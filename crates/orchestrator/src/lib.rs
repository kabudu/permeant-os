pub mod decision;
pub mod policy;
pub mod state;

pub use decision::{evaluate_migration, MigrationDecision};
pub use policy::ResourcePolicy;
pub use state::{MigrationState, MigrationStateMachine};

use anyhow::Result;

#[derive(Debug, Clone)]
pub struct MigrationOrchestrator {
    pub policy: ResourcePolicy,
    pub active_migrations: usize,
    pub consecutive_failures: u32,
}

impl MigrationOrchestrator {
    pub fn new(policy: ResourcePolicy) -> Self {
        Self {
            policy,
            active_migrations: 0,
            consecutive_failures: 0,
        }
    }

    /// Pre-checks if migration is allowed under ResourcePolicy and model constraints.
    pub fn initiate_migration(
        &mut self,
        seq_len: usize,
        n_layers: usize,
        n_kv_heads: usize,
        head_dim: usize,
        transfer_quant: Option<&str>,
        network_bandwidth_bps: f64,
    ) -> Result<(MigrationStateMachine, MigrationDecision)> {
        // 1. Check circuit breaker
        self.policy
            .check_circuit_breaker(self.consecutive_failures)?;

        // 2. Check concurrency
        self.policy.check_concurrency(self.active_migrations)?;

        // 3. Evaluate warm-start decision boundary
        let decision = evaluate_migration(
            seq_len,
            n_layers,
            n_kv_heads,
            head_dim,
            transfer_quant,
            network_bandwidth_bps,
        );

        // 4. Check memory quota allocation
        self.policy
            .check_memory_allocation(decision.kv_cache_size_bytes, 0)?;

        self.active_migrations += 1;
        let sm = MigrationStateMachine::new();

        Ok((sm, decision))
    }

    /// Records a migration failure, incrementing circuit breaker counter.
    pub fn record_failure(&mut self) {
        self.consecutive_failures += 1;
        if self.active_migrations > 0 {
            self.active_migrations -= 1;
        }
    }

    /// Records a migration success, resetting circuit breaker counter.
    pub fn record_success(&mut self) {
        self.consecutive_failures = 0;
        if self.active_migrations > 0 {
            self.active_migrations -= 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_migration_state_transitions() {
        let mut sm = MigrationStateMachine::new();
        assert_eq!(sm.current_state(), MigrationState::Idle);

        assert!(sm.transition_to(MigrationState::Extracting).is_ok());
        assert_eq!(sm.current_state(), MigrationState::Extracting);

        assert!(sm.transition_to(MigrationState::Streaming).is_ok());
        assert_eq!(sm.current_state(), MigrationState::Streaming);

        // Invalid transition: Streaming directly to Committed
        assert!(sm.transition_to(MigrationState::Committed).is_err());

        // Valid rollback transition
        assert!(sm.transition_to(MigrationState::RolledBack).is_ok());
        assert_eq!(sm.current_state(), MigrationState::RolledBack);

        // Cannot transition out of terminal state
        assert!(sm.transition_to(MigrationState::Idle).is_err());
    }

    #[test]
    fn test_resource_policy_quotas() {
        let policy = ResourcePolicy {
            max_concurrent_migrations: 2,
            max_memory_quota_bytes: 1000,
            circuit_breaker_threshold: 3,
            ..Default::default()
        };
        let orch = MigrationOrchestrator::new(policy);

        // Check concurrency limits
        assert!(orch.policy.check_concurrency(0).is_ok());
        assert!(orch.policy.check_concurrency(1).is_ok());
        assert!(orch.policy.check_concurrency(2).is_err());

        // Check memory allocation limits
        assert!(orch.policy.check_memory_allocation(400, 200).is_ok());
        assert!(orch.policy.check_memory_allocation(900, 200).is_err());

        // Check circuit breaker
        assert!(orch.policy.check_circuit_breaker(0).is_ok());
        assert!(orch.policy.check_circuit_breaker(2).is_ok());
        assert!(orch.policy.check_circuit_breaker(3).is_err());
    }

    #[test]
    fn test_warm_start_decision_boundary() {
        let n_layers = 32;
        let n_kv_heads = 8;
        let head_dim = 128;

        // Case A: 16k context, slow 10 Gbps network (FP16 default)
        // estimated_transfer_time is around 0.15 + (16384 * 8 * 128 * 32 * 2 * 2 * 8 / 1e10) = 0.15 + 0.17 = 0.32 seconds.
        // estimated_prefill_time = 16384 * 1e-5 + 16384^2 * 6e-10 = 0.16 + 0.16 = 0.32 seconds.
        // 0.32 <= 0.32 * 0.7 is false -> should NOT migrate (prefill is fast)
        let dec_slow = evaluate_migration(
            16384,
            n_layers,
            n_kv_heads,
            head_dim,
            None,
            10_000_000_000.0,
        );
        assert!(!dec_slow.should_migrate);

        // Case B: 64k context, fast 25 Gbps network with FP8 transfer quantization
        // KV size is 1/2 due to FP8. Transfer time is tiny. Prefill time is quadratic (around 3.2 seconds).
        // Transfer time is 0.15 + (65536 * 8 * 128 * 32 * 2 * 1 * 8 / 25e9) = 0.15 + 0.13 = 0.28 seconds.
        // Prefill time is 0.65 + 2.57 = 3.22 seconds.
        // 0.28 <= 3.22 * 0.7 is true -> should migrate (migration wins significantly)
        let dec_fast = evaluate_migration(
            65536,
            n_layers,
            n_kv_heads,
            head_dim,
            Some("fp8"),
            25_000_000_000.0,
        );
        assert!(dec_fast.should_migrate);
    }
}
