/// Cumulative runtime state — tracks tokens, cost, and last-run status per agent.
/// Persists to a JSON file for dashboard consumption and cross-restart continuity.
use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};

// ============================================================================
// Types
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentRuntimeState {
    pub agent_id: String,
    pub session_id: Option<String>,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub total_cost_cents: f64,
    pub last_run_status: String,
    pub last_error: Option<String>,
    pub updated_at: String, // ISO 8601
}

// ============================================================================
// RuntimeStateManager
// ============================================================================

pub struct RuntimeStateManager {
    states: Mutex<HashMap<String, AgentRuntimeState>>,
    state_file: PathBuf,
}

impl RuntimeStateManager {
    /// Create a new manager, loading persisted state if the file exists.
    pub fn new(state_file: PathBuf) -> Self {
        let states = if state_file.exists() {
            match std::fs::read_to_string(&state_file) {
                Ok(content) => {
                    match serde_json::from_str::<HashMap<String, AgentRuntimeState>>(&content) {
                        Ok(s) => {
                            info!("runtime_state: loaded {} agents from {}", s.len(), state_file.display());
                            s
                        }
                        Err(e) => {
                            warn!("runtime_state: failed to parse state file: {}", e);
                            HashMap::new()
                        }
                    }
                }
                Err(e) => {
                    warn!("runtime_state: failed to read state file: {}", e);
                    HashMap::new()
                }
            }
        } else {
            HashMap::new()
        };

        Self {
            states: Mutex::new(states),
            state_file,
        }
    }

    /// Update state after a Claude session completes. Accumulates tokens and cost.
    pub async fn update_on_completion(
        &self,
        agent_id: &str,
        session_id: Option<&str>,
        input_tokens: u64,
        output_tokens: u64,
        cost_usd: Option<f64>,
        status: &str,
        error: Option<&str>,
    ) {
        let mut states = self.states.lock().await;
        let state = states
            .entry(agent_id.to_string())
            .or_insert_with(|| AgentRuntimeState {
                agent_id: agent_id.to_string(),
                session_id: None,
                total_input_tokens: 0,
                total_output_tokens: 0,
                total_cost_cents: 0.0,
                last_run_status: String::new(),
                last_error: None,
                updated_at: String::new(),
            });

        state.session_id = session_id.map(|s| s.to_string());
        state.total_input_tokens += input_tokens;
        state.total_output_tokens += output_tokens;
        if let Some(usd) = cost_usd {
            state.total_cost_cents += usd * 100.0;
        }
        state.last_run_status = status.to_string();
        state.last_error = error.map(|e| e.to_string());
        state.updated_at = Utc::now().to_rfc3339();

        debug!(
            "runtime_state: {} — {}+{} tokens, status={}",
            agent_id, input_tokens, output_tokens, status
        );
    }

    /// Get state for a single agent.
    pub async fn get_state(&self, agent_id: &str) -> Option<AgentRuntimeState> {
        let states = self.states.lock().await;
        states.get(agent_id).cloned()
    }

    /// Get all agent states.
    pub async fn get_all_states(&self) -> Vec<AgentRuntimeState> {
        let states = self.states.lock().await;
        states.values().cloned().collect()
    }

    /// Persist current state to the JSON file.
    pub async fn persist(&self) -> Result<()> {
        let states = self.states.lock().await;
        let json = serde_json::to_string_pretty(&*states)?;

        if let Some(parent) = self.state_file.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&self.state_file, json)?;
        debug!("runtime_state: persisted to {}", self.state_file.display());

        Ok(())
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_state_file() -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("runtime-state-test-{}.json", std::process::id()));
        p
    }

    #[tokio::test]
    async fn accumulation() {
        let mgr = RuntimeStateManager::new(temp_state_file());

        mgr.update_on_completion("boot", Some("s1"), 100, 50, Some(0.01), "success", None)
            .await;
        mgr.update_on_completion("boot", Some("s2"), 200, 75, Some(0.02), "success", None)
            .await;

        let state = mgr.get_state("boot").await.unwrap();
        assert_eq!(state.total_input_tokens, 300);
        assert_eq!(state.total_output_tokens, 125);
        assert!((state.total_cost_cents - 3.0).abs() < 0.001);
        assert_eq!(state.session_id.as_deref(), Some("s2"));
    }

    #[tokio::test]
    async fn persistence_round_trip() {
        let path = temp_state_file();

        {
            let mgr = RuntimeStateManager::new(path.clone());
            mgr.update_on_completion("ig88", None, 500, 200, Some(0.05), "success", None)
                .await;
            mgr.persist().await.unwrap();
        }

        {
            let mgr = RuntimeStateManager::new(path.clone());
            let state = mgr.get_state("ig88").await.unwrap();
            assert_eq!(state.total_input_tokens, 500);
            assert_eq!(state.total_output_tokens, 200);
        }

        let _ = std::fs::remove_file(&path);
    }

    #[tokio::test]
    async fn get_all_states() {
        let mgr = RuntimeStateManager::new(temp_state_file());
        mgr.update_on_completion("boot", None, 10, 5, None, "success", None)
            .await;
        mgr.update_on_completion("ig88", None, 20, 10, None, "error", Some("timeout"))
            .await;

        let all = mgr.get_all_states().await;
        assert_eq!(all.len(), 2);
    }

    #[tokio::test]
    async fn error_tracking() {
        let mgr = RuntimeStateManager::new(temp_state_file());
        mgr.update_on_completion("boot", None, 10, 5, None, "error", Some("process crashed"))
            .await;

        let state = mgr.get_state("boot").await.unwrap();
        assert_eq!(state.last_run_status, "error");
        assert_eq!(state.last_error.as_deref(), Some("process crashed"));
    }
}
