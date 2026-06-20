use anyhow::{bail, Context, Result};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use std::cmp::Reverse;
use std::collections::HashSet;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::TcpStream;
use usxf_core::crypto::EncryptedEnvelope;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentGraphBinding {
    pub manifest_path: String,
    pub graph_path: String,
    pub graph_hash: String,
    pub prompt_byte_hash: Option<String>,
    pub prompt_token_hash: Option<String>,
    pub tokenizer_hash: Option<String>,
    pub kv_hash: Option<String>,
    pub kv_spans: Vec<AgentGraphBindingKvSpan>,
    pub artifacts: Vec<AgentGraphBindingArtifact>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentGraphBindingKvSpan {
    pub node_id: String,
    pub token_start: usize,
    pub token_end: usize,
    pub cache_ref: String,
    pub tokenizer_hash: Option<String>,
    pub block_hashes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgentGraphBindingArtifact {
    pub path: String,
    pub sha256: String,
    pub size_bytes: Option<u64>,
}

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
    AgentGraphBinding(AgentGraphBinding),
    AgentGraphBindingAck {
        accepted: bool,
        error_message: Option<String>,
    },
    CommitRequest,
    CommitResponse {
        success: bool,
        error_message: Option<String>,
    },
}

const FRAME_KIND_JSON: u8 = 0;
const FRAME_KIND_PAYLOAD_CHUNK: u8 = 1;
pub const PRODUCTION_TRANSPORT_VERSION: u16 = 1;
pub const DEFAULT_MAX_BINARY_FRAME_BYTES: u32 = 64 * 1024 * 1024;
const BINARY_FRAME_MAGIC: [u8; 4] = *b"PMT1";
const BINARY_FRAME_HEADER_LEN: usize = 28;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ProductionTransportMode {
    WebSocketMtls,
    QuicMtls,
    RdmaUcx,
    Nixl,
    FramedTcpMtls,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProductionTransportProfile {
    pub mode: ProductionTransportMode,
    pub binary_framing: bool,
    pub require_mutual_tls: bool,
    pub max_frame_bytes: u32,
    pub idle_timeout_ms: u64,
    pub keepalive_interval_ms: u64,
    pub replay_window_frames: u32,
}

impl ProductionTransportProfile {
    pub fn websocket_mtls_binary() -> Self {
        Self {
            mode: ProductionTransportMode::WebSocketMtls,
            binary_framing: true,
            require_mutual_tls: true,
            max_frame_bytes: DEFAULT_MAX_BINARY_FRAME_BYTES,
            idle_timeout_ms: 30_000,
            keepalive_interval_ms: 10_000,
            replay_window_frames: 4096,
        }
    }

    pub fn quic_mtls_binary() -> Self {
        Self {
            mode: ProductionTransportMode::QuicMtls,
            binary_framing: true,
            require_mutual_tls: true,
            max_frame_bytes: DEFAULT_MAX_BINARY_FRAME_BYTES,
            idle_timeout_ms: 30_000,
            keepalive_interval_ms: 10_000,
            replay_window_frames: 4096,
        }
    }

    pub fn framed_tcp_mtls_binary() -> Self {
        Self {
            mode: ProductionTransportMode::FramedTcpMtls,
            binary_framing: true,
            require_mutual_tls: true,
            max_frame_bytes: 16 * 1024 * 1024,
            idle_timeout_ms: 30_000,
            keepalive_interval_ms: 10_000,
            replay_window_frames: 2048,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum EndpointRole {
    Source,
    Target,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SecureSessionHello {
    pub protocol_version: u16,
    pub session_id: String,
    pub role: EndpointRole,
    pub node_id: String,
    pub peer_node_id: Option<String>,
    pub profile: ProductionTransportProfile,
    pub nonce: Vec<u8>,
    pub supported_codecs: Vec<String>,
    pub public_key: Vec<u8>,
    pub signature: Vec<u8>,
}

#[derive(Debug, Clone, Serialize)]
struct SecureSessionHelloSigningPayload<'a> {
    protocol_version: u16,
    session_id: &'a str,
    role: &'a EndpointRole,
    node_id: &'a str,
    peer_node_id: &'a Option<String>,
    profile: &'a ProductionTransportProfile,
    nonce: &'a [u8],
    supported_codecs: &'a [String],
}

#[derive(Debug, Clone)]
pub struct SecureSessionHelloRequest {
    pub session_id: String,
    pub role: EndpointRole,
    pub node_id: String,
    pub peer_node_id: Option<String>,
    pub profile: ProductionTransportProfile,
    pub nonce: Vec<u8>,
    pub supported_codecs: Vec<String>,
}

impl SecureSessionHello {
    pub fn signed(request: SecureSessionHelloRequest, signing_key: &SigningKey) -> Result<Self> {
        if request.nonce.len() < 16 {
            bail!("secure session nonce must be at least 16 bytes");
        }
        if request.session_id.trim().is_empty() {
            bail!("secure session id must be non-empty");
        }
        if request.node_id.trim().is_empty() {
            bail!("secure session node id must be non-empty");
        }

        let payload = SecureSessionHelloSigningPayload {
            protocol_version: PRODUCTION_TRANSPORT_VERSION,
            session_id: &request.session_id,
            role: &request.role,
            node_id: &request.node_id,
            peer_node_id: &request.peer_node_id,
            profile: &request.profile,
            nonce: &request.nonce,
            supported_codecs: &request.supported_codecs,
        };
        let signed_payload = serde_json::to_vec(&payload)?;
        let signature = signing_key.sign(&signed_payload);

        Ok(Self {
            protocol_version: PRODUCTION_TRANSPORT_VERSION,
            session_id: request.session_id,
            role: request.role,
            node_id: request.node_id,
            peer_node_id: request.peer_node_id,
            profile: request.profile,
            nonce: request.nonce,
            supported_codecs: request.supported_codecs,
            public_key: signing_key.verifying_key().to_bytes().to_vec(),
            signature: signature.to_bytes().to_vec(),
        })
    }

    pub fn verify(&self) -> Result<()> {
        if self.protocol_version != PRODUCTION_TRANSPORT_VERSION {
            bail!(
                "unsupported production transport version: {}",
                self.protocol_version
            );
        }
        if self.nonce.len() < 16 {
            bail!("secure session nonce must be at least 16 bytes");
        }
        if self.session_id.trim().is_empty() || self.node_id.trim().is_empty() {
            bail!("secure session id and node id must be non-empty");
        }
        if self.profile.max_frame_bytes == 0 {
            bail!("secure session max_frame_bytes must be greater than zero");
        }
        if !self.profile.binary_framing {
            bail!("production transport requires binary framing");
        }
        if !self.profile.require_mutual_tls {
            bail!("production transport baseline requires mutual TLS");
        }

        let verifying_key = VerifyingKey::from_bytes(
            &self
                .public_key
                .clone()
                .try_into()
                .map_err(|_| anyhow::anyhow!("invalid secure session public key length"))?,
        )
        .context("failed to parse secure session public key")?;
        let signature_bytes: [u8; 64] = self
            .signature
            .clone()
            .try_into()
            .map_err(|_| anyhow::anyhow!("invalid secure session signature length"))?;
        let signature = Signature::from_bytes(&signature_bytes);
        let payload = SecureSessionHelloSigningPayload {
            protocol_version: self.protocol_version,
            session_id: &self.session_id,
            role: &self.role,
            node_id: &self.node_id,
            peer_node_id: &self.peer_node_id,
            profile: &self.profile,
            nonce: &self.nonce,
            supported_codecs: &self.supported_codecs,
        };
        let signed_payload = serde_json::to_vec(&payload)?;
        verifying_key
            .verify(&signed_payload, &signature)
            .context("secure session signature verification failed")?;
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TransportCandidate {
    pub profile: ProductionTransportProfile,
    pub priority: u16,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TransportNegotiationResult {
    pub selected: ProductionTransportProfile,
    pub selected_reason: String,
    pub considered_modes: Vec<ProductionTransportMode>,
}

pub fn default_transport_candidates() -> Vec<TransportCandidate> {
    vec![
        TransportCandidate {
            profile: ProductionTransportProfile::websocket_mtls_binary(),
            priority: 100,
            reason: "portable private-network baseline".to_string(),
        },
        TransportCandidate {
            profile: ProductionTransportProfile::quic_mtls_binary(),
            priority: 90,
            reason: "lower-latency stream transport when both endpoints support QUIC".to_string(),
        },
        TransportCandidate {
            profile: ProductionTransportProfile::framed_tcp_mtls_binary(),
            priority: 50,
            reason: "safe compatibility fallback when WebSocket or QUIC are unavailable"
                .to_string(),
        },
    ]
}

pub fn negotiate_transport(
    source_candidates: &[TransportCandidate],
    target_candidates: &[TransportCandidate],
) -> Result<TransportNegotiationResult> {
    let mut considered_modes = Vec::new();
    let mut compatible = Vec::new();

    for source in source_candidates {
        considered_modes.push(source.profile.mode.clone());
        for target in target_candidates {
            if source.profile.mode == target.profile.mode
                && source.profile.binary_framing
                && target.profile.binary_framing
                && source.profile.require_mutual_tls
                && target.profile.require_mutual_tls
            {
                let mut selected = source.profile.clone();
                selected.max_frame_bytes = source
                    .profile
                    .max_frame_bytes
                    .min(target.profile.max_frame_bytes);
                selected.idle_timeout_ms = source
                    .profile
                    .idle_timeout_ms
                    .min(target.profile.idle_timeout_ms);
                selected.keepalive_interval_ms = source
                    .profile
                    .keepalive_interval_ms
                    .min(target.profile.keepalive_interval_ms);
                selected.replay_window_frames = source
                    .profile
                    .replay_window_frames
                    .min(target.profile.replay_window_frames);
                compatible.push((
                    source.priority.min(target.priority),
                    selected,
                    format!("{}; target: {}", source.reason, target.reason),
                ));
            }
        }
    }

    compatible.sort_by_key(|candidate| Reverse(candidate.0));
    if let Some((_, selected, selected_reason)) = compatible.into_iter().next() {
        return Ok(TransportNegotiationResult {
            selected,
            selected_reason,
            considered_modes,
        });
    }

    bail!("no mutually supported production transport candidate");
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BinaryFrame {
    pub kind: u8,
    pub flags: u8,
    pub stream_id: u32,
    pub frame_index: u64,
    pub payload: Vec<u8>,
}

impl BinaryFrame {
    pub fn new(kind: u8, stream_id: u32, frame_index: u64, payload: Vec<u8>) -> Self {
        Self {
            kind,
            flags: 0,
            stream_id,
            frame_index,
            payload,
        }
    }
}

#[derive(Debug, Clone)]
pub struct BinaryFrameValidator {
    max_frame_bytes: u32,
    seen_frames: HashSet<(u32, u64)>,
}

impl BinaryFrameValidator {
    pub fn new(max_frame_bytes: u32) -> Self {
        Self {
            max_frame_bytes,
            seen_frames: HashSet::new(),
        }
    }

    pub fn accept(&mut self, frame: &BinaryFrame) -> Result<()> {
        if frame.payload.len() > self.max_frame_bytes as usize {
            bail!(
                "binary frame payload exceeds configured maximum: {} > {}",
                frame.payload.len(),
                self.max_frame_bytes
            );
        }
        let key = (frame.stream_id, frame.frame_index);
        if !self.seen_frames.insert(key) {
            bail!(
                "duplicate binary frame rejected: stream_id={}, frame_index={}",
                frame.stream_id,
                frame.frame_index
            );
        }
        Ok(())
    }
}

pub fn encode_binary_frame(frame: &BinaryFrame, max_frame_bytes: u32) -> Result<Vec<u8>> {
    if frame.payload.len() > max_frame_bytes as usize {
        bail!(
            "binary frame payload exceeds configured maximum: {} > {}",
            frame.payload.len(),
            max_frame_bytes
        );
    }
    let payload_len = frame.payload.len() as u32;
    let payload_crc32 = compute_crc32(&frame.payload);
    let mut out = Vec::with_capacity(BINARY_FRAME_HEADER_LEN + frame.payload.len());
    out.extend_from_slice(&BINARY_FRAME_MAGIC);
    out.extend_from_slice(&PRODUCTION_TRANSPORT_VERSION.to_be_bytes());
    out.push(frame.kind);
    out.push(frame.flags);
    out.extend_from_slice(&frame.stream_id.to_be_bytes());
    out.extend_from_slice(&frame.frame_index.to_be_bytes());
    out.extend_from_slice(&payload_len.to_be_bytes());
    out.extend_from_slice(&payload_crc32.to_be_bytes());
    out.extend_from_slice(&frame.payload);
    Ok(out)
}

pub fn decode_binary_frame(buffer: &[u8], max_frame_bytes: u32) -> Result<BinaryFrame> {
    if buffer.len() < BINARY_FRAME_HEADER_LEN {
        bail!("binary frame is too short: {} bytes", buffer.len());
    }
    if buffer[0..4] != BINARY_FRAME_MAGIC {
        bail!("invalid binary frame magic");
    }
    let mut cursor = 4usize;
    let version = read_u16(buffer, &mut cursor)?;
    if version != PRODUCTION_TRANSPORT_VERSION {
        bail!("unsupported binary frame version: {}", version);
    }
    let kind = buffer[cursor];
    cursor += 1;
    let flags = buffer[cursor];
    cursor += 1;
    let stream_id = read_u32(buffer, &mut cursor)?;
    let frame_index = read_u64(buffer, &mut cursor)?;
    let payload_len = read_u32(buffer, &mut cursor)? as usize;
    if payload_len > max_frame_bytes as usize {
        bail!(
            "binary frame payload exceeds configured maximum: {} > {}",
            payload_len,
            max_frame_bytes
        );
    }
    let payload_crc32 = read_u32(buffer, &mut cursor)?;
    let payload_end = cursor
        .checked_add(payload_len)
        .context("binary frame payload length overflow")?;
    if payload_end != buffer.len() {
        bail!("binary frame payload length does not match frame size");
    }
    let payload = buffer[cursor..payload_end].to_vec();
    let computed_crc32 = compute_crc32(&payload);
    if computed_crc32 != payload_crc32 {
        bail!(
            "binary frame CRC32 mismatch: expected {}, computed {}",
            payload_crc32,
            computed_crc32
        );
    }
    Ok(BinaryFrame {
        kind,
        flags,
        stream_id,
        frame_index,
        payload,
    })
}

pub async fn send_binary_frame<W>(
    writer: &mut W,
    frame: &BinaryFrame,
    max_frame_bytes: u32,
) -> Result<()>
where
    W: AsyncWrite + Unpin,
{
    let encoded = encode_binary_frame(frame, max_frame_bytes)?;
    writer
        .write_all(&encoded)
        .await
        .context("failed to write binary frame")?;
    writer
        .flush()
        .await
        .context("failed to flush binary frame")?;
    Ok(())
}

pub async fn recv_binary_frame<R>(reader: &mut R, max_frame_bytes: u32) -> Result<BinaryFrame>
where
    R: AsyncRead + Unpin,
{
    let mut header = vec![0u8; BINARY_FRAME_HEADER_LEN];
    reader
        .read_exact(&mut header)
        .await
        .context("failed to read binary frame header")?;

    if header[0..4] != BINARY_FRAME_MAGIC {
        bail!("invalid binary frame magic");
    }
    let mut cursor = 4usize;
    let version = read_u16(&header, &mut cursor)?;
    if version != PRODUCTION_TRANSPORT_VERSION {
        bail!("unsupported binary frame version: {}", version);
    }
    cursor += 1; // kind
    cursor += 1; // flags
    let _stream_id = read_u32(&header, &mut cursor)?;
    let _frame_index = read_u64(&header, &mut cursor)?;
    let payload_len = read_u32(&header, &mut cursor)? as usize;
    if payload_len > max_frame_bytes as usize {
        bail!(
            "binary frame payload exceeds configured maximum: {} > {}",
            payload_len,
            max_frame_bytes
        );
    }
    let mut buffer = header;
    buffer.resize(BINARY_FRAME_HEADER_LEN + payload_len, 0);
    reader
        .read_exact(&mut buffer[BINARY_FRAME_HEADER_LEN..])
        .await
        .context("failed to read binary frame payload")?;
    decode_binary_frame(&buffer, max_frame_bytes)
}

/// Helper to send a frame-length prefixed JSON-serialized message over a TcpStream.
pub async fn send_message(stream: &mut TcpStream, msg: &MigrationMessage) -> Result<()> {
    let serialized = encode_message(msg).context("Serialization failed")?;
    let len = serialized.len() as u32;
    stream
        .write_all(&len.to_be_bytes())
        .await
        .context("Failed to write frame length")?;
    stream
        .write_all(&serialized)
        .await
        .context("Failed to write frame content")?;
    stream.flush().await.context("Failed to flush stream")?;
    Ok(())
}

/// Helper to read a frame-length prefixed JSON-serialized message from a TcpStream.
pub async fn recv_message(stream: &mut TcpStream) -> Result<MigrationMessage> {
    let mut len_bytes = [0u8; 4];
    stream
        .read_exact(&mut len_bytes)
        .await
        .context("Failed to read frame length")?;
    let len = u32::from_be_bytes(len_bytes) as usize;

    // Safety check for massive messages
    if len > 500 * 1024 * 1024 {
        bail!("Frame size too large: {} bytes", len);
    }

    let mut buffer = vec![0u8; len];
    stream
        .read_exact(&mut buffer)
        .await
        .context("Failed to read frame content")?;

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

fn read_u16(buffer: &[u8], cursor: &mut usize) -> Result<u16> {
    let end = cursor
        .checked_add(2)
        .context("Frame cursor overflow while reading u16")?;
    if end > buffer.len() {
        bail!("Frame truncated while reading u16");
    }

    let bytes: [u8; 2] = buffer[*cursor..end]
        .try_into()
        .context("Failed to parse u16 bytes")?;
    *cursor = end;
    Ok(u16::from_be_bytes(bytes))
}

fn read_u64(buffer: &[u8], cursor: &mut usize) -> Result<u64> {
    let end = cursor
        .checked_add(8)
        .context("Frame cursor overflow while reading u64")?;
    if end > buffer.len() {
        bail!("Frame truncated while reading u64");
    }

    let bytes: [u8; 8] = buffer[*cursor..end]
        .try_into()
        .context("Failed to parse u64 bytes")?;
    *cursor = end;
    Ok(u64::from_be_bytes(bytes))
}
