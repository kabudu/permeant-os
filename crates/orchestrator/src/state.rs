use anyhow::{bail, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum MigrationState {
    Idle,
    Extracting,
    Streaming,
    Injecting,
    Validating,
    Committed,
    RolledBack,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MigrationStateMachine {
    current_state: MigrationState,
    updated_at: DateTime<Utc>,
    history: Vec<(MigrationState, DateTime<Utc>)>,
}

impl MigrationStateMachine {
    pub fn new() -> Self {
        let now = Utc::now();
        Self {
            current_state: MigrationState::Idle,
            updated_at: now,
            history: vec![(MigrationState::Idle, now)],
        }
    }

    pub fn current_state(&self) -> MigrationState {
        self.current_state
    }

    pub fn history(&self) -> &[(MigrationState, DateTime<Utc>)] {
        &self.history
    }

    pub fn transition_to(&mut self, next: MigrationState) -> Result<()> {
        let valid = match (self.current_state, next) {
            // Idle can transition to Extracting or RolledBack
            (MigrationState::Idle, MigrationState::Extracting) => true,
            (MigrationState::Idle, MigrationState::RolledBack) => true,

            // Extracting can transition to Streaming or RolledBack
            (MigrationState::Extracting, MigrationState::Streaming) => true,
            (MigrationState::Extracting, MigrationState::RolledBack) => true,

            // Streaming can transition to Injecting or RolledBack
            (MigrationState::Streaming, MigrationState::Injecting) => true,
            (MigrationState::Streaming, MigrationState::RolledBack) => true,

            // Injecting can transition to Validating or RolledBack
            (MigrationState::Injecting, MigrationState::Validating) => true,
            (MigrationState::Injecting, MigrationState::RolledBack) => true,

            // Validating can transition to Committed or RolledBack
            (MigrationState::Validating, MigrationState::Committed) => true,
            (MigrationState::Validating, MigrationState::RolledBack) => true,

            // Terminal states cannot transition anywhere
            (MigrationState::Committed, _) => false,
            (MigrationState::RolledBack, _) => false,

            // Allow same state transition (noop)
            (s1, s2) if s1 == s2 => true,

            _ => false,
        };

        if !valid {
            bail!(
                "Invalid state transition from {:?} to {:?}",
                self.current_state,
                next
            );
        }

        if self.current_state != next {
            let now = Utc::now();
            self.current_state = next;
            self.updated_at = now;
            self.history.push((next, now));
        }

        Ok(())
    }
}

impl Default for MigrationStateMachine {
    fn default() -> Self {
        Self::new()
    }
}
