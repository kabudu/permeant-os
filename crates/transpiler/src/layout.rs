use anyhow::{Result, bail, Context};

#[derive(Debug, Clone, PartialEq)]
pub struct Tensor {
    pub data: Vec<f32>,
    pub shape: Vec<usize>,
}

impl Tensor {
    pub fn new(data: Vec<f32>, shape: Vec<usize>) -> Self {
        Self { data, shape }
    }
    
    pub fn size(&self) -> usize {
        self.shape.iter().product()
    }
}

/// Transpiles a Key tensor from USXF canonical layout [seq_len, num_kv_heads, head_dim]
/// to vLLM's block layout [num_blocks, num_kv_heads, head_dim, block_size].
pub fn canonical_to_vllm_block_key(
    canonical: &Tensor,
    block_size: usize,
) -> Result<Tensor> {
    if canonical.shape.len() != 3 {
        bail!("Canonical key must have 3 dimensions [seq_len, num_kv_heads, head_dim]");
    }
    let seq_len = canonical.shape[0];
    let num_kv_heads = canonical.shape[1];
    let head_dim = canonical.shape[2];
    
    let num_blocks = (seq_len + block_size - 1) / block_size;
    let total_vllm_size = num_blocks * num_kv_heads * head_dim * block_size;
    let mut vllm_data = vec![0.0f32; total_vllm_size];
    
    for block_idx in 0..num_blocks {
        for head_idx in 0..num_kv_heads {
            for dim_idx in 0..head_dim {
                for token_in_block in 0..block_size {
                    let global_token_idx = block_idx * block_size + token_in_block;
                    
                    let vllm_offset = block_idx * (num_kv_heads * head_dim * block_size)
                        + head_idx * (head_dim * block_size)
                        + dim_idx * block_size
                        + token_in_block;
                        
                    if global_token_idx < seq_len {
                        let canonical_offset = global_token_idx * (num_kv_heads * head_dim)
                            + head_idx * head_dim
                            + dim_idx;
                        vllm_data[vllm_offset] = canonical.data[canonical_offset];
                    } else {
                        // Pad with zero for empty slots in the last block
                        vllm_data[vllm_offset] = 0.0;
                    }
                }
            }
        }
    }
    
    Ok(Tensor::new(vllm_data, vec![num_blocks, num_kv_heads, head_dim, block_size]))
}

/// Transpiles a Key tensor from vLLM block layout [num_blocks, num_kv_heads, head_dim, block_size]
/// back to USXF canonical layout [seq_len, num_kv_heads, head_dim].
pub fn vllm_block_to_canonical_key(
    vllm: &Tensor,
    seq_len: usize,
    block_size: usize,
) -> Result<Tensor> {
    if vllm.shape.len() != 4 {
        bail!("vLLM block key must have 4 dimensions [num_blocks, num_kv_heads, head_dim, block_size]");
    }
    let num_blocks = vllm.shape[0];
    let num_kv_heads = vllm.shape[1];
    let head_dim = vllm.shape[2];
    let block_size_check = vllm.shape[3];
    
    if block_size != block_size_check {
        bail!("Block size mismatch: expected {}, found {}", block_size, block_size_check);
    }
    
    let expected_blocks = (seq_len + block_size - 1) / block_size;
    if num_blocks < expected_blocks {
        bail!("vLLM tensor doesn't contain enough blocks for seq_len {}", seq_len);
    }
    
    let canonical_size = seq_len * num_kv_heads * head_dim;
    let mut canonical_data = vec![0.0f32; canonical_size];
    
    for t in 0..seq_len {
        let block_idx = t / block_size;
        let token_in_block = t % block_size;
        
        for h in 0..num_kv_heads {
            for d in 0..head_dim {
                let vllm_offset = block_idx * (num_kv_heads * head_dim * block_size)
                    + h * (head_dim * block_size)
                    + d * block_size
                    + token_in_block;
                    
                let canonical_offset = t * (num_kv_heads * head_dim) + h * head_dim + d;
                
                canonical_data[canonical_offset] = vllm.data[vllm_offset];
            }
        }
    }
    
    Ok(Tensor::new(canonical_data, vec![seq_len, num_kv_heads, head_dim]))
}

/// Transpiles a Value tensor from USXF canonical layout [seq_len, num_kv_heads, head_dim]
/// to vLLM's block layout [num_blocks, num_kv_heads, block_size, head_dim].
pub fn canonical_to_vllm_block_value(
    canonical: &Tensor,
    block_size: usize,
) -> Result<Tensor> {
    if canonical.shape.len() != 3 {
        bail!("Canonical value must have 3 dimensions [seq_len, num_kv_heads, head_dim]");
    }
    let seq_len = canonical.shape[0];
    let num_kv_heads = canonical.shape[1];
    let head_dim = canonical.shape[2];
    
    let num_blocks = (seq_len + block_size - 1) / block_size;
    let total_vllm_size = num_blocks * num_kv_heads * block_size * head_dim;
    let mut vllm_data = vec![0.0f32; total_vllm_size];
    
    for block_idx in 0..num_blocks {
        for head_idx in 0..num_kv_heads {
            for token_in_block in 0..block_size {
                let global_token_idx = block_idx * block_size + token_in_block;
                
                for dim_idx in 0..head_dim {
                    let vllm_offset = block_idx * (num_kv_heads * block_size * head_dim)
                        + head_idx * (block_size * head_dim)
                        + token_in_block * head_dim
                        + dim_idx;
                        
                    if global_token_idx < seq_len {
                        let canonical_offset = global_token_idx * (num_kv_heads * head_dim)
                            + head_idx * head_dim
                            + dim_idx;
                        vllm_data[vllm_offset] = canonical.data[canonical_offset];
                    } else {
                        vllm_data[vllm_offset] = 0.0;
                    }
                }
            }
        }
    }
    
    Ok(Tensor::new(vllm_data, vec![num_blocks, num_kv_heads, block_size, head_dim]))
}

/// Transpiles a Value tensor from vLLM block layout [num_blocks, num_kv_heads, block_size, head_dim]
/// back to USXF canonical layout [seq_len, num_kv_heads, head_dim].
pub fn vllm_block_to_canonical_value(
    vllm: &Tensor,
    seq_len: usize,
    block_size: usize,
) -> Result<Tensor> {
    if vllm.shape.len() != 4 {
        bail!("vLLM block value must have 4 dimensions [num_blocks, num_kv_heads, block_size, head_dim]");
    }
    let num_blocks = vllm.shape[0];
    let num_kv_heads = vllm.shape[1];
    let block_size_check = vllm.shape[2];
    let head_dim = vllm.shape[3];
    
    if block_size != block_size_check {
        bail!("Block size mismatch: expected {}, found {}", block_size, block_size_check);
    }
    
    let expected_blocks = (seq_len + block_size - 1) / block_size;
    if num_blocks < expected_blocks {
        bail!("vLLM tensor doesn't contain enough blocks for seq_len {}", seq_len);
    }
    
    let canonical_size = seq_len * num_kv_heads * head_dim;
    let mut canonical_data = vec![0.0f32; canonical_size];
    
    for t in 0..seq_len {
        let block_idx = t / block_size;
        let token_in_block = t % block_size;
        
        for h in 0..num_kv_heads {
            for d in 0..head_dim {
                let vllm_offset = block_idx * (num_kv_heads * block_size * head_dim)
                    + h * (block_size * head_dim)
                    + token_in_block * head_dim
                    + d;
                    
                let canonical_offset = t * (num_kv_heads * head_dim) + h * head_dim + d;
                
                canonical_data[canonical_offset] = vllm.data[vllm_offset];
            }
        }
    }
    
    Ok(Tensor::new(canonical_data, vec![seq_len, num_kv_heads, head_dim]))
}
