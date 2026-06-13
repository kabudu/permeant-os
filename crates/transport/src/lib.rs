use serde::{Deserialize, Serialize};
use anyhow::{Result, Context, bail};
use tokio::net::{TcpListener, TcpStream};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use usxf_core::crypto::EncryptedEnvelope;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MigrationMessage {
    CapabilityRequest {
        model_architecture: String,
        attention_type: String,
        seq_len: usize,
    },
    CapabilityResponse {
        accepted: bool,
        error_message: Option<String>,
        target_device: String,
    },
    HeaderEnvelope(EncryptedEnvelope),
    HeaderAck {
        accepted: bool,
    },
    PayloadChunk {
        chunk_index: u32,
        layer_index: u32,
        tensor_name: String,
        data: Vec<u8>,
        crc32: u32,
    },
    ChunkAck {
        chunk_index: u32,
    },
    CommitRequest,
    CommitResponse {
        success: bool,
        error_message: Option<String>,
    },
}

/// Helper to send a frame-length prefixed JSON-serialized message over a TcpStream.
pub async fn send_message(stream: &mut TcpStream, msg: &MigrationMessage) -> Result<()> {
    let serialized = serde_json::to_vec(msg).context("Serialization failed")?;
    let len = serialized.len() as u32;
    stream.write_all(&len.to_be_bytes()).await.context("Failed to write frame length")?;
    stream.write_all(&serialized).await.context("Failed to write frame content")?;
    stream.flush().await.context("Failed to flush stream")?;
    Ok(())
}

/// Helper to read a frame-length prefixed JSON-serialized message from a TcpStream.
pub async fn recv_message(stream: &mut TcpStream) -> Result<MigrationMessage> {
    let mut len_bytes = [0u8; 4];
    stream.read_exact(&mut len_bytes).await.context("Failed to read frame length")?;
    let len = u32::from_be_bytes(len_bytes) as usize;
    
    // Safety check for massive messages
    if len > 500 * 1024 * 1024 {
        bail!("Frame size too large: {} bytes", len);
    }
    
    let mut buffer = vec![0u8; len];
    stream.read_exact(&mut buffer).await.context("Failed to read frame content")?;
    
    let msg: MigrationMessage = serde_json::from_slice(&buffer).context("Deserialization failed")?;
    Ok(msg)
}

/// Verifies if a payload chunk has the matching CRC32 checksum.
pub fn verify_chunk_crc32(chunk: &MigrationMessage) -> Result<bool> {
    if let MigrationMessage::PayloadChunk { data, crc32, .. } = chunk {
        let mut hasher = crc32fast::Hasher::new();
        hasher.update(data);
        let computed = hasher.finalize();
        Ok(computed == *crc32)
    } else {
        bail!("Message is not a payload chunk");
    }
}

/// Computes CRC32 checksum of data.
pub fn compute_crc32(data: &[u8]) -> u32 {
    let mut hasher = crc32fast::Hasher::new();
    hasher.update(data);
    hasher.finalize()
}
