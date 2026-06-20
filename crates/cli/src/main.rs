use anyhow::{bail, Context, Result};
use chrono::Utc;
use clap::{Parser, Subcommand, ValueEnum};
use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use tokio::net::{TcpListener, TcpStream};

use permeant_extractor::extract_kv_cache;
use permeant_injector::KVConnectorBase_V1;
use permeant_orchestrator::{MigrationOrchestrator, ResourcePolicy};
use permeant_transpiler::{
    canonical_to_vllm_block_key, canonical_to_vllm_block_value, compute_optimal_scale,
    dequantize_e4m3_scaled, dequantize_qatq_i4, quantize_e4m3_scaled, quantize_qatq_i4, Tensor,
};
use permeant_transport::{
    compute_crc32, recv_message, send_message, verify_chunk_crc32, AgentGraphBinding,
    AgentGraphBindingArtifact, AgentGraphBindingKvSpan, MigrationMessage,
};
use usxf_core::{
    compute_sha256, compute_token_block_hashes, open_packet, seal_packet, validate_header,
    AttentionType, ExchangeDtype, ModelCacheSpec, ModelIdentity, UsxfHeader,
};

#[derive(Parser, Debug)]
#[command(name = "permeantos-cli")]
#[command(about = "PermeantOS State-Fluid Hypervisor Control CLI", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
enum TransferCodec {
    None,
    Fp8,
    Qatq,
}

impl TransferCodec {
    fn manifest_value(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Fp8 => "fp8",
            Self::Qatq => "qatq",
        }
    }

    fn header_scheme(self) -> Option<&'static str> {
        match self {
            Self::None => None,
            Self::Fp8 => Some("fp8"),
            Self::Qatq => Some("qatq"),
        }
    }
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Start a migration daemon target listener
    Daemon {
        #[arg(short, long, default_value = "127.0.0.1:9099")]
        addr: String,
    },
    /// Run a complete local simulation of KV Cache migration
    SimMigrate {
        #[arg(short, long, default_value = "127.0.0.1:9099")]
        target_addr: String,
        #[arg(short, long, default_value_t = 8192)]
        seq_len: usize,
        #[arg(short, long)]
        quant: bool, // Enable FP8 transfer quantization
        #[arg(long, value_enum, default_value_t = TransferCodec::None)]
        transfer_codec: TransferCodec,
        #[arg(long)]
        agent_graph_manifest: Option<String>,
    },
    /// Inspect a serialized USXF JSON header or package
    Inspect {
        #[arg(short, long)]
        file: String,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Daemon { addr } => {
            println!("Starting PermeantOS Hypervisor Daemon on {}...", addr);
            run_daemon(&addr).await?;
        }
        Commands::SimMigrate {
            target_addr,
            seq_len,
            quant,
            transfer_codec,
            agent_graph_manifest,
        } => {
            let selected_codec = if quant && transfer_codec == TransferCodec::None {
                TransferCodec::Fp8
            } else {
                transfer_codec
            };
            println!(
                "Starting end-to-end migration simulation to {} (Context: {} tokens, Transfer Codec: {})...",
                target_addr,
                seq_len,
                selected_codec.manifest_value()
            );
            run_sim_migrate(
                &target_addr,
                seq_len,
                selected_codec,
                agent_graph_manifest.as_deref(),
            )
            .await?;
        }
        Commands::Inspect { file } => {
            run_inspect(&file)?;
        }
    }

    Ok(())
}

async fn run_daemon(addr_str: &str) -> Result<()> {
    let addr: SocketAddr = addr_str.parse().context("Invalid socket address")?;
    let listener = TcpListener::bind(addr)
        .await
        .context("Failed to bind socket")?;

    let mut orchestrator = MigrationOrchestrator::new(ResourcePolicy::default());
    let mut injector = KVConnectorBase_V1::new(256); // 256 token block size

    // Hardcoded keys for simulation purposes
    let aes_key = [7u8; 32];

    println!("Daemon listening for migration requests. Press Ctrl+C to stop.");

    loop {
        let (mut socket, peer) = listener.accept().await?;
        println!("\n[Daemon] Incoming connection from {:?}", peer);
        if let Err(err) =
            handle_migration_connection(&mut socket, &mut orchestrator, &mut injector, &aes_key)
                .await
        {
            eprintln!(
                "[Daemon] Connection {:?} ended without commit: {}",
                peer, err
            );
        }
    }
}

async fn handle_migration_connection(
    socket: &mut TcpStream,
    orchestrator: &mut MigrationOrchestrator,
    injector: &mut KVConnectorBase_V1,
    aes_key: &[u8; 32],
) -> Result<()> {
    let msg = recv_message(socket).await?;
    if let MigrationMessage::CapabilityRequest {
        model_architecture,
        attention_type,
        seq_len,
    } = msg
    {
        println!(
            "[Daemon] Received migration capability request for: {}, Attn: {}, SeqLen: {}",
            model_architecture, attention_type, seq_len
        );

        let target_device = describe_runtime_target_device();
        let response = if seq_len > 131072 {
            MigrationMessage::CapabilityResponse {
                accepted: false,
                error_message: Some(
                    "Context size exceeds hypervisor hardware memory limits".to_string(),
                ),
                target_device: target_device.clone(),
            }
        } else {
            MigrationMessage::CapabilityResponse {
                accepted: true,
                error_message: None,
                target_device,
            }
        };

        send_message(socket, &response).await?;
        if let MigrationMessage::CapabilityResponse {
            accepted: false, ..
        } = response
        {
            println!("[Daemon] Rejected migration capability (context too large)");
            return Ok(());
        }
    } else {
        bail!("Protocol violation: Expected CapabilityRequest");
    }

    let msg = recv_message(socket).await?;
    let header = if let MigrationMessage::HeaderEnvelope(envelope) = msg {
        println!(
            "[Daemon] Received encrypted USXF header envelope. Verifying signature & decrypting..."
        );
        let plaintext =
            open_packet(&envelope, aes_key).context("Header decryption or signature failed")?;
        let header: UsxfHeader =
            serde_json::from_slice(&plaintext).context("Failed to deserialize USXF header")?;

        validate_header(&header).context("USXF metadata validation failed")?;
        println!(
            "[Daemon] Header verified. Model Identity: {}. Config Hash: {}",
            header.model_architecture, header.model_identity.config_hash
        );

        send_message(socket, &MigrationMessage::HeaderAck { accepted: true }).await?;
        header
    } else {
        bail!("Protocol violation: Expected HeaderEnvelope");
    };

    println!("[Daemon] Streaming payload chunks starting...");
    let expected_blocks = header.seq_len.div_ceil(header.block_size);
    let mut accumulated_blocks: HashMap<String, HashMap<String, Tensor>> = HashMap::new();
    let mut received_chunks: HashSet<(u32, u32, String)> = HashSet::new();

    for _ in 0..(header.model_cache_spec.n_layers * 2 * expected_blocks) {
        let chunk_msg = recv_message(socket).await?;
        if !verify_chunk_crc32(&chunk_msg)? {
            bail!("Payload chunk CRC32 checksum mismatch!");
        }

        if let MigrationMessage::PayloadChunk {
            chunk_index,
            layer_index,
            tensor_name,
            data,
            ..
        } = chunk_msg
        {
            let block_hash = validate_payload_chunk_metadata(
                &header,
                chunk_index,
                layer_index,
                &tensor_name,
                &mut received_chunks,
            )?;
            let expected_float_count = block_float_count(&header, &tensor_name);
            let decrypted_data = match header
                .transfer_quantization
                .as_ref()
                .map(|quant| quant.scheme.as_str())
            {
                Some("fp8") => dequantize_e4m3_scaled(&data, 0.1),
                Some("qatq") => dequantize_qatq_i4(&data, expected_float_count)?,
                Some(other) => bail!("Unsupported transfer quantization scheme: {other}"),
                None => {
                    let mut floats = vec![0.0f32; data.len() / 4];
                    for (i, chunk) in data.chunks_exact(4).enumerate() {
                        let bytes: [u8; 4] = chunk.try_into()?;
                        floats[i] = f32::from_be_bytes(bytes);
                    }
                    floats
                }
            };

            if decrypted_data.len() != expected_float_count {
                bail!(
                    "Decoded payload length mismatch for {} block {}: expected {}, got {}",
                    tensor_name,
                    chunk_index,
                    expected_float_count,
                    decrypted_data.len()
                );
            }

            let shape = if tensor_name.ends_with(".key") {
                vec![
                    1,
                    header.model_cache_spec.n_kv_heads,
                    header.model_cache_spec.head_dim,
                    header.block_size,
                ]
            } else {
                vec![
                    1,
                    header.model_cache_spec.n_kv_heads,
                    header.block_size,
                    header.model_cache_spec.head_dim,
                ]
            };

            let block_tensor = Tensor::new(decrypted_data, shape);
            accumulated_blocks
                .entry(block_hash.clone())
                .or_default()
                .insert(tensor_name, block_tensor);
            send_message(socket, &MigrationMessage::ChunkAck { chunk_index }).await?;
        } else {
            bail!("Protocol violation: Expected PayloadChunk");
        }
    }

    println!(
        "[Daemon] All layers and blocks streamed. Waiting for graph binding or commit request..."
    );
    let mut msg = recv_message(socket).await?;
    if let MigrationMessage::AgentGraphBinding(binding) = msg {
        println!(
            "[Daemon] Received Agent Memory Graph binding. Validating graph/KV transaction evidence..."
        );
        if let Err(error) = validate_agent_graph_binding(&binding, &header) {
            let error_message = error.to_string();
            send_message(
                socket,
                &MigrationMessage::AgentGraphBindingAck {
                    accepted: false,
                    error_message: Some(error_message.clone()),
                },
            )
            .await?;
            orchestrator.record_failure();
            bail!("Agent Memory Graph binding rejected: {}", error_message);
        }
        send_message(
            socket,
            &MigrationMessage::AgentGraphBindingAck {
                accepted: true,
                error_message: None,
            },
        )
        .await?;
        println!(
            "[Daemon] Agent Memory Graph binding verified for {} KV span(s).",
            binding.kv_spans.len()
        );
        msg = recv_message(socket).await?;
    }

    println!("[Daemon] Injecting staged blocks into KVConnectorBase_V1...");
    for (hash, tensors) in accumulated_blocks {
        injector.inject_block_tensors(hash, tensors)?;
    }

    if let MigrationMessage::CommitRequest = msg {
        println!("[Daemon] Commit requested. Running numerical continuation validation...");
        injector.verify_continuation(&header.block_hashes)?;

        println!("[Daemon] Validation passed. Committing migration state.");
        send_message(
            socket,
            &MigrationMessage::CommitResponse {
                success: true,
                error_message: None,
            },
        )
        .await?;
        orchestrator.record_success();
        println!("[Daemon] Migration COMMITTED successfully!");
        Ok(())
    } else {
        bail!("Protocol violation: Expected CommitRequest");
    }
}

fn validate_payload_chunk_metadata(
    header: &UsxfHeader,
    chunk_index: u32,
    layer_index: u32,
    tensor_name: &str,
    received_chunks: &mut HashSet<(u32, u32, String)>,
) -> Result<String> {
    let block_hash = header
        .block_hashes
        .get(chunk_index as usize)
        .with_context(|| {
            format!(
                "Payload chunk index {} exceeds advertised block count {}",
                chunk_index,
                header.block_hashes.len()
            )
        })?
        .clone();

    if layer_index as usize >= header.model_cache_spec.n_layers {
        bail!(
            "Payload chunk layer index {} exceeds advertised layer count {}",
            layer_index,
            header.model_cache_spec.n_layers
        );
    }

    let expected_key_name = format!("layer.{}.key", layer_index);
    let expected_value_name = format!("layer.{}.value", layer_index);
    if tensor_name != expected_key_name && tensor_name != expected_value_name {
        bail!(
            "Payload chunk tensor name {} does not match layer {}",
            tensor_name,
            layer_index
        );
    }

    let chunk_key = (chunk_index, layer_index, tensor_name.to_string());
    if !received_chunks.insert(chunk_key) {
        bail!(
            "Duplicate payload chunk for block {}, layer {}, tensor {}",
            chunk_index,
            layer_index,
            tensor_name
        );
    }

    Ok(block_hash)
}

#[derive(serde::Serialize)]
struct EnvironmentSnapshot {
    os: String,
    arch: String,
    hostname: String,
    git_commit: String,
    process_id: u32,
    current_dir: String,
}

#[derive(serde::Serialize)]
struct MigrationManifest {
    manifest_version: String,
    run_id: String,
    timestamp: String,
    source_environment: EnvironmentSnapshot,
    target_addr: String,
    target_device: String,
    model_architecture: String,
    model_identity: String,
    usxf_version: String,
    attention_type: String,
    sequence_length: usize,
    batch_size: usize,
    layers: usize,
    n_q_heads: usize,
    n_kv_heads: usize,
    head_dim: usize,
    block_size: usize,
    expected_blocks: usize,
    block_hash_count: usize,
    dtype: String,
    source_quantization: String,
    transfer_quantization: String,
    uncompressed_bytes: u64,
    transferred_bytes: u64,
    compression_ratio: f64,
    chunks_sent: u64,
    average_chunk_bytes: f64,
    handshake_time_ms: f64,
    header_time_ms: f64,
    transfer_time_ms: f64,
    commit_time_ms: f64,
    total_time_ms: f64,
    effective_bandwidth_gbps: f64,
    phase_status: String,
    success: bool,
    error_message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    agent_graph: Option<AgentGraphManifest>,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct AgentGraphArtifactHash {
    path: String,
    sha256: String,
    size_bytes: Option<u64>,
}

#[derive(Clone, Debug, serde::Serialize)]
struct AgentGraphManifest {
    manifest_path: String,
    graph_path: String,
    graph_hash: String,
    prompt_byte_hash: Option<String>,
    prompt_token_hash: Option<String>,
    tokenizer_hash: Option<String>,
    kv_hash: Option<String>,
    kv_spans: Vec<AgentGraphKvSpan>,
    artifacts: Vec<AgentGraphArtifactHash>,
}

impl AgentGraphManifest {
    fn to_binding(&self, header: &UsxfHeader) -> AgentGraphBinding {
        AgentGraphBinding {
            manifest_path: self.manifest_path.clone(),
            graph_path: self.graph_path.clone(),
            graph_hash: self.graph_hash.clone(),
            prompt_byte_hash: self.prompt_byte_hash.clone(),
            prompt_token_hash: self.prompt_token_hash.clone(),
            tokenizer_hash: self.tokenizer_hash.clone(),
            kv_hash: self.kv_hash.clone(),
            kv_spans: self
                .kv_spans
                .iter()
                .map(|span| AgentGraphBindingKvSpan {
                    node_id: span.node_id.clone(),
                    token_start: span.token_start,
                    token_end: span.token_end,
                    cache_ref: span.cache_ref.clone(),
                    tokenizer_hash: span.tokenizer_hash.clone(),
                    block_hashes: block_hashes_for_span(header, span.token_start, span.token_end),
                })
                .collect(),
            artifacts: self
                .artifacts
                .iter()
                .map(|artifact| AgentGraphBindingArtifact {
                    path: artifact.path.clone(),
                    sha256: artifact.sha256.clone(),
                    size_bytes: artifact.size_bytes,
                })
                .collect(),
        }
    }
}

#[derive(serde::Deserialize)]
struct AgentGraphPackageManifest {
    graph_path: String,
    graph_hash: String,
    prompt: Option<AgentGraphPromptManifest>,
    kv: Option<AgentGraphKvManifest>,
    kv_spans: Option<Vec<AgentGraphPackageKvSpan>>,
    artifacts: Option<Vec<AgentGraphPackageArtifact>>,
}

#[derive(serde::Deserialize)]
struct AgentGraphPromptManifest {
    byte_hash: Option<String>,
    token_hash: Option<String>,
    tokenizer_hash: Option<String>,
}

#[derive(serde::Deserialize)]
struct AgentGraphKvManifest {
    kv_hash: Option<String>,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct AgentGraphKvSpan {
    node_id: String,
    token_start: usize,
    token_end: usize,
    cache_ref: String,
    tokenizer_hash: Option<String>,
    block_hashes: Vec<String>,
}

#[derive(serde::Deserialize)]
struct AgentGraphPackageKvSpan {
    node_id: String,
    token_start: usize,
    token_end: usize,
    cache_ref: String,
    tokenizer_hash: Option<String>,
    block_hashes: Option<Vec<String>>,
}

#[derive(serde::Deserialize)]
struct AgentGraphPackageArtifact {
    path: String,
    sha256: String,
    size_bytes: Option<u64>,
}

fn collect_environment_snapshot() -> EnvironmentSnapshot {
    let hostname = std::env::var("HOSTNAME")
        .or_else(|_| std::env::var("COMPUTERNAME"))
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            std::process::Command::new("hostname")
                .output()
                .ok()
                .and_then(|output| String::from_utf8(output.stdout).ok())
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| "unknown".to_string())
        });

    let git_commit = std::process::Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .output()
        .ok()
        .and_then(|output| {
            if output.status.success() {
                String::from_utf8(output.stdout).ok()
            } else {
                None
            }
        })
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "unknown".to_string());

    EnvironmentSnapshot {
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        hostname,
        git_commit,
        process_id: std::process::id(),
        current_dir: std::env::current_dir()
            .ok()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "unknown".to_string()),
    }
}

fn describe_runtime_target_device() -> String {
    let env = collect_environment_snapshot();
    format!("{}/{}/{}", env.os, env.arch, env.hostname)
}

fn write_migration_manifest(manifest: &MigrationManifest) -> Result<String> {
    let manifest_str = serde_json::to_string_pretty(manifest)?;
    let filename = format!("{}-manifest.json", manifest.run_id);
    std::fs::write(&filename, &manifest_str)?;
    Ok(filename)
}

fn ensure_sha256_field(field_name: &str, value: &str) -> Result<()> {
    let digest = value
        .strip_prefix("sha256:")
        .with_context(|| format!("{} must start with sha256:", field_name))?;
    if digest.len() != 64 || !digest.chars().all(|ch| ch.is_ascii_hexdigit()) {
        bail!("{} must contain a 64-character sha256 digest", field_name);
    }
    Ok(())
}

fn validate_optional_sha256(field_name: &str, value: Option<&String>) -> Result<()> {
    if let Some(value) = value {
        ensure_sha256_field(field_name, value)?;
    }
    Ok(())
}

fn validate_agent_graph_kv_span(
    span: AgentGraphPackageKvSpan,
    index: usize,
) -> Result<AgentGraphKvSpan> {
    if span.node_id.trim().is_empty() {
        bail!("agent_graph.kv_spans[{}].node_id must not be empty", index);
    }
    if span.cache_ref.trim().is_empty() {
        bail!(
            "agent_graph.kv_spans[{}].cache_ref must not be empty",
            index
        );
    }
    if span.token_end <= span.token_start {
        bail!(
            "agent_graph.kv_spans[{}].token_end must be greater than token_start",
            index
        );
    }
    validate_optional_sha256(
        &format!("agent_graph.kv_spans[{}].tokenizer_hash", index),
        span.tokenizer_hash.as_ref(),
    )?;

    let block_hashes = span.block_hashes.unwrap_or_default();
    for block_hash in &block_hashes {
        ensure_sha256_field(
            &format!("agent_graph.kv_spans[{}].block_hashes", index),
            block_hash,
        )?;
    }

    Ok(AgentGraphKvSpan {
        node_id: span.node_id,
        token_start: span.token_start,
        token_end: span.token_end,
        cache_ref: span.cache_ref,
        tokenizer_hash: span.tokenizer_hash,
        block_hashes,
    })
}

fn block_hashes_for_span(header: &UsxfHeader, token_start: usize, token_end: usize) -> Vec<String> {
    if token_end <= token_start || token_start >= header.seq_len || header.block_size == 0 {
        return Vec::new();
    }
    let start_block = token_start / header.block_size;
    let end_token = token_end.min(header.seq_len) - 1;
    let end_block = end_token / header.block_size;

    header
        .block_hashes
        .get(start_block..=end_block)
        .unwrap_or(&[])
        .to_vec()
}

fn load_agent_graph_manifest(path: Option<&str>) -> Result<Option<AgentGraphManifest>> {
    let Some(path) = path else {
        return Ok(None);
    };
    let manifest_bytes = std::fs::read(path)
        .with_context(|| format!("Failed to read Agent Memory Graph manifest at {}", path))?;
    let package: AgentGraphPackageManifest = serde_json::from_slice(&manifest_bytes)
        .with_context(|| format!("Failed to parse Agent Memory Graph manifest at {}", path))?;

    ensure_sha256_field("agent_graph.graph_hash", &package.graph_hash)?;
    if let Some(prompt) = &package.prompt {
        validate_optional_sha256("agent_graph.prompt.byte_hash", prompt.byte_hash.as_ref())?;
        validate_optional_sha256("agent_graph.prompt.token_hash", prompt.token_hash.as_ref())?;
        validate_optional_sha256(
            "agent_graph.prompt.tokenizer_hash",
            prompt.tokenizer_hash.as_ref(),
        )?;
    }
    if let Some(kv) = &package.kv {
        validate_optional_sha256("agent_graph.kv.kv_hash", kv.kv_hash.as_ref())?;
    }

    let mut kv_spans = Vec::new();
    for (index, span) in package.kv_spans.unwrap_or_default().into_iter().enumerate() {
        kv_spans.push(validate_agent_graph_kv_span(span, index)?);
    }

    let mut artifacts = Vec::new();
    for artifact in package.artifacts.unwrap_or_default() {
        ensure_sha256_field("agent_graph.artifacts.sha256", &artifact.sha256)?;
        artifacts.push(AgentGraphArtifactHash {
            path: artifact.path,
            sha256: artifact.sha256,
            size_bytes: artifact.size_bytes,
        });
    }

    Ok(Some(AgentGraphManifest {
        manifest_path: path.to_string(),
        graph_path: package.graph_path,
        graph_hash: package.graph_hash,
        prompt_byte_hash: package
            .prompt
            .as_ref()
            .and_then(|prompt| prompt.byte_hash.clone()),
        prompt_token_hash: package
            .prompt
            .as_ref()
            .and_then(|prompt| prompt.token_hash.clone()),
        tokenizer_hash: package
            .prompt
            .as_ref()
            .and_then(|prompt| prompt.tokenizer_hash.clone()),
        kv_hash: package.kv.as_ref().and_then(|kv| kv.kv_hash.clone()),
        kv_spans,
        artifacts,
    }))
}

fn validate_agent_graph_binding(binding: &AgentGraphBinding, header: &UsxfHeader) -> Result<()> {
    if binding.manifest_path.trim().is_empty() {
        bail!("agent graph binding manifest_path must not be empty");
    }
    if binding.graph_path.trim().is_empty() {
        bail!("agent graph binding graph_path must not be empty");
    }
    ensure_sha256_field("agent_graph.graph_hash", &binding.graph_hash)?;
    validate_optional_sha256(
        "agent_graph.prompt_byte_hash",
        binding.prompt_byte_hash.as_ref(),
    )?;
    validate_optional_sha256(
        "agent_graph.prompt_token_hash",
        binding.prompt_token_hash.as_ref(),
    )?;
    validate_optional_sha256(
        "agent_graph.tokenizer_hash",
        binding.tokenizer_hash.as_ref(),
    )?;
    validate_optional_sha256("agent_graph.kv_hash", binding.kv_hash.as_ref())?;

    if binding.prompt_token_hash.is_none() {
        bail!("agent graph binding must include prompt_token_hash");
    }
    if binding.tokenizer_hash.is_none() {
        bail!("agent graph binding must include tokenizer_hash");
    }
    if binding.kv_hash.is_none() {
        bail!("agent graph binding must include kv_hash");
    }
    if binding.kv_spans.is_empty() {
        bail!("agent graph binding must include at least one KV span");
    }

    let migrated_blocks: HashSet<&str> = header.block_hashes.iter().map(String::as_str).collect();
    for (index, span) in binding.kv_spans.iter().enumerate() {
        if span.node_id.trim().is_empty() {
            bail!("agent_graph.kv_spans[{}].node_id must not be empty", index);
        }
        if span.cache_ref.trim().is_empty() {
            bail!(
                "agent_graph.kv_spans[{}].cache_ref must not be empty",
                index
            );
        }
        if span.token_end <= span.token_start {
            bail!(
                "agent_graph.kv_spans[{}].token_end must be greater than token_start",
                index
            );
        }
        if span.token_end > header.seq_len {
            bail!(
                "agent_graph.kv_spans[{}] exceeds target context window {}",
                index,
                header.seq_len
            );
        }
        validate_optional_sha256(
            &format!("agent_graph.kv_spans[{}].tokenizer_hash", index),
            span.tokenizer_hash.as_ref(),
        )?;
        if let (Some(span_tokenizer), Some(binding_tokenizer)) = (
            span.tokenizer_hash.as_ref(),
            binding.tokenizer_hash.as_ref(),
        ) {
            if span_tokenizer != binding_tokenizer {
                bail!(
                    "agent_graph.kv_spans[{}].tokenizer_hash does not match binding tokenizer_hash",
                    index
                );
            }
        }
        if span.block_hashes.is_empty() {
            bail!(
                "agent_graph.kv_spans[{}].block_hashes must not be empty",
                index
            );
        }
        for block_hash in &span.block_hashes {
            ensure_sha256_field(
                &format!("agent_graph.kv_spans[{}].block_hashes", index),
                block_hash,
            )?;
            if !migrated_blocks.contains(block_hash.as_str()) {
                bail!(
                    "agent_graph.kv_spans[{}].block_hashes contains a block not present in the migrated KV header",
                    index
                );
            }
        }
    }

    for (index, artifact) in binding.artifacts.iter().enumerate() {
        if artifact.path.trim().is_empty() {
            bail!("agent_graph.artifacts[{}].path must not be empty", index);
        }
        ensure_sha256_field(
            &format!("agent_graph.artifacts[{}].sha256", index),
            &artifact.sha256,
        )?;
    }

    Ok(())
}

fn configured_model_architecture() -> String {
    std::env::var("PERMEANT_MODEL_ARCHITECTURE")
        .or_else(|_| std::env::var("PERMEANT_MLX_MODEL_ID"))
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "live-runtime-unknown".to_string())
}

fn configured_model_identity() -> String {
    std::env::var("PERMEANT_MODEL_IDENTITY")
        .or_else(|_| std::env::var("PERMEANT_MLX_MODEL_ID"))
        .or_else(|_| std::env::var("PERMEANT_MODEL_ARCHITECTURE"))
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "live-runtime-unknown".to_string())
}

fn configured_model_config_hash(model_architecture: &str, model_identity: &str) -> String {
    std::env::var("PERMEANT_MODEL_CONFIG_HASH")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            compute_sha256(format!("{}|{}", model_architecture, model_identity).as_bytes())
        })
}

fn configured_extractor_id() -> String {
    std::env::var("PERMEANT_EXTRACTOR_ID")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "permeant-os-live-extractor".to_string())
}

fn configured_model_layer_count(model_architecture: &str, model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_LAYER_COUNT")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| {
            if model_architecture == "Qwen/Qwen2.5-0.5B-Instruct"
                || model_identity == "Qwen/Qwen2.5-0.5B-Instruct"
            {
                24
            } else {
                4
            }
        })
}

fn configured_model_q_heads(model_architecture: &str, model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_Q_HEADS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| {
            if model_architecture == "Qwen/Qwen2.5-0.5B-Instruct"
                || model_identity == "Qwen/Qwen2.5-0.5B-Instruct"
            {
                14
            } else {
                8
            }
        })
}

fn configured_model_kv_heads(_model_architecture: &str, _model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_KV_HEADS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(2)
}

fn configured_model_head_dim(_model_architecture: &str, _model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_HEAD_DIM")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(64)
}

fn configured_model_hidden_size(model_architecture: &str, model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_HIDDEN_SIZE")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| {
            if model_architecture == "Qwen/Qwen2.5-0.5B-Instruct"
                || model_identity == "Qwen/Qwen2.5-0.5B-Instruct"
            {
                896
            } else {
                1024
            }
        })
}

fn configured_model_block_size() -> usize {
    std::env::var("PERMEANT_MODEL_BLOCK_SIZE")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(256)
}

fn normalize_canonical_kv_tensor(tensor_name: &str, tensor: &Tensor) -> Result<Tensor> {
    match tensor.shape.as_slice() {
        [seq_len, num_kv_heads, head_dim] => Ok(Tensor::new(
            tensor.data.clone(),
            vec![*seq_len, *num_kv_heads, *head_dim],
        )),
        [1, num_kv_heads, seq_len, head_dim] => Ok(Tensor::new(
            tensor.data.clone(),
            vec![*seq_len, *num_kv_heads, *head_dim],
        )),
        _ => bail!(
            "Unsupported canonical KV tensor shape for {}: {:?}",
            tensor_name,
            tensor.shape
        ),
    }
}

fn block_float_count(header: &UsxfHeader, tensor_name: &str) -> usize {
    if tensor_name.ends_with(".key") {
        header.model_cache_spec.n_kv_heads * header.model_cache_spec.head_dim * header.block_size
    } else {
        header.model_cache_spec.n_kv_heads * header.block_size * header.model_cache_spec.head_dim
    }
}

fn encode_payload(data: &[f32], transfer_codec: TransferCodec) -> Vec<u8> {
    match transfer_codec {
        TransferCodec::None => {
            let mut bytes = Vec::with_capacity(data.len() * 4);
            for &f in data {
                bytes.extend_from_slice(&f.to_be_bytes());
            }
            bytes
        }
        TransferCodec::Fp8 => {
            let scale = compute_optimal_scale(data, 448.0);
            quantize_e4m3_scaled(data, scale)
        }
        TransferCodec::Qatq => quantize_qatq_i4(data),
    }
}

async fn run_sim_migrate(
    target_addr_str: &str,
    seq_len: usize,
    transfer_codec: TransferCodec,
    agent_graph_manifest_path: Option<&str>,
) -> Result<()> {
    let total_start = std::time::Instant::now();
    let run_id = format!(
        "migration-{}-{}",
        Utc::now().format("%Y%m%d-%H%M%S"),
        std::process::id()
    );
    let source_environment = collect_environment_snapshot();
    let model_architecture = configured_model_architecture();
    let model_identity = configured_model_identity();
    let model_config_hash = configured_model_config_hash(&model_architecture, &model_identity);
    let agent_graph_manifest = load_agent_graph_manifest(agent_graph_manifest_path)?;
    if let Some(agent_graph) = &agent_graph_manifest {
        println!(
            "Loaded Agent Memory Graph manifest: {}",
            agent_graph.graph_hash
        );
    }

    // 1. Model Configuration
    let n_layers = configured_model_layer_count(&model_architecture, &model_identity);
    let n_q_heads = configured_model_q_heads(&model_architecture, &model_identity);
    let n_kv_heads = configured_model_kv_heads(&model_architecture, &model_identity);
    let head_dim = configured_model_head_dim(&model_architecture, &model_identity);
    let hidden_size = configured_model_hidden_size(&model_architecture, &model_identity);
    let block_size = configured_model_block_size();

    println!("Step 1: Extracting local agent KV cache state...");
    let extracted_cache = extract_kv_cache(seq_len, n_layers, n_kv_heads, head_dim)?;
    println!(
        "Extracted cache: {} tensors (Layers 0-{} keys/values)",
        extracted_cache.len(),
        n_layers - 1
    );

    // Let's connect to target daemon
    println!("Connecting to target daemon at {}...", target_addr_str);
    let mut socket = TcpStream::connect(target_addr_str).await.context(
        "Failed to connect to migration daemon. Make sure to run 'daemon' subcommand first.",
    )?;

    // 2. Capability Exchange
    println!("Step 2: Performing Capability Exchange...");
    let handshake_start = std::time::Instant::now();
    send_message(
        &mut socket,
        &MigrationMessage::CapabilityRequest {
            model_architecture: model_architecture.clone(),
            attention_type: "gqa".to_string(),
            seq_len,
        },
    )
    .await?;

    let resp = recv_message(&mut socket).await?;
    let target_device_name = if let MigrationMessage::CapabilityResponse {
        accepted,
        error_message,
        target_device,
    } = resp
    {
        if !accepted {
            bail!(
                "Target daemon rejected migration capacity: {:?}",
                error_message
            );
        }
        println!(
            "Target accepted capability request. Device: {}",
            target_device
        );
        target_device
    } else {
        bail!("Unexpected handshake response");
    };
    let handshake_time = handshake_start.elapsed().as_secs_f64() * 1000.0;

    // 3. Build USXF Header
    println!("Step 3: Building USXF Header...");
    let header_start = std::time::Instant::now();
    let dummy_tokens = vec![42u32; seq_len];
    let block_hashes = compute_token_block_hashes(&dummy_tokens, block_size);
    let block_hash_count = block_hashes.len();

    // Compute a dummy checksum of the payload data
    let checksum =
        "sha256:0000000000000000000000000000000000000000000000000000000000000000".to_string();

    let transfer_quant = transfer_codec
        .header_scheme()
        .map(|scheme| usxf_core::QuantizationInfo {
            scheme: scheme.to_string(),
            group_size: None,
            scales: None,
        });

    let header = UsxfHeader {
        usxf_version: "1.1".to_string(),
        model_architecture: model_architecture.clone(),
        model_identity: ModelIdentity {
            config_hash: model_config_hash.clone(),
            weights_revision: model_identity.clone(),
        },
        attention_type: AttentionType::Gqa,
        model_cache_spec: ModelCacheSpec {
            n_layers,
            n_q_heads,
            n_kv_heads,
            head_dim,
            hidden_size,
            max_position_embeddings: Some(131072),
            rope_theta: Some(500000.0),
            sliding_window: None,
        },
        mla_spec: None,
        chat_state: None,
        token_ids: dummy_tokens,
        seq_len,
        batch_size: 1,
        dtype: ExchangeDtype::Float32,
        source_quantization: None,
        transfer_quantization: transfer_quant,
        block_size,
        block_hashes,
        position_ids: None,
        extra: HashMap::new(),
        created_at: Utc::now(),
        extractor_id: configured_extractor_id(),
        checksum,
        signature: "".to_string(), // will be updated/signed
    };

    // Sign and Encrypt Header
    let aes_key = [7u8; 32];
    // Generate temporary signing key
    let mut csprng = rand::rngs::OsRng;
    let signing_key = usxf_core::crypto::SigningKey::generate(&mut csprng);

    let serialized_header = serde_json::to_vec(&header)?;
    let envelope = seal_packet(&serialized_header, &aes_key, &signing_key)?;

    println!("Sending encrypted USXF header...");
    send_message(&mut socket, &MigrationMessage::HeaderEnvelope(envelope)).await?;

    let ack = recv_message(&mut socket).await?;
    if let MigrationMessage::HeaderAck { accepted } = ack {
        if !accepted {
            bail!("Target daemon rejected USXF header.");
        }
        println!("Target verified USXF header.");
    } else {
        bail!("Unexpected header response");
    }
    let header_time = header_start.elapsed().as_secs_f64() * 1000.0;

    // 4. Stream payload blocks
    println!("Step 4: Transpiling and streaming payload layers block-by-block...");
    let expected_blocks = seq_len.div_ceil(block_size);
    let mut total_transferred_bytes = 0u64;
    let mut chunks_sent = 0u64;
    let transfer_start = std::time::Instant::now();

    for layer_idx in 0..n_layers {
        let key_name = format!("layer.{}.key", layer_idx);
        let value_name = format!("layer.{}.value", layer_idx);
        let key_tensor =
            normalize_canonical_kv_tensor(&key_name, extracted_cache.get(&key_name).unwrap())?;
        let value_tensor =
            normalize_canonical_kv_tensor(&value_name, extracted_cache.get(&value_name).unwrap())?;

        // Transpile to vLLM blocks
        let vllm_key = canonical_to_vllm_block_key(&key_tensor, block_size)?;
        let vllm_value = canonical_to_vllm_block_value(&value_tensor, block_size)?;

        // Stream each block
        for block_idx in 0..expected_blocks {
            // Extract single block slice from vLLM key/value tensors
            // Key shape: [num_blocks, num_kv_heads, head_dim, block_size]
            // Value shape: [num_blocks, num_kv_heads, block_size, head_dim]
            let k_block_size = n_kv_heads * head_dim * block_size;
            let v_block_size = n_kv_heads * block_size * head_dim;

            let k_start = block_idx * k_block_size;
            let k_data = &vllm_key.data[k_start..(k_start + k_block_size)];

            let v_start = block_idx * v_block_size;
            let v_data = &vllm_value.data[v_start..(v_start + v_block_size)];

            // Format data payload (with optional quantization)
            let k_payload = encode_payload(k_data, transfer_codec);
            let v_payload = encode_payload(v_data, transfer_codec);

            total_transferred_bytes += (k_payload.len() + v_payload.len()) as u64;

            // Send Key chunk
            let crc32_k = compute_crc32(&k_payload);
            send_message(
                &mut socket,
                &MigrationMessage::PayloadChunk {
                    chunk_index: block_idx as u32,
                    layer_index: layer_idx as u32,
                    tensor_name: format!("layer.{}.key", layer_idx),
                    data: k_payload,
                    crc32: crc32_k,
                },
            )
            .await?;
            chunks_sent += 1;
            let _ack_k = recv_message(&mut socket).await?;

            // Send Value chunk
            let crc32_v = compute_crc32(&v_payload);
            send_message(
                &mut socket,
                &MigrationMessage::PayloadChunk {
                    chunk_index: block_idx as u32,
                    layer_index: layer_idx as u32,
                    tensor_name: format!("layer.{}.value", layer_idx),
                    data: v_payload,
                    crc32: crc32_v,
                },
            )
            .await?;
            chunks_sent += 1;
            let _ack_v = recv_message(&mut socket).await?;
        }
    }
    let transfer_time = transfer_start.elapsed().as_secs_f64() * 1000.0;

    let uncompressed_bytes = (n_layers * 2 * n_kv_heads * head_dim * seq_len * 4) as u64; // float32 = 4 bytes
    let compression_ratio = if uncompressed_bytes > 0 {
        total_transferred_bytes as f64 / uncompressed_bytes as f64
    } else {
        0.0
    };
    let average_chunk_bytes = if chunks_sent > 0 {
        total_transferred_bytes as f64 / chunks_sent as f64
    } else {
        0.0
    };

    let transfer_secs = transfer_time / 1000.0;
    let effective_bandwidth_gbps = if transfer_secs > 0.0 {
        (((total_transferred_bytes * 8) as f64) / transfer_secs) / 1_000_000_000.0
    } else {
        0.0
    };

    if let Some(agent_graph) = &agent_graph_manifest {
        println!("Step 5: Binding Agent Memory Graph package to staged KV transaction...");
        send_message(
            &mut socket,
            &MigrationMessage::AgentGraphBinding(agent_graph.to_binding(&header)),
        )
        .await?;
        let binding_resp = recv_message(&mut socket).await?;
        match binding_resp {
            MigrationMessage::AgentGraphBindingAck { accepted: true, .. } => {
                println!("Target accepted Agent Memory Graph binding.");
            }
            MigrationMessage::AgentGraphBindingAck {
                accepted: false,
                error_message,
            } => {
                let error_text = format!("{:?}", error_message);
                let total_time = total_start.elapsed().as_secs_f64() * 1000.0;
                let manifest = MigrationManifest {
                    manifest_version: "1.0".to_string(),
                    run_id,
                    timestamp: Utc::now().to_rfc3339(),
                    source_environment,
                    target_addr: target_addr_str.to_string(),
                    target_device: target_device_name,
                    model_architecture: model_architecture.clone(),
                    model_identity: model_identity.clone(),
                    usxf_version: "1.1".to_string(),
                    attention_type: "gqa".to_string(),
                    sequence_length: seq_len,
                    batch_size: 1,
                    layers: n_layers,
                    n_q_heads,
                    n_kv_heads,
                    head_dim,
                    block_size,
                    expected_blocks,
                    block_hash_count,
                    dtype: "float32".to_string(),
                    source_quantization: "none".to_string(),
                    transfer_quantization: transfer_codec.manifest_value().to_string(),
                    uncompressed_bytes,
                    transferred_bytes: total_transferred_bytes,
                    compression_ratio,
                    chunks_sent,
                    average_chunk_bytes,
                    handshake_time_ms: handshake_time,
                    header_time_ms: header_time,
                    transfer_time_ms: transfer_time,
                    commit_time_ms: 0.0,
                    total_time_ms: total_time,
                    effective_bandwidth_gbps,
                    phase_status: "graph_binding_failed".to_string(),
                    success: false,
                    error_message: Some(error_text.clone()),
                    agent_graph: agent_graph_manifest,
                };
                let filename = write_migration_manifest(&manifest)?;
                println!("Saved failed migration benchmark manifest: {}", filename);
                bail!(
                    "Target daemon rejected Agent Memory Graph binding: {}",
                    error_text
                );
            }
            _ => bail!("Unexpected Agent Memory Graph binding response"),
        }
    } else {
        println!("Step 5: No Agent Memory Graph package supplied; continuing KV-only commit.");
    }

    // 6. Commitment Phase
    println!("Step 6: Invoking Two-Phase Commit...");
    let commit_start = std::time::Instant::now();
    send_message(&mut socket, &MigrationMessage::CommitRequest).await?;

    let commit_resp = recv_message(&mut socket).await?;
    let commit_time = commit_start.elapsed().as_secs_f64() * 1000.0;

    let total_time = total_start.elapsed().as_secs_f64() * 1000.0;
    if let MigrationMessage::CommitResponse {
        success,
        error_message,
    } = commit_resp
    {
        if success {
            println!("\nMigration completed successfully! All layers injected and verified.");

            let manifest = MigrationManifest {
                manifest_version: "1.0".to_string(),
                run_id,
                timestamp: Utc::now().to_rfc3339(),
                source_environment,
                target_addr: target_addr_str.to_string(),
                target_device: target_device_name,
                model_architecture: model_architecture.clone(),
                model_identity: model_identity.clone(),
                usxf_version: "1.1".to_string(),
                attention_type: "gqa".to_string(),
                sequence_length: seq_len,
                batch_size: 1,
                layers: n_layers,
                n_q_heads,
                n_kv_heads,
                head_dim,
                block_size,
                expected_blocks,
                block_hash_count,
                dtype: "float32".to_string(),
                source_quantization: "none".to_string(),
                transfer_quantization: transfer_codec.manifest_value().to_string(),
                uncompressed_bytes,
                transferred_bytes: total_transferred_bytes,
                compression_ratio,
                chunks_sent,
                average_chunk_bytes,
                handshake_time_ms: handshake_time,
                header_time_ms: header_time,
                transfer_time_ms: transfer_time,
                commit_time_ms: commit_time,
                total_time_ms: total_time,
                effective_bandwidth_gbps,
                phase_status: "committed".to_string(),
                success: true,
                error_message: None,
                agent_graph: agent_graph_manifest.clone(),
            };

            let filename = write_migration_manifest(&manifest)?;
            println!("Saved migration benchmark manifest: {}", filename);
        } else {
            let error_text = format!("{:?}", error_message);
            let manifest = MigrationManifest {
                manifest_version: "1.0".to_string(),
                run_id,
                timestamp: Utc::now().to_rfc3339(),
                source_environment,
                target_addr: target_addr_str.to_string(),
                target_device: target_device_name,
                model_architecture: model_architecture.clone(),
                model_identity: model_identity.clone(),
                usxf_version: "1.1".to_string(),
                attention_type: "gqa".to_string(),
                sequence_length: seq_len,
                batch_size: 1,
                layers: n_layers,
                n_q_heads,
                n_kv_heads,
                head_dim,
                block_size,
                expected_blocks,
                block_hash_count,
                dtype: "float32".to_string(),
                source_quantization: "none".to_string(),
                transfer_quantization: transfer_codec.manifest_value().to_string(),
                uncompressed_bytes,
                transferred_bytes: total_transferred_bytes,
                compression_ratio,
                chunks_sent,
                average_chunk_bytes,
                handshake_time_ms: handshake_time,
                header_time_ms: header_time,
                transfer_time_ms: transfer_time,
                commit_time_ms: commit_time,
                total_time_ms: total_time,
                effective_bandwidth_gbps,
                phase_status: "commit_failed".to_string(),
                success: false,
                error_message: Some(error_text.clone()),
                agent_graph: agent_graph_manifest,
            };
            let filename = write_migration_manifest(&manifest)?;
            println!("Saved failed migration benchmark manifest: {}", filename);
            bail!("Target daemon failed to commit: {:?}", error_message);
        }
    } else {
        bail!("Unexpected commit response");
    }

    Ok(())
}

fn run_inspect(file_path: &str) -> Result<()> {
    println!("Inspecting USXF packet at: {}", file_path);
    let bytes = std::fs::read(file_path).context("Failed to read file")?;
    let header: UsxfHeader =
        serde_json::from_slice(&bytes).context("Failed to parse USXF metadata")?;

    println!("\nUSXF Metadata Inspection:");
    println!("--------------------------");
    println!("USXF Version:      {}", header.usxf_version);
    println!("Model Architecture:{}", header.model_architecture);
    println!("Attention Type:    {:?}", header.attention_type);
    println!("Sequence Length:   {} tokens", header.seq_len);
    println!("Block Size:        {} tokens", header.block_size);
    println!("Number of Blocks:  {}", header.block_hashes.len());
    println!("Cache Precision:   {:?}", header.dtype);
    println!("Layers:            {}", header.model_cache_spec.n_layers);
    println!("KV Heads:          {}", header.model_cache_spec.n_kv_heads);
    println!("Head Dim:          {}", header.model_cache_spec.head_dim);
    println!("Created At:        {}", header.created_at);
    println!("Checksum:          {}", header.checksum);
    println!("Signature:         {}", header.signature);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn temp_manifest_path(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "permeant-cli-{}-{}-{}.json",
            name,
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap_or_default()
        ))
    }

    fn test_header(block_hashes: Vec<String>, seq_len: usize) -> UsxfHeader {
        UsxfHeader {
            usxf_version: "1.1".to_string(),
            model_architecture: "test-model".to_string(),
            model_identity: ModelIdentity {
                config_hash:
                    "sha256:1111111111111111111111111111111111111111111111111111111111111111"
                        .to_string(),
                weights_revision: "test".to_string(),
            },
            attention_type: AttentionType::Gqa,
            model_cache_spec: ModelCacheSpec {
                n_layers: 1,
                n_q_heads: 2,
                n_kv_heads: 1,
                head_dim: 4,
                hidden_size: 8,
                max_position_embeddings: Some(128),
                rope_theta: Some(10000.0),
                sliding_window: None,
            },
            mla_spec: None,
            chat_state: None,
            token_ids: vec![42; seq_len],
            seq_len,
            batch_size: 1,
            dtype: ExchangeDtype::Float32,
            source_quantization: None,
            transfer_quantization: None,
            block_size: seq_len,
            block_hashes,
            position_ids: None,
            extra: HashMap::new(),
            created_at: Utc::now(),
            extractor_id: "test-extractor".to_string(),
            checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
                .to_string(),
            signature: "".to_string(),
        }
    }

    fn test_graph_binding(block_hash: &str) -> AgentGraphBinding {
        AgentGraphBinding {
            manifest_path: "manifest.json".to_string(),
            graph_path: "graph.json".to_string(),
            graph_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_string(),
            prompt_byte_hash: Some(
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    .to_string(),
            ),
            prompt_token_hash: Some(
                "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                    .to_string(),
            ),
            tokenizer_hash: Some(
                "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                    .to_string(),
            ),
            kv_hash: Some(
                "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                    .to_string(),
            ),
            kv_spans: vec![AgentGraphBindingKvSpan {
                node_id: "checkpoint:prompt".to_string(),
                token_start: 0,
                token_end: 8,
                cache_ref: "kv:prefix:0".to_string(),
                tokenizer_hash: Some(
                    "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                        .to_string(),
                ),
                block_hashes: vec![block_hash.to_string()],
            }],
            artifacts: vec![AgentGraphBindingArtifact {
                path: "reports/result.json".to_string(),
                sha256: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                    .to_string(),
                size_bytes: Some(42),
            }],
        }
    }

    fn test_agent_graph_manifest(original_block_hash: &str) -> AgentGraphManifest {
        AgentGraphManifest {
            manifest_path: "manifest.json".to_string(),
            graph_path: "graph.json".to_string(),
            graph_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_string(),
            prompt_byte_hash: Some(
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    .to_string(),
            ),
            prompt_token_hash: Some(
                "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                    .to_string(),
            ),
            tokenizer_hash: Some(
                "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                    .to_string(),
            ),
            kv_hash: Some(
                "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                    .to_string(),
            ),
            kv_spans: vec![AgentGraphKvSpan {
                node_id: "checkpoint:prompt".to_string(),
                token_start: 0,
                token_end: 8,
                cache_ref: "kv:prefix:0".to_string(),
                tokenizer_hash: Some(
                    "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                        .to_string(),
                ),
                block_hashes: vec![original_block_hash.to_string()],
            }],
            artifacts: vec![],
        }
    }

    #[test]
    fn validates_payload_chunk_metadata() {
        let block_hash = "sha256:9999999999999999999999999999999999999999999999999999999999999999";
        let header = test_header(vec![block_hash.to_string()], 8);
        let mut received_chunks = HashSet::new();

        let validated_hash =
            validate_payload_chunk_metadata(&header, 0, 0, "layer.0.key", &mut received_chunks)
                .unwrap();

        assert_eq!(validated_hash, block_hash);
    }

    #[test]
    fn rejects_payload_chunk_with_out_of_range_block_index() {
        let header = test_header(
            vec![
                "sha256:9999999999999999999999999999999999999999999999999999999999999999"
                    .to_string(),
            ],
            8,
        );
        let mut received_chunks = HashSet::new();

        let error =
            validate_payload_chunk_metadata(&header, 1, 0, "layer.0.key", &mut received_chunks)
                .expect_err("out-of-range chunk index should fail");

        assert!(error.to_string().contains("exceeds advertised block count"));
    }

    #[test]
    fn rejects_payload_chunk_with_mismatched_tensor_name() {
        let header = test_header(
            vec![
                "sha256:9999999999999999999999999999999999999999999999999999999999999999"
                    .to_string(),
            ],
            8,
        );
        let mut received_chunks = HashSet::new();

        let error =
            validate_payload_chunk_metadata(&header, 0, 0, "layer.1.key", &mut received_chunks)
                .expect_err("mismatched tensor name should fail");

        assert!(error.to_string().contains("does not match layer"));
    }

    #[test]
    fn rejects_payload_chunk_with_out_of_range_layer_index() {
        let header = test_header(
            vec![
                "sha256:9999999999999999999999999999999999999999999999999999999999999999"
                    .to_string(),
            ],
            8,
        );
        let mut received_chunks = HashSet::new();

        let error =
            validate_payload_chunk_metadata(&header, 0, 1, "layer.1.key", &mut received_chunks)
                .expect_err("out-of-range layer index should fail");

        assert!(error.to_string().contains("exceeds advertised layer count"));
    }

    #[test]
    fn rejects_duplicate_payload_chunk_metadata() {
        let header = test_header(
            vec![
                "sha256:9999999999999999999999999999999999999999999999999999999999999999"
                    .to_string(),
            ],
            8,
        );
        let mut received_chunks = HashSet::new();

        validate_payload_chunk_metadata(&header, 0, 0, "layer.0.key", &mut received_chunks)
            .unwrap();
        let error =
            validate_payload_chunk_metadata(&header, 0, 0, "layer.0.key", &mut received_chunks)
                .expect_err("duplicate chunk should fail");

        assert!(error.to_string().contains("Duplicate payload chunk"));
    }

    #[test]
    fn loads_agent_graph_manifest_hash_fields() {
        let path = temp_manifest_path("agent-graph-manifest");
        fs::write(
            &path,
            r#"{
  "manifest_version": "0.1",
  "graph_path": "graph.json",
  "graph_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "prompt": {
    "byte_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "token_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "tokenizer_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "kv": {
    "kv_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  },
  "kv_spans": [
    {
      "node_id": "checkpoint:prompt",
      "token_start": 0,
      "token_end": 8,
      "cache_ref": "kv:simulated:prompt",
      "tokenizer_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "block_hashes": [
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      ]
    }
  ],
  "artifacts": [
    {
      "path": "reports/result.json",
      "sha256": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      "size_bytes": 42
    }
  ]
}"#,
        )
        .unwrap();

        let loaded = load_agent_graph_manifest(Some(path.to_str().unwrap()))
            .unwrap()
            .unwrap();
        assert_eq!(
            loaded.graph_hash,
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
        assert_eq!(loaded.graph_path, "graph.json");
        assert_eq!(
            loaded.prompt_token_hash.as_deref(),
            Some("sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")
        );
        assert_eq!(
            loaded.kv_hash.as_deref(),
            Some("sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
        );
        assert_eq!(loaded.artifacts.len(), 1);
        assert_eq!(loaded.artifacts[0].path, "reports/result.json");
        assert_eq!(loaded.kv_spans.len(), 1);
        assert_eq!(loaded.kv_spans[0].node_id, "checkpoint:prompt");
        assert_eq!(loaded.kv_spans[0].token_start, 0);
        assert_eq!(loaded.kv_spans[0].token_end, 8);
        assert_eq!(loaded.kv_spans[0].cache_ref, "kv:simulated:prompt");

        let _ = fs::remove_file(path);
    }

    #[test]
    fn rejects_invalid_agent_graph_hash() {
        let path = temp_manifest_path("bad-agent-graph-manifest");
        fs::write(
            &path,
            r#"{
  "graph_path": "graph.json",
  "graph_hash": "not-a-sha256"
}"#,
        )
        .unwrap();

        let error = load_agent_graph_manifest(Some(path.to_str().unwrap()))
            .expect_err("invalid graph hash should fail");
        assert!(error.to_string().contains("agent_graph.graph_hash"));

        let _ = fs::remove_file(path);
    }

    #[test]
    fn rejects_invalid_agent_graph_kv_span() {
        let path = temp_manifest_path("bad-agent-graph-kv-span");
        fs::write(
            &path,
            r#"{
  "graph_path": "graph.json",
  "graph_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "kv_spans": [
    {
      "node_id": "checkpoint:prompt",
      "token_start": 12,
      "token_end": 8,
      "cache_ref": "kv:simulated:prompt"
    }
  ]
}"#,
        )
        .unwrap();

        let error = load_agent_graph_manifest(Some(path.to_str().unwrap()))
            .expect_err("invalid KV span range should fail");
        assert!(error
            .to_string()
            .contains("agent_graph.kv_spans[0].token_end"));

        let _ = fs::remove_file(path);
    }

    #[test]
    fn validates_agent_graph_binding_against_migrated_header() {
        let block_hash = "sha256:9999999999999999999999999999999999999999999999999999999999999999";
        let header = test_header(vec![block_hash.to_string()], 8);
        let binding = test_graph_binding(block_hash);

        validate_agent_graph_binding(&binding, &header).unwrap();
    }

    #[test]
    fn graph_binding_uses_migrated_header_block_hashes_for_spans() {
        let header_block_hash =
            "sha256:9999999999999999999999999999999999999999999999999999999999999999";
        let simulated_manifest_block_hash =
            "sha256:7777777777777777777777777777777777777777777777777777777777777777";
        let header = test_header(vec![header_block_hash.to_string()], 8);
        let manifest = test_agent_graph_manifest(simulated_manifest_block_hash);
        let binding = manifest.to_binding(&header);

        assert_eq!(
            binding.kv_spans[0].block_hashes,
            vec![header_block_hash.to_string()]
        );
        validate_agent_graph_binding(&binding, &header).unwrap();
    }

    #[test]
    fn rejects_agent_graph_binding_with_unmigrated_block_hash() {
        let header = test_header(
            vec![
                "sha256:9999999999999999999999999999999999999999999999999999999999999999"
                    .to_string(),
            ],
            8,
        );
        let binding = test_graph_binding(
            "sha256:8888888888888888888888888888888888888888888888888888888888888888",
        );

        let error = validate_agent_graph_binding(&binding, &header)
            .expect_err("binding with an unmigrated block hash should fail");
        assert!(error
            .to_string()
            .contains("not present in the migrated KV header"));
    }

    #[test]
    fn rejects_agent_graph_binding_without_required_kv_evidence() {
        let block_hash = "sha256:9999999999999999999999999999999999999999999999999999999999999999";
        let header = test_header(vec![block_hash.to_string()], 8);
        let mut binding = test_graph_binding(block_hash);
        binding.kv_hash = None;

        let error = validate_agent_graph_binding(&binding, &header)
            .expect_err("binding without a KV hash should fail");
        assert!(error.to_string().contains("must include kv_hash"));
    }
}
