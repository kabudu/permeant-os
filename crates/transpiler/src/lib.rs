pub mod layout;
pub mod quant;

pub use layout::*;
pub use quant::*;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gqa_layout_exactness() {
        let seq_len = 10;
        let num_kv_heads = 2;
        let head_dim = 8;
        let block_size = 4;

        // Create sequential canonical key tensor
        let mut key_data = Vec::new();
        for i in 0..(seq_len * num_kv_heads * head_dim) {
            key_data.push(i as f32);
        }
        let canonical_key = Tensor::new(key_data, vec![seq_len, num_kv_heads, head_dim]);

        // Transpile to vLLM blocks
        let vllm_key = canonical_to_vllm_block_key(&canonical_key, block_size).unwrap();
        assert_eq!(vllm_key.shape, vec![3, num_kv_heads, head_dim, block_size]);

        // Reconstruct canonical key
        let reconstructed_key =
            vllm_block_to_canonical_key(&vllm_key, seq_len, block_size).unwrap();
        assert_eq!(
            reconstructed_key.shape,
            vec![seq_len, num_kv_heads, head_dim]
        );
        assert_eq!(reconstructed_key.data, canonical_key.data);

        // Create sequential canonical value tensor
        let mut val_data = Vec::new();
        for i in 0..(seq_len * num_kv_heads * head_dim) {
            val_data.push(i as f32 * 0.5);
        }
        let canonical_val = Tensor::new(val_data, vec![seq_len, num_kv_heads, head_dim]);

        // Transpile to vLLM blocks
        let vllm_val = canonical_to_vllm_block_value(&canonical_val, block_size).unwrap();
        assert_eq!(vllm_val.shape, vec![3, num_kv_heads, block_size, head_dim]);

        // Reconstruct canonical value
        let reconstructed_val =
            vllm_block_to_canonical_value(&vllm_val, seq_len, block_size).unwrap();
        assert_eq!(
            reconstructed_val.shape,
            vec![seq_len, num_kv_heads, head_dim]
        );
        assert_eq!(reconstructed_val.data, canonical_val.data);
    }

    #[test]
    fn test_fp8_quantization_precision() {
        // Test standard values in normal range
        let test_vals = vec![0.0, 0.25, -0.75, 1.5, -3.25, 48.0, -120.0, 350.0];

        for &val in &test_vals {
            let byte_e4m3 = quant::f32_to_e4m3(val);
            let recon_e4m3 = quant::e4m3_to_f32(byte_e4m3);

            let byte_e5m2 = quant::f32_to_e5m2(val);
            let recon_e5m2 = quant::e5m2_to_f32(byte_e5m2);

            // Check that the error is within reasonable bounds (relative error is small)
            if val != 0.0 {
                let error_e4m3 = (recon_e4m3 - val).abs() / val.abs();
                let error_e5m2 = (recon_e5m2 - val).abs() / val.abs();
                // E4M3 has more mantissa, so precision should be higher (error generally < 15%)
                assert!(
                    error_e4m3 < 0.15,
                    "E4M3 error too large for {}: {}",
                    val,
                    error_e4m3
                );
                assert!(
                    error_e5m2 < 0.30,
                    "E5M2 error too large for {}: {}",
                    val,
                    error_e5m2
                );
            } else {
                assert_eq!(recon_e4m3, 0.0);
                assert_eq!(recon_e5m2, 0.0);
            }
        }
    }

    #[test]
    fn test_scaled_quantization_roundtrip() {
        let floats = vec![0.12, -0.55, 3.42, -9.10, 24.11, -87.65, 120.4, -310.5];
        let scale = quant::compute_optimal_scale(&floats, 448.0);

        let quantized = quant::quantize_e4m3_scaled(&floats, scale);
        let dequantized = quant::dequantize_e4m3_scaled(&quantized, scale);

        for i in 0..floats.len() {
            let diff = (dequantized[i] - floats[i]).abs();
            let relative_diff = diff / floats[i].abs();
            assert!(
                relative_diff < 0.15,
                "Scaled relative error too high for index {}: expected {}, got {}",
                i,
                floats[i],
                dequantized[i]
            );
        }
    }

    #[test]
    fn test_boundary_block_sizes() {
        let block_size = 4;
        let num_kv_heads = 1;
        let head_dim = 2;

        for seq_len in [3, 4, 5] {
            let mut key_data = vec![0.0f32; seq_len * num_kv_heads * head_dim];
            for (i, value) in key_data.iter_mut().enumerate() {
                *value = i as f32;
            }
            let canonical = Tensor::new(key_data, vec![seq_len, num_kv_heads, head_dim]);

            let vllm = canonical_to_vllm_block_key(&canonical, block_size).unwrap();
            let expected_blocks = seq_len.div_ceil(block_size);
            assert_eq!(vllm.shape[0], expected_blocks);

            let recon = vllm_block_to_canonical_key(&vllm, seq_len, block_size).unwrap();
            assert_eq!(recon.data, canonical.data);
        }
    }

    #[test]
    fn test_extreme_quantization_values() {
        let subnormal_pos = 1.0f32 / 2048.0;
        let byte = quant::f32_to_e4m3(subnormal_pos);
        let recon = quant::e4m3_to_f32(byte);
        assert!(recon >= 0.0);

        let large_val = 1000.0f32;
        let byte_large = quant::f32_to_e4m3(large_val);
        let recon_large = quant::e4m3_to_f32(byte_large);
        assert_eq!(recon_large, 448.0);

        let large_val_neg = -1000.0f32;
        let byte_large_neg = quant::f32_to_e4m3(large_val_neg);
        let recon_large_neg = quant::e4m3_to_f32(byte_large_neg);
        assert_eq!(recon_large_neg, -448.0);

        let nan_byte = quant::f32_to_e4m3(f32::NAN);
        let recon_nan = quant::e4m3_to_f32(nan_byte);
        assert!(recon_nan.is_nan());

        let nan_byte_e5m2 = quant::f32_to_e5m2(f32::NAN);
        let recon_nan_e5m2 = quant::e5m2_to_f32(nan_byte_e5m2);
        assert!(recon_nan_e5m2.is_nan());
    }

    #[test]
    fn test_qatq_i4_roundtrip_shape_and_compression() {
        let floats = vec![-2.4, -1.2, -0.5, 0.0, 0.4, 1.1, 2.2, 3.7, -4.1, 0.9, 1.8];
        let encoded = quant::quantize_qatq_i4(&floats);
        let decoded = quant::dequantize_qatq_i4(&encoded, floats.len()).unwrap();

        assert_eq!(decoded.len(), floats.len());
        assert!(encoded.len() < floats.len() * 4);
        let max_abs = floats
            .iter()
            .zip(decoded.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(0.0_f32, f32::max);
        assert!(max_abs < 0.7, "QATQ int4 error too large: {max_abs}");
    }

    #[test]
    fn test_qatq_i4_rejects_wrong_expected_len() {
        let encoded = quant::quantize_qatq_i4(&[1.0, 2.0, 3.0, 4.0]);
        let err = quant::dequantize_qatq_i4(&encoded, 3).unwrap_err();
        assert!(err.to_string().contains("length mismatch"));
    }

    #[test]
    fn test_qatq_phase2_transfer_compressed_roundtrip_is_exact() {
        let floats = vec![0.0_f32; 128];
        let encoded = quant::encode_qatq_phase2_transfer(&floats).unwrap();

        assert_eq!(encoded.storage_name(), quant::QATQ_PHASE2_STORAGE);
        assert_eq!(encoded.strategy_name(), Some("byte-plane-blocks"));
        assert!(encoded.payload.len() < encoded.raw_f32le_len);

        let decoded = quant::decode_qatq_phase2_transfer(
            encoded.storage_name(),
            &encoded.payload,
            floats.len(),
        )
        .unwrap();
        assert_eq!(f32_bits(&decoded), f32_bits(&floats));
    }

    #[test]
    fn test_qatq_phase2_transfer_pass_through_roundtrip_is_exact() {
        let floats = vec![
            f32::from_bits(0x0102_0304),
            f32::from_bits(0x1122_3344),
            f32::from_bits(0x5566_7788),
            f32::from_bits(0x99aa_bbcc),
        ];
        let encoded = quant::encode_qatq_phase2_transfer(&floats).unwrap();

        assert_eq!(
            encoded.storage_name(),
            quant::RAW_F32LE_PASS_THROUGH_STORAGE
        );
        assert_eq!(encoded.strategy_name(), None);
        assert_eq!(encoded.payload.len(), encoded.raw_f32le_len);

        let decoded = quant::decode_qatq_phase2_transfer(
            encoded.storage_name(),
            &encoded.payload,
            floats.len(),
        )
        .unwrap();
        assert_eq!(f32_bits(&decoded), f32_bits(&floats));
    }

    fn f32_bits(values: &[f32]) -> Vec<u32> {
        values.iter().map(|value| value.to_bits()).collect()
    }
}
