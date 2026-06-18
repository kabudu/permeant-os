use clap::{Parser, Subcommand};
use anyhow::{Result, Context, bail};
use std::collections::HashMap;
use std::net::SocketAddr;
use tokio::net::{TcpListener, TcpStream};
use chrono::Utc;

use usxf_core::{UsxfHeader, ModelIdentity, ModelCacheSpec, AttentionType, ExchangeDtype, seal_packet, open_packet, validate_header, compute_token_block_hashes, compute_sha256};
use permeant_transpiler::{Tensor, canonical_to_vllm_block_key, canonical_to_vllm_block_value, quantize_e4m3_scaled, dequantize_e4m3_scaled, compute_optimal_scale};
use permeant_transport::{MigrationMessage, send_message, recv_message, compute_crc32, verify_chunk_crc32};
use permeant_orchestrator::{MigrationOrchestrator, ResourcePolicy, MigrationState};
use permeant_extractor::extract_kv_cache;
use permeant_injector::KVConnectorBase_V1;

#[derive(Parser, Debug)]
#[command(name = "permeantos-cli")]
#[command(about = "PermeantOS State-Fluid Hypervisor Control CLI", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
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
        Commands::SimMigrate { target_addr, seq_len, quant } => {
            println!("Starting end-to-end migration simulation to {} (Context: {} tokens, FP8 Quantization: {})...", target_addr, seq_len, quant);
            run_sim_migrate(&target_addr, seq_len, quant).await?;
        }
        Commands::Inspect { file } => {
            run_inspect(&file)?;
        }
    }
    
    Ok(())
}

async fn run_daemon(addr_str: &str) -> Result<()> {
    let addr: SocketAddr = addr_str.parse().context("Invalid socket address")?;
    let listener = TcpListener::bind(addr).await.context("Failed to bind socket")?;
    
    let mut orchestrator = MigrationOrchestrator::new(ResourcePolicy::default());
    let mut injector = KVConnectorBase_V1::new(256); // 256 token block size
    
    // Hardcoded keys for simulation purposes
    let aes_key = [7u8; 32];
    
    println!("Daemon listening for migration requests. Press Ctrl+C to stop.");
    
    loop {
        let (mut socket, peer) = listener.accept().await?;
        println!("\n[Daemon] Incoming connection from {:?}", peer);
        if let Err(err) = handle_migration_connection(
            &mut socket,
            &mut orchestrator,
            &mut injector,
            &aes_key,
        )
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
    if let MigrationMessage::CapabilityRequest { model_architecture, attention_type, seq_len } = msg {
        println!("[Daemon] Received migration capability request for: {}, Attn: {}, SeqLen: {}", model_architecture, attention_type, seq_len);
        
        let target_device = describe_runtime_target_device();
        let response = if seq_len > 131072 {
            MigrationMessage::CapabilityResponse {
                accepted: false,
                error_message: Some("Context size exceeds hypervisor hardware memory limits".to_string()),
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
        if let MigrationMessage::CapabilityResponse { accepted: false, .. } = response {
            println!("[Daemon] Rejected migration capability (context too large)");
            return Ok(());
        }
    } else {
        bail!("Protocol violation: Expected CapabilityRequest");
    }
    
    let msg = recv_message(socket).await?;
    let header = if let MigrationMessage::HeaderEnvelope(envelope) = msg {
        println!("[Daemon] Received encrypted USXF header envelope. Verifying signature & decrypting...");
        let plaintext = open_packet(&envelope, aes_key).context("Header decryption or signature failed")?;
        let header: UsxfHeader = serde_json::from_slice(&plaintext).context("Failed to deserialize USXF header")?;
        
        validate_header(&header).context("USXF metadata validation failed")?;
        println!("[Daemon] Header verified. Model Identity: {}. Config Hash: {}", header.model_architecture, header.model_identity.config_hash);
        
        send_message(socket, &MigrationMessage::HeaderAck { accepted: true }).await?;
        header
    } else {
        bail!("Protocol violation: Expected HeaderEnvelope");
    };
    
    println!("[Daemon] Streaming payload chunks starting...");
    let expected_blocks = (header.seq_len + header.block_size - 1) / header.block_size;
    let mut accumulated_blocks: HashMap<String, HashMap<String, Tensor>> = HashMap::new();
    
    for _ in 0..(header.model_cache_spec.n_layers * 2 * expected_blocks) {
        let chunk_msg = recv_message(socket).await?;
        if !verify_chunk_crc32(&chunk_msg)? {
            bail!("Payload chunk CRC32 checksum mismatch!");
        }
        
        if let MigrationMessage::PayloadChunk { chunk_index, layer_index: _, tensor_name, data, .. } = chunk_msg {
            let block_hash = header.block_hashes[chunk_index as usize].clone();
            let decrypted_data = if let Some(_quant) = &header.transfer_quantization {
                dequantize_e4m3_scaled(&data, 0.1)
            } else {
                let mut floats = vec![0.0f32; data.len() / 4];
                for (i, chunk) in data.chunks_exact(4).enumerate() {
                    let bytes: [u8; 4] = chunk.try_into()?;
                    floats[i] = f32::from_be_bytes(bytes);
                }
                floats
            };
            
            let shape = if tensor_name.ends_with(".key") {
                vec![1, header.model_cache_spec.n_kv_heads, header.model_cache_spec.head_dim, header.block_size]
            } else {
                vec![1, header.model_cache_spec.n_kv_heads, header.block_size, header.model_cache_spec.head_dim]
            };
            
            let block_tensor = Tensor::new(decrypted_data, shape);
            accumulated_blocks
                .entry(block_hash.clone())
                .or_insert_with(HashMap::new)
                .insert(tensor_name, block_tensor);
            send_message(socket, &MigrationMessage::ChunkAck { chunk_index }).await?;
        } else {
            bail!("Protocol violation: Expected PayloadChunk");
        }
    }
    
    println!("[Daemon] All layers and blocks streamed. Injecting into KVConnectorBase_V1...");
    for (hash, tensors) in accumulated_blocks {
        injector.inject_block_tensors(hash, tensors)?;
    }
    
    let msg = recv_message(socket).await?;
    if let MigrationMessage::CommitRequest = msg {
        println!("[Daemon] Commit requested. Running numerical continuation validation...");
        injector.verify_continuation(&header.block_hashes)?;
        
        println!("[Daemon] Validation passed. Committing migration state.");
        send_message(socket, &MigrationMessage::CommitResponse { success: true, error_message: None }).await?;
        orchestrator.record_success();
        println!("[Daemon] Migration COMMITTED successfully!");
        Ok(())
    } else {
        bail!("Protocol violation: Expected CommitRequest");
    }
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
        .unwrap_or_else(|| compute_sha256(format!("{}|{}", model_architecture, model_identity).as_bytes()))
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

fn configured_model_kv_heads(model_architecture: &str, model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_KV_HEADS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| {
            if model_architecture == "Qwen/Qwen2.5-0.5B-Instruct"
                || model_identity == "Qwen/Qwen2.5-0.5B-Instruct"
            {
                2
            } else {
                2
            }
        })
}

fn configured_model_head_dim(model_architecture: &str, model_identity: &str) -> usize {
    std::env::var("PERMEANT_MODEL_HEAD_DIM")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_else(|| {
            if model_architecture == "Qwen/Qwen2.5-0.5B-Instruct"
                || model_identity == "Qwen/Qwen2.5-0.5B-Instruct"
            {
                64
            } else {
                64
            }
        })
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

async fn run_sim_migrate(target_addr_str: &str, seq_len: usize, quantize: bool) -> Result<()> {
    let total_start = std::time::Instant::now();
    let run_id = format!("migration-{}-{}", Utc::now().format("%Y%m%d-%H%M%S"), std::process::id());
    let source_environment = collect_environment_snapshot();
    let model_architecture = configured_model_architecture();
    let model_identity = configured_model_identity();
    let model_config_hash = configured_model_config_hash(&model_architecture, &model_identity);

    // 1. Model Configuration
    let n_layers = configured_model_layer_count(&model_architecture, &model_identity);
    let n_q_heads = configured_model_q_heads(&model_architecture, &model_identity);
    let n_kv_heads = configured_model_kv_heads(&model_architecture, &model_identity);
    let head_dim = configured_model_head_dim(&model_architecture, &model_identity);
    let hidden_size = configured_model_hidden_size(&model_architecture, &model_identity);
    let block_size = configured_model_block_size();
    
    println!("Step 1: Extracting local agent KV cache state...");
    let extracted_cache = extract_kv_cache(seq_len, n_layers, n_kv_heads, head_dim)?;
    println!("Extracted cache: {} tensors (Layers 0-{} keys/values)", extracted_cache.len(), n_layers - 1);
    
    // Let's connect to target daemon
    println!("Connecting to target daemon at {}...", target_addr_str);
    let mut socket = TcpStream::connect(target_addr_str).await.context("Failed to connect to migration daemon. Make sure to run 'daemon' subcommand first.")?;
    
    // 2. Capability Exchange
    println!("Step 2: Performing Capability Exchange...");
    let handshake_start = std::time::Instant::now();
    send_message(&mut socket, &MigrationMessage::CapabilityRequest {
        model_architecture: model_architecture.clone(),
        attention_type: "gqa".to_string(),
        seq_len,
    }).await?;
    
    let resp = recv_message(&mut socket).await?;
    let target_device_name = if let MigrationMessage::CapabilityResponse { accepted, error_message, target_device } = resp {
        if !accepted {
            bail!("Target daemon rejected migration capacity: {:?}", error_message);
        }
        println!("Target accepted capability request. Device: {}", target_device);
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
    let checksum = "sha256:0000000000000000000000000000000000000000000000000000000000000000".to_string();
    
    let transfer_quant = if quantize {
        Some(usxf_core::QuantizationInfo {
            scheme: "fp8".to_string(),
            group_size: None,
            scales: None,
        })
    } else {
        None
    };
    
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
    let expected_blocks = (seq_len + block_size - 1) / block_size;
    let mut total_transferred_bytes = 0u64;
    let mut chunks_sent = 0u64;
    let transfer_start = std::time::Instant::now();
    
    for layer_idx in 0..n_layers {
        let key_name = format!("layer.{}.key", layer_idx);
        let value_name = format!("layer.{}.value", layer_idx);
        let key_tensor = normalize_canonical_kv_tensor(&key_name, extracted_cache.get(&key_name).unwrap())?;
        let value_tensor = normalize_canonical_kv_tensor(&value_name, extracted_cache.get(&value_name).unwrap())?;
        
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
            let (k_payload, v_payload) = if quantize {
                // Quantize to FP8 (simulate compression)
                let scale = compute_optimal_scale(k_data, 448.0);
                let k_quant = quantize_e4m3_scaled(k_data, scale);
                
                let scale_v = compute_optimal_scale(v_data, 448.0);
                let v_quant = quantize_e4m3_scaled(v_data, scale_v);
                
                (k_quant, v_quant)
            } else {
                // Raw f32 bytes
                let mut k_bytes = Vec::with_capacity(k_data.len() * 4);
                for &f in k_data {
                    k_bytes.extend_from_slice(&f.to_be_bytes());
                }
                let mut v_bytes = Vec::with_capacity(v_data.len() * 4);
                for &f in v_data {
                    v_bytes.extend_from_slice(&f.to_be_bytes());
                }
                (k_bytes, v_bytes)
            };
            
            total_transferred_bytes += (k_payload.len() + v_payload.len()) as u64;
            
            // Send Key chunk
            let crc32_k = compute_crc32(&k_payload);
            send_message(&mut socket, &MigrationMessage::PayloadChunk {
                chunk_index: block_idx as u32,
                layer_index: layer_idx as u32,
                tensor_name: format!("layer.{}.key", layer_idx),
                data: k_payload,
                crc32: crc32_k,
            }).await?;
            chunks_sent += 1;
            let _ack_k = recv_message(&mut socket).await?;
            
            // Send Value chunk
            let crc32_v = compute_crc32(&v_payload);
            send_message(&mut socket, &MigrationMessage::PayloadChunk {
                chunk_index: block_idx as u32,
                layer_index: layer_idx as u32,
                tensor_name: format!("layer.{}.value", layer_idx),
                data: v_payload,
                crc32: crc32_v,
            }).await?;
            chunks_sent += 1;
            let _ack_v = recv_message(&mut socket).await?;
        }
    }
    let transfer_time = transfer_start.elapsed().as_secs_f64() * 1000.0;
    
    // 5. Commitment Phase
    println!("Step 5: Invoking Two-Phase Commit...");
    let commit_start = std::time::Instant::now();
    send_message(&mut socket, &MigrationMessage::CommitRequest).await?;
    
    let commit_resp = recv_message(&mut socket).await?;
    let commit_time = commit_start.elapsed().as_secs_f64() * 1000.0;
    
    let total_time = total_start.elapsed().as_secs_f64() * 1000.0;
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

    if let MigrationMessage::CommitResponse { success, error_message } = commit_resp {
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
                transfer_quantization: if quantize { "fp8".to_string() } else { "none".to_string() },
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
                transfer_quantization: if quantize { "fp8".to_string() } else { "none".to_string() },
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
    let header: UsxfHeader = serde_json::from_slice(&bytes).context("Failed to parse USXF metadata")?;
    
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
