use crate::state::MigrationState;
use anyhow::{bail, Result};
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct ResourcePolicy {
    pub max_concurrent_migrations: usize,
    pub max_memory_quota_bytes: u64,
    pub phase_timeouts: HashMap<MigrationState, u64>, // State -> Timeout in seconds
    pub circuit_breaker_threshold: u32,               // Max consecutive failures
}

impl Default for ResourcePolicy {
    fn default() -> Self {
        let mut timeouts = HashMap::new();
        timeouts.insert(MigrationState::Idle, 30);
        timeouts.insert(MigrationState::Extracting, 120);
        timeouts.insert(MigrationState::Streaming, 300);
        timeouts.insert(MigrationState::Injecting, 120);
        timeouts.insert(MigrationState::Validating, 60);

        Self {
            max_concurrent_migrations: 4,
            max_memory_quota_bytes: 32 * 1024 * 1024 * 1024, // 32 GB default
            phase_timeouts: timeouts,
            circuit_breaker_threshold: 5,
        }
    }
}

impl ResourcePolicy {
    /// Checks if a new migration can proceed based on active concurrent migration count.
    pub fn check_concurrency(&self, active_count: usize) -> Result<()> {
        if active_count >= self.max_concurrent_migrations {
            bail!(
                "Resource quota exceeded: Max concurrent migrations is {}, currently running {}",
                self.max_concurrent_migrations,
                active_count
            );
        }
        Ok(())
    }

    /// Checks if memory limits are respected.
    pub fn check_memory_allocation(
        &self,
        requested_bytes: u64,
        current_allocated: u64,
    ) -> Result<()> {
        if current_allocated + requested_bytes > self.max_memory_quota_bytes {
            bail!(
                "Resource quota exceeded: Requested {} bytes, which exceeds remaining memory quota (max {}, currently allocated {})",
                requested_bytes,
                self.max_memory_quota_bytes,
                current_allocated
            );
        }
        Ok(())
    }

    /// Checks if the elapsed time exceeds the configured timeout for a state.
    pub fn is_phase_timed_out(&self, state: MigrationState, elapsed_seconds: u64) -> bool {
        if let Some(&timeout) = self.phase_timeouts.get(&state) {
            elapsed_seconds > timeout
        } else {
            false
        }
    }

    /// Checks if the circuit breaker has triggered due to excessive consecutive failures.
    pub fn check_circuit_breaker(&self, consecutive_failures: u32) -> Result<()> {
        if consecutive_failures >= self.circuit_breaker_threshold {
            bail!(
                "Circuit breaker active: Migration service disabled due to {} consecutive failures (threshold {})",
                consecutive_failures,
                self.circuit_breaker_threshold
            );
        }
        Ok(())
    }
}
