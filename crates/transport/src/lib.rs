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

const FRAME_KIND_JSON: u8 = 0;
const FRAME_KIND_PAYLOAD_CHUNK: u8 = 1;

/// Helper to send a frame-length prefixed JSON-serialized message over a TcpStream.
pub async fn send_message(stream: &mut TcpStream, msg: &MigrationMessage) -> Result<()> {
    let serialized = encode_message(msg).context("Serialization failed")?;
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
    
    decode_message(&buffer).context("Deserialization failed")
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

fn encode_message(msg: &MigrationMessage) -> Result<Vec<u8>> {
    match msg {
        MigrationMessage::PayloadChunk {
            chunk_index,
            layer_index,
            tensor_name,
            data,
            crc32,
        } => {
            let name_bytes = tensor_name.as_bytes();
            let mut out = Vec::with_capacity(1 + 4 + 4 + 4 + name_bytes.len() + 4 + 4 + data.len());
            out.push(FRAME_KIND_PAYLOAD_CHUNK);
            out.extend_from_slice(&chunk_index.to_be_bytes());
            out.extend_from_slice(&layer_index.to_be_bytes());
            out.extend_from_slice(&(name_bytes.len() as u32).to_be_bytes());
            out.extend_from_slice(name_bytes);
            out.extend_from_slice(&crc32.to_be_bytes());
            out.extend_from_slice(&(data.len() as u32).to_be_bytes());
            out.extend_from_slice(data);
            Ok(out)
        }
        _ => {
            let json = serde_json::to_vec(msg)?;
            let mut out = Vec::with_capacity(1 + json.len());
            out.push(FRAME_KIND_JSON);
            out.extend_from_slice(&json);
            Ok(out)
        }
    }
}

fn decode_message(buffer: &[u8]) -> Result<MigrationMessage> {
    if buffer.is_empty() {
        bail!("Empty frame");
    }

    match buffer[0] {
        FRAME_KIND_JSON => Ok(serde_json::from_slice(&buffer[1..])?),
        FRAME_KIND_PAYLOAD_CHUNK => decode_payload_chunk(&buffer[1..]),
        other => bail!("Unknown frame kind: {}", other),
    }
}

fn decode_payload_chunk(buffer: &[u8]) -> Result<MigrationMessage> {
    let mut cursor = 0usize;

    let chunk_index = read_u32(buffer, &mut cursor)?;
    let layer_index = read_u32(buffer, &mut cursor)?;

    let name_len = read_u32(buffer, &mut cursor)? as usize;
    let name_end = cursor
        .checked_add(name_len)
        .context("Payload chunk tensor name length overflow")?;
    if name_end > buffer.len() {
        bail!("Payload chunk tensor name exceeds frame length");
    }
    let tensor_name = String::from_utf8(buffer[cursor..name_end].to_vec())
        .context("Payload chunk tensor name is not valid UTF-8")?;
    cursor = name_end;

    let crc32 = read_u32(buffer, &mut cursor)?;
    let data_len = read_u32(buffer, &mut cursor)? as usize;
    let data_end = cursor
        .checked_add(data_len)
        .context("Payload chunk data length overflow")?;
    if data_end != buffer.len() {
        bail!("Payload chunk data length does not match frame size");
    }

    Ok(MigrationMessage::PayloadChunk {
        chunk_index,
        layer_index,
        tensor_name,
        data: buffer[cursor..data_end].to_vec(),
        crc32,
    })
}

fn read_u32(buffer: &[u8], cursor: &mut usize) -> Result<u32> {
    let end = cursor
        .checked_add(4)
        .context("Frame cursor overflow while reading u32")?;
    if end > buffer.len() {
        bail!("Frame truncated while reading u32");
    }

    let bytes: [u8; 4] = buffer[*cursor..end]
        .try_into()
        .context("Failed to parse u32 bytes")?;
    *cursor = end;
    Ok(u32::from_be_bytes(bytes))
}
