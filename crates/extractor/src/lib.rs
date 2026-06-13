use anyhow::{Result, Context};
use permeant_transpiler::Tensor;
use std::collections::HashMap;

/// Simulates extracting KV cache tensors from a hardware device (Metal/CUDA) or CPU.
/// Generates realistic structured tensor activations representing model state.
pub fn extract_kv_cache(
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
) -> Result<HashMap<String, Tensor>> {
    let mut cache = HashMap::new();
    
    // Size of each tensor: seq_len * n_kv_heads * head_dim
    let tensor_size = seq_len * n_kv_heads * head_dim;
    
    for i in 0..n_layers {
        let mut key_data = vec![0.0f32; tensor_size];
        let mut value_data = vec![0.0f32; tensor_size];
        
        // Populate with synthetic but highly structured activations (e.g., sine waves + decay)
        // to mimic real model KV cache states for numerical validation
        for t in 0..seq_len {
            for h in 0..n_kv_heads {
                for d in 0..head_dim {
                    let idx = t * (n_kv_heads * head_dim) + h * head_dim + d;
                    
                    // A mock model attention pattern (oscillations with high frequency & position-based decay)
                    let angle = (t as f32 * 0.1) + (h as f32 * 0.5) + (d as f32 * 0.05);
                    let decay = (-0.01 * t as f32).exp();
                    
                    key_data[idx] = angle.sin() * decay;
                    value_data[idx] = angle.cos() * decay;
                }
            }
        }
        
        let key_tensor = Tensor::new(key_data, vec![seq_len, n_kv_heads, head_dim]);
        let value_tensor = Tensor::new(value_data, vec![seq_len, n_kv_heads, head_dim]);
        
        cache.insert(format!("layer.{}.key", i), key_tensor);
        cache.insert(format!("layer.{}.value", i), value_tensor);
    }
    
    Ok(cache)
}
