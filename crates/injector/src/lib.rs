use anyhow::{Result, bail, Context};
use permeant_transpiler::Tensor;
use std::collections::HashMap;

/// Mock implementation of the production-grade `KVConnectorBase_V1` plugin.
/// Manages virtual block-allocation and injection into the target vLLM page manager.
pub struct KVConnectorBase_V1 {
    pub block_size: usize,
    // Maps content-addressable block hash (e.g. "sha256:...") to the layer-wise block tensor payload
    pub physical_cache: HashMap<String, HashMap<String, Tensor>>, 
}

impl KVConnectorBase_V1 {
    pub fn new(block_size: usize) -> Self {
        Self {
            block_size,
            physical_cache: HashMap::new(),
        }
    }
    
    /// Queries which prefix blocks are already cached locally.
    /// Returns the count of matching blocks.
    pub fn query_matching_prefix(&self, block_hashes: &[String]) -> usize {
        let mut match_count = 0;
        for hash in block_hashes {
            if self.physical_cache.contains_key(hash) {
                match_count += 1;
            } else {
                break; // must be contiguous prefix
            }
        }
        match_count
    }
    
    /// Injects a block's tensors into the physical cache.
    pub fn inject_block_tensors(
        &mut self,
        block_hash: String,
        tensors: HashMap<String, Tensor>,
    ) -> Result<()> {
        // Validation of shape: every tensor in GQA block should match block_size along the block dimension
        for (name, tensor) in &tensors {
            if name.ends_with(".key") {
                // vLLM block key layout: [num_blocks, num_kv_heads, head_dim, block_size]
                // For a single injected block, shape should be [1, num_kv_heads, head_dim, block_size]
                if tensor.shape.len() != 4 || tensor.shape[0] != 1 || tensor.shape[3] != self.block_size {
                    bail!(
                        "Invalid key block layout for tensor {}. Expected shape [1, H, D, {}], found {:?}",
                        name,
                        self.block_size,
                        tensor.shape
                    );
                }
            } else if name.ends_with(".value") {
                // vLLM block value layout: [num_blocks, num_kv_heads, block_size, head_dim]
                if tensor.shape.len() != 4 || tensor.shape[0] != 1 || tensor.shape[2] != self.block_size {
                    bail!(
                        "Invalid value block layout for tensor {}. Expected shape [1, H, {}, D], found {:?}",
                        name,
                        self.block_size,
                        tensor.shape
                    );
                }
            }
        }
        
        self.physical_cache.insert(block_hash, tensors);
        Ok(())
    }
    
    /// Verifies the continuity of generations on the injected blocks.
    /// Simulates running the attention layer check.
    pub fn verify_continuation(&self, block_hashes: &[String]) -> Result<()> {
        for hash in block_hashes {
            if !self.physical_cache.contains_key(hash) {
                bail!("Missing block in physical cache for hash: {}", hash);
            }
        }
        Ok(())
    }
}
