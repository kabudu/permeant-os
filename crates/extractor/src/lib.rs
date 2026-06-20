use anyhow::{bail, Context, Result};
use permeant_transpiler::Tensor;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::Write;
use std::process::{Command, Stdio};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExtractorMode {
    Mock,
    JsonCommand,
}

#[derive(Debug, Serialize)]
struct ExtractorRequest {
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
}

#[derive(Debug, Deserialize)]
struct ExtractorTensor {
    name: String,
    shape: Vec<usize>,
    data: Vec<f32>,
}

#[derive(Debug, Deserialize)]
struct ExtractorResponse {
    tensors: Vec<ExtractorTensor>,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum ExtractorResponseEnvelope {
    Response(ExtractorResponse),
    Tensors(Vec<ExtractorTensor>),
}

pub fn extract_kv_cache(
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
) -> Result<HashMap<String, Tensor>> {
    match extractor_mode() {
        ExtractorMode::Mock => extract_mock_kv_cache(seq_len, n_layers, n_kv_heads, head_dim),
        ExtractorMode::JsonCommand => extract_via_command(seq_len, n_layers, n_kv_heads, head_dim),
    }
}

fn extractor_mode() -> ExtractorMode {
    match std::env::var("PERMEANT_EXTRACTOR_MODE") {
        Ok(value) if value.eq_ignore_ascii_case("json_command") => ExtractorMode::JsonCommand,
        _ => ExtractorMode::Mock,
    }
}

fn extract_mock_kv_cache(
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
) -> Result<HashMap<String, Tensor>> {
    let mut extracted = HashMap::new();
    let tensor_len = n_kv_heads
        .checked_mul(seq_len)
        .and_then(|v| v.checked_mul(head_dim))
        .context("Tensor size overflow during mock extraction")?;

    for layer_idx in 0..n_layers {
        let mut key_data = Vec::with_capacity(tensor_len);
        let mut value_data = Vec::with_capacity(tensor_len);

        for token_idx in 0..seq_len {
            for kv_head_idx in 0..n_kv_heads {
                for dim_idx in 0..head_dim {
                    let base = ((layer_idx * 1_000_000)
                        + (token_idx * 10_000)
                        + (kv_head_idx * 100)
                        + dim_idx) as f32;
                    key_data.push(base / 10_000.0);
                    value_data.push((base + 1.0) / 10_000.0);
                }
            }
        }

        let shape = vec![1, n_kv_heads, seq_len, head_dim];
        extracted.insert(
            format!("layer.{}.key", layer_idx),
            Tensor::new(key_data, shape.clone()),
        );
        extracted.insert(
            format!("layer.{}.value", layer_idx),
            Tensor::new(value_data, shape.clone()),
        );
    }

    Ok(extracted)
}

fn extract_via_command(
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
) -> Result<HashMap<String, Tensor>> {
    let command = std::env::var("PERMEANT_EXTRACTOR_CMD")
        .context("PERMEANT_EXTRACTOR_CMD must be set when PERMEANT_EXTRACTOR_MODE=json_command")?;

    let request = ExtractorRequest {
        seq_len,
        n_layers,
        n_kv_heads,
        head_dim,
    };
    let request_bytes = serde_json::to_vec(&request)?;

    let mut child = Command::new("sh")
        .arg("-c")
        .arg(&command)
        .env("PERMEANT_SEQ_LEN", seq_len.to_string())
        .env("PERMEANT_N_LAYERS", n_layers.to_string())
        .env("PERMEANT_N_KV_HEADS", n_kv_heads.to_string())
        .env("PERMEANT_HEAD_DIM", head_dim.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("Failed to start extractor command: {}", command))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(&request_bytes)
            .context("Failed to write extractor request to stdin")?;
    }

    let output = child
        .wait_with_output()
        .context("Failed to wait for extractor command")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("Extractor command failed: {}", stderr.trim());
    }

    let response: ExtractorResponseEnvelope = serde_json::from_slice(&output.stdout)
        .context("Failed to parse extractor command JSON output")?;

    let tensors = match response {
        ExtractorResponseEnvelope::Response(response) => response.tensors,
        ExtractorResponseEnvelope::Tensors(tensors) => tensors,
    };

    let mut extracted = HashMap::new();
    for tensor in tensors {
        extracted.insert(tensor.name, Tensor::new(tensor.data, tensor.shape));
    }

    for layer_idx in 0..n_layers {
        for suffix in ["key", "value"] {
            let name = format!("layer.{}.{}", layer_idx, suffix);
            if !extracted.contains_key(&name) {
                bail!(
                    "Extractor command output is missing required tensor '{}'",
                    name
                );
            }
        }
    }

    Ok(extracted)
}
