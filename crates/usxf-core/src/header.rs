use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct UsxfHeader {
    pub usxf_version: String,                    // Must be "1.1"
    pub model_architecture: String,
    pub model_identity: ModelIdentity,
    pub attention_type: AttentionType,
    pub model_cache_spec: ModelCacheSpec,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mla_spec: Option<MlaSpec>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chat_state: Option<ChatState>,
    pub token_ids: Vec<u32>,
    pub seq_len: usize,
    pub batch_size: u32,                         // Currently must be 1
    pub dtype: ExchangeDtype,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_quantization: Option<QuantizationInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transfer_quantization: Option<QuantizationInfo>,
    pub block_size: usize,
    pub block_hashes: Vec<String>,               // "sha256:..."
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position_ids: Option<Vec<usize>>,
    #[serde(default)]
    pub extra: HashMap<String, serde_json::Value>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub extractor_id: String,
    pub checksum: String,                        // "sha256:..."
    pub signature: String,                       // "ed25519:..."
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AttentionType {
    Mha,
    Gqa,
    Mqa,
    Mla,
    Hybrid,
    Other,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExchangeDtype {
    Float16,
    Bfloat16,      // Recommended default
    Float32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelIdentity {
    pub config_hash: String,
    pub weights_revision: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelCacheSpec {
    pub n_layers: usize,
    pub n_q_heads: usize,
    pub n_kv_heads: usize,
    pub head_dim: usize,
    pub hidden_size: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_position_embeddings: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rope_theta: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sliding_window: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MlaSpec {
    pub latent_dim: usize,
    pub rope_head_dim: usize,
    pub nope_head_dim: usize,
    pub kv_lora_rank: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChatState {
    pub template_name: String,
    pub template_hash: String,
    pub turn_boundaries: Vec<usize>,
    pub roles: Vec<String>,                    // "system", "user", etc.
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct QuantizationInfo {
    pub scheme: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group_size: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scales: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsxfPacket {
    pub header: UsxfHeader,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload_path: Option<String>,
}
