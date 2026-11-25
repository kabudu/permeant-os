use anyhow::{bail, Context, Result};
use permeant_transpiler::Tensor;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::Write;
use std::process::{Command, Stdio};

#[derive(Debug, Clone)]
#[allow(non_camel_case_types)]
pub struct KVConnectorBase_V1 {
    block_size: usize,
    backend: InjectorBackend,
}

#[derive(Debug, Clone)]
enum InjectorBackend {
    Mock {
        physical_cache: HashMap<String, HashMap<String, Tensor>>,
    },
    JsonCommand {
        command: String,
        binary_blocks: bool,
    },
}

#[derive(Debug, Serialize)]
#[serde(tag = "action", rename_all = "snake_case")]
enum InjectorRequest {
    InjectBlock {
        block_size: usize,
        block_hash: String,
        tensors: Vec<SerializedTensor>,
    },
    VerifyContinuation {
        block_size: usize,
        expected_hashes: Vec<String>,
    },
}

#[derive(Debug, Serialize)]
struct SerializedTensor {
    name: String,
    shape: Vec<usize>,
    data: Vec<f32>,
}

#[derive(Debug, Deserialize, Default)]
struct InjectorResponse {
    success: Option<bool>,
    error: Option<String>,
    missing_hashes: Option<Vec<String>>,
}

impl KVConnectorBase_V1 {
    pub fn new(block_size: usize) -> Self {
        let backend = match std::env::var("PERMEANT_INJECTOR_MODE") {
            Ok(value)
                if value.eq_ignore_ascii_case("json_command")
                    || value.eq_ignore_ascii_case("binary_command") =>
            {
                let command =
                    std::env::var("PERMEANT_INJECTOR_CMD").unwrap_or_else(|_| "".to_string());
                InjectorBackend::JsonCommand {
                    command,
                    binary_blocks: value.eq_ignore_ascii_case("binary_command"),
                }
            }
            _ => InjectorBackend::Mock {
                physical_cache: HashMap::new(),
            },
        };

        Self {
            block_size,
            backend,
        }
    }

    pub fn inject_block_tensors(
        &mut self,
        block_hash: String,
        tensors: HashMap<String, Tensor>,
    ) -> Result<()> {
        match &mut self.backend {
            InjectorBackend::Mock { physical_cache } => {
                physical_cache.insert(block_hash, tensors);
                Ok(())
            }
            InjectorBackend::JsonCommand {
                command,
                binary_blocks,
            } => {
                if command.trim().is_empty() {
                    bail!(
                        "PERMEANT_INJECTOR_CMD must be set when PERMEANT_INJECTOR_MODE=json_command"
                    );
                }

                let request = InjectorRequest::InjectBlock {
                    block_size: self.block_size,
                    block_hash,
                    tensors: tensors
                        .into_iter()
                        .map(|(name, tensor)| SerializedTensor {
                            name,
                            shape: tensor.shape,
                            data: tensor.data,
                        })
                        .collect(),
                };
                run_injector_command(command, &request, *binary_blocks)
            }
        }
    }

    pub fn verify_continuation(&self, expected_hashes: &[String]) -> Result<()> {
        match &self.backend {
            InjectorBackend::Mock { physical_cache } => {
                let missing: Vec<String> = expected_hashes
                    .iter()
                    .filter(|hash| !physical_cache.contains_key((*hash).as_str()))
                    .cloned()
                    .collect();

                if missing.is_empty() {
                    Ok(())
                } else {
                    bail!("Missing migrated KV blocks in target cache: {:?}", missing)
                }
            }
            InjectorBackend::JsonCommand {
                command,
                binary_blocks,
            } => {
                if command.trim().is_empty() {
                    bail!(
                        "PERMEANT_INJECTOR_CMD must be set when PERMEANT_INJECTOR_MODE=json_command"
                    );
                }

                let request = InjectorRequest::VerifyContinuation {
                    block_size: self.block_size,
                    expected_hashes: expected_hashes.to_vec(),
                };
                run_injector_command(command, &request, *binary_blocks)
            }
        }
    }
}

// PKV1 is scoped to the local vLLM injector handoff; it does not change USXF.
const MAX_BINARY_HEADER: usize = 64 * 1024;
const MAX_BINARY_BLOCK: usize = 64 * 1024 * 1024;

#[derive(Serialize)]
struct BinaryTensor<'a> {
    name: &'a str,
    shape: &'a [usize],
}

#[derive(Serialize)]
struct BinaryBlock<'a> {
    block_hash: &'a str,
    block_size: usize,
    tensors: Vec<BinaryTensor<'a>>,
}

fn encode_binary_block(
    block_hash: &str,
    block_size: usize,
    tensors: &[SerializedTensor],
) -> Result<Vec<u8>> {
    let mut size = 8usize;
    for tensor in tensors {
        let elements = tensor
            .shape
            .iter()
            .try_fold(1usize, |count, dim| count.checked_mul(*dim));
        if tensor.shape.len() != 4
            || tensor.shape[0] != 1
            || tensor.shape.contains(&0)
            || elements != Some(tensor.data.len())
        {
            bail!("invalid preblocked injector tensor shape: {}", tensor.name);
        }
        let data_bytes = tensor
            .data
            .len()
            .checked_mul(4)
            .context("injector tensor too large")?;
        size = size
            .checked_add(data_bytes)
            .context("injector block too large")?;
        if size > MAX_BINARY_BLOCK {
            bail!("binary injector block exceeds size limit");
        }
    }
    let header = serde_json::to_vec(&BinaryBlock {
        block_hash,
        block_size,
        tensors: tensors
            .iter()
            .map(|tensor| BinaryTensor {
                name: &tensor.name,
                shape: &tensor.shape,
            })
            .collect(),
    })?;
    if header.len() > MAX_BINARY_HEADER || size + header.len() > MAX_BINARY_BLOCK {
        bail!("binary injector block exceeds size limit");
    }
    let header_len = u32::try_from(header.len()).context("injector header too large")?;
    let mut bytes = Vec::with_capacity(size + header.len());
    bytes.extend_from_slice(b"PKV1");
    bytes.extend_from_slice(&header_len.to_le_bytes());
    bytes.extend_from_slice(&header);
    for tensor in tensors {
        bytes.extend(tensor.data.iter().flat_map(|value| value.to_le_bytes()));
    }
    Ok(bytes)
}

fn run_injector_command(
    command: &str,
    request: &InjectorRequest,
    binary_blocks: bool,
) -> Result<()> {
    let start = std::time::Instant::now();
    let (request_bytes, binary_request) = match request {
        InjectorRequest::InjectBlock {
            block_hash,
            block_size,
            tensors,
        } if binary_blocks => (encode_binary_block(block_hash, *block_size, tensors)?, true),
        _ => (serde_json::to_vec(request)?, false),
    };
    let encoded_at = std::time::Instant::now();

    let mut child = Command::new("sh")
        .arg("-c")
        .arg(command)
        .env(
            "PERMEANT_VLLM_INJECTOR_BINARY_REQUEST",
            if binary_request { "1" } else { "0" },
        )
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("Failed to start injector command: {}", command))?;
    let spawned_at = std::time::Instant::now();

    let write = child
        .stdin
        .take()
        .context("missing injector stdin")
        .and_then(|mut stdin| {
            stdin
                .write_all(&request_bytes)
                .context("Failed to write injector request to stdin")
        });
    let written_at = std::time::Instant::now();

    let output = child
        .wait_with_output()
        .context("Failed to wait for injector command")?;
    if std::env::var("PERMEANT_INJECTOR_PROFILE").as_deref() == Ok("1") {
        let ms = |duration: std::time::Duration| duration.as_secs_f64() * 1000.0;
        eprintln!(
            "[Injector] request_bytes={} encode_ms={:.3} spawn_ms={:.3} stdin_ms={:.3} after_stdin_ms={:.3}",
            request_bytes.len(),
            ms(encoded_at.duration_since(start)),
            ms(spawned_at.duration_since(encoded_at)),
            ms(written_at.duration_since(spawned_at)),
            ms(written_at.elapsed()),
        );
        eprint!("{}", String::from_utf8_lossy(&output.stderr));
    }
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("Injector command failed: {}", stderr.trim());
    }
    write?;

    let response: InjectorResponse = if output.stdout.is_empty() {
        InjectorResponse {
            success: Some(!binary_blocks),
            error: None,
            missing_hashes: None,
        }
    } else {
        serde_json::from_slice(&output.stdout)
            .context("Failed to parse injector command JSON output")?
    };

    if response.success.unwrap_or(!binary_blocks) {
        Ok(())
    } else if let Some(missing) = response.missing_hashes {
        bail!("Injector command reported missing hashes: {:?}", missing)
    } else {
        bail!(
            "Injector command reported failure: {}",
            response
                .error
                .unwrap_or_else(|| "unknown error".to_string())
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn binary_block_preserves_f32_bits_and_rejects_shape_mismatch() {
        let tensor = SerializedTensor {
            name: "layer.0.key".into(),
            shape: vec![1, 1, 1, 3],
            data: vec![1.5, -0.0, f32::from_bits(0x3f800001)],
        };
        let frame =
            encode_binary_block("checkpoint-block", 3, std::slice::from_ref(&tensor)).unwrap();
        assert_eq!(&frame[..4], b"PKV1");
        let end = 8 + u32::from_le_bytes(frame[4..8].try_into().unwrap()) as usize;
        let meta: serde_json::Value = serde_json::from_slice(&frame[8..end]).unwrap();
        assert_eq!(meta["tensors"][0]["shape"], serde_json::json!([1, 1, 1, 3]));
        assert!(meta["tensors"][0].get("data").is_none());
        assert_eq!(&frame[end..], &[0, 0, 192, 63, 0, 0, 0, 128, 1, 0, 128, 63]);
        let mut invalid = tensor;
        invalid.data.pop();
        assert!(encode_binary_block("checkpoint-block", 3, &[invalid]).is_err());
    }
}
