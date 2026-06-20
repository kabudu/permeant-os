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
            Ok(value) if value.eq_ignore_ascii_case("json_command") => {
                let command =
                    std::env::var("PERMEANT_INJECTOR_CMD").unwrap_or_else(|_| "".to_string());
                InjectorBackend::JsonCommand { command }
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
            InjectorBackend::JsonCommand { command } => {
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
                run_injector_command(command, &request)
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
            InjectorBackend::JsonCommand { command } => {
                if command.trim().is_empty() {
                    bail!(
                        "PERMEANT_INJECTOR_CMD must be set when PERMEANT_INJECTOR_MODE=json_command"
                    );
                }

                let request = InjectorRequest::VerifyContinuation {
                    block_size: self.block_size,
                    expected_hashes: expected_hashes.to_vec(),
                };
                run_injector_command(command, &request)
            }
        }
    }
}

fn run_injector_command(command: &str, request: &InjectorRequest) -> Result<()> {
    let request_bytes = serde_json::to_vec(request)?;

    let mut child = Command::new("sh")
        .arg("-c")
        .arg(command)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("Failed to start injector command: {}", command))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(&request_bytes)
            .context("Failed to write injector request to stdin")?;
    }

    let output = child
        .wait_with_output()
        .context("Failed to wait for injector command")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("Injector command failed: {}", stderr.trim());
    }

    let response: InjectorResponse = if output.stdout.is_empty() {
        InjectorResponse {
            success: Some(true),
            error: None,
            missing_hashes: None,
        }
    } else {
        serde_json::from_slice(&output.stdout)
            .context("Failed to parse injector command JSON output")?
    };

    if response.success.unwrap_or(true) {
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
