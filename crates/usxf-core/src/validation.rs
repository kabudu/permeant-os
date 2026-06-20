use crate::header::{AttentionType, UsxfHeader};
use crate::version::USXF_VERSION;
use anyhow::{bail, Result};
use sha2::{Digest, Sha256};

/// Validates the structure and constraints of the current USXF header version.
pub fn validate_header(header: &UsxfHeader) -> Result<()> {
    if header.usxf_version != USXF_VERSION {
        bail!(
            "Invalid USXF version: expected '{}', found '{}'",
            USXF_VERSION,
            header.usxf_version
        );
    }

    if header.batch_size != 1 {
        bail!(
            "USXF v1.1 supports only single-sequence migration (batch_size must be 1). Found batch_size: {}",
            header.batch_size
        );
    }

    if header.seq_len == 0 {
        bail!("seq_len must be greater than 0");
    }

    if header.block_size == 0 {
        bail!("block_size must be greater than 0");
    }

    let expected_blocks = header.seq_len.div_ceil(header.block_size);
    if header.block_hashes.len() != expected_blocks {
        bail!(
            "Mismatch in block_hashes size. seq_len: {}, block_size: {}, expected {} hashes, found {}",
            header.seq_len,
            header.block_size,
            expected_blocks,
            header.block_hashes.len()
        );
    }

    if header.attention_type == AttentionType::Mla && header.mla_spec.is_none() {
        bail!("mla_spec is required when attention_type is 'mla'");
    }

    // Check that config_hash is a valid hex sha256 hash
    if !header.model_identity.config_hash.starts_with("sha256:") {
        bail!("model_identity.config_hash must start with 'sha256:'");
    }

    if !header.checksum.starts_with("sha256:") {
        bail!("checksum must start with 'sha256:'");
    }

    Ok(())
}

/// Helper to compute SHA-256 hash of a payload.
pub fn compute_sha256(payload: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(payload);
    format!("sha256:{:x}", hasher.finalize())
}

/// Computes hashes of token blocks of size `block_size`.
pub fn compute_token_block_hashes(tokens: &[u32], block_size: usize) -> Vec<String> {
    tokens
        .chunks(block_size)
        .map(|chunk| {
            let mut hasher = Sha256::new();
            for token in chunk {
                hasher.update(token.to_be_bytes());
            }
            format!("sha256:{:x}", hasher.finalize())
        })
        .collect()
}
