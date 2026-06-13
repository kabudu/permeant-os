pub mod header;
pub mod crypto;
pub mod validation;

pub use header::*;
pub use crypto::*;
pub use validation::*;

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use std::collections::HashMap;

    #[test]
    fn test_serialization_and_validation() {
        let dummy_tokens = vec![1, 2, 3, 4, 5];
        let block_hashes = validation::compute_token_block_hashes(&dummy_tokens, 2);
        assert_eq!(block_hashes.len(), 3);

        let header = UsxfHeader {
            usxf_version: "1.1".to_string(),
            model_architecture: "Llama-3.1-8B".to_string(),
            model_identity: ModelIdentity {
                config_hash: "sha256:7f8e9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f".to_string(),
                weights_revision: "hf:meta-llama/Llama-3.1-8B".to_string(),
            },
            attention_type: AttentionType::Gqa,
            model_cache_spec: ModelCacheSpec {
                n_layers: 32,
                n_q_heads: 32,
                n_kv_heads: 8,
                head_dim: 128,
                hidden_size: 4096,
                max_position_embeddings: Some(131072),
                rope_theta: Some(500000.0),
                sliding_window: None,
            },
            mla_spec: None,
            chat_state: None,
            token_ids: dummy_tokens,
            seq_len: 5,
            batch_size: 1,
            dtype: ExchangeDtype::Bfloat16,
            source_quantization: None,
            transfer_quantization: None,
            block_size: 2,
            block_hashes,
            position_ids: None,
            extra: HashMap::new(),
            created_at: Utc::now(),
            extractor_id: "extractor-v1".to_string(),
            checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000000".to_string(),
            signature: "".to_string(),
        };

        let res = validation::validate_header(&header);
        assert!(res.is_ok(), "Header validation failed: {:?}", res);
    }

    #[test]
    fn test_encrypt_then_sign() {
        let plaintext = b"Hello PermeantOS crypto envelope!";
        let aes_key = [9u8; 32];
        
        let mut csprng = rand::rngs::OsRng;
        let signing_key = crypto::SigningKey::generate(&mut csprng);

        let sealed = crypto::seal_packet(plaintext, &aes_key, &signing_key);
        assert!(sealed.is_ok());
        let envelope = sealed.unwrap();

        let opened = crypto::open_packet(&envelope, &aes_key);
        assert!(opened.is_ok());
        assert_eq!(opened.unwrap(), plaintext);
        
        // Test tampering detection
        let mut tampered_envelope = envelope.clone();
        tampered_envelope.ciphertext[0] ^= 1; // flip a bit
        let tampered_open = crypto::open_packet(&tampered_envelope, &aes_key);
        assert!(tampered_open.is_err(), "Integrity verification should have failed!");
    }
}
