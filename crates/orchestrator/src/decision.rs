#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MigrationDecision {
    pub should_migrate: bool,
    pub estimated_transfer_time_secs: f64,
    pub estimated_prefill_time_secs: f64,
    pub kv_cache_size_bytes: u64,
}

use serde::{Deserialize, Serialize};

/// Evaluates whether migrating the KV cache is faster than re-prefilling the context.
/// According to the plan: if estimated_transfer_time > estimated_prefill_time * 0.7, recommend re-prefill (false).
pub fn evaluate_migration(
    seq_len: usize,
    n_layers: usize,
    n_kv_heads: usize,
    head_dim: usize,
    transfer_quantization_scheme: Option<&str>,
    network_bandwidth_bps: f64, // e.g. 10_000_000_000 for 10 Gbps
) -> MigrationDecision {
    // 1. Calculate bytes per element
    let bytes_per_element = match transfer_quantization_scheme {
        Some("fp8") | Some("int8") => 1,
        _ => 2, // Default to float16/bfloat16 (2 bytes)
    };

    // 2. Compute KV cache size: n_layers * 2 (key & value) * n_kv_heads * head_dim * seq_len * bytes_per_element
    let kv_cache_size_bytes =
        (n_layers * 2 * n_kv_heads * head_dim * seq_len * bytes_per_element) as u64;

    // 3. Estimate transfer time: size in bits / bandwidth in bps + fixed protocol overhead
    let transfer_bits = (kv_cache_size_bytes * 8) as f64;
    let base_transfer_time = transfer_bits / network_bandwidth_bps;
    let protocol_overhead_secs = 0.15; // 150ms network negotiation + state machine transitions
    let estimated_transfer_time_secs = base_transfer_time + protocol_overhead_secs;

    // 4. Estimate prefill time (empirical model reflecting linear-to-quadratic attention curve)
    // t_prefill = linear_cost + quadratic_cost
    // linear_cost models weight loading & memory bandwidth
    // quadratic_cost models self-attention computation
    let seq_len_f = seq_len as f64;
    let linear_cost = seq_len_f * 1e-5;
    let quadratic_cost = seq_len_f.powi(2) * 6e-10;
    let estimated_prefill_time_secs = linear_cost + quadratic_cost;

    // 5. Decision criteria: migrate if estimated_transfer_time <= 0.7 * estimated_prefill_time
    let should_migrate = estimated_transfer_time_secs <= (estimated_prefill_time_secs * 0.7);

    MigrationDecision {
        should_migrate,
        estimated_transfer_time_secs,
        estimated_prefill_time_secs,
        kv_cache_size_bytes,
    }
}
