/// Per-agent budget tracking with soft/hard thresholds and incident management.
/// Persists state to a JSON file for recovery across restarts.
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
pub struct AgentBudget {
    pub agent_id: String,
    pub monthly_limit_usd: f64,
    pub spent_this_month_usd: f64,
    pub month_key: String, // "YYYY-MM"
}

#[derive(Debug, Clone)]
pub enum BudgetCheckResult {
    Normal,
    Warning { pct: f64 },
    Paused { reason: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ThresholdType {
    Soft,
    Hard,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum IncidentStatus {
    Open,
    Resolved,
    Dismissed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetIncident {
    pub id: String,
    pub agent_id: String,
    pub threshold_type: ThresholdType,
    pub amount_limit: f64,
    pub amount_observed: f64,
    pub status: IncidentStatus,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedState {
    budgets: HashMap<String, AgentBudget>,
    incidents: Vec<BudgetIncident>,
}

// ============================================================================
// BudgetTracker
// ============================================================================

pub struct BudgetTracker {
    budgets: Mutex<HashMap<String, AgentBudget>>,
    incidents: Mutex<Vec<BudgetIncident>>,
    state_file: PathBuf,
}

impl BudgetTracker {
    /// Create a new tracker, loading persisted state if the file exists.
    pub fn new(state_file: PathBuf) -> Self {
        let (budgets, incidents) = if state_file.exists() {
            match std::fs::read_to_string(&state_file) {
                Ok(content) => match serde_json::from_str::<PersistedState>(&content) {
                    Ok(state) => {
                        info!("budget: loaded state from {}", state_file.display());
                        (state.budgets, state.incidents)
                    }
                    Err(e) => {
                        warn!("budget: failed to parse state file: {}", e);
                        (HashMap::new(), Vec::new())
                    }
                },
                Err(e) => {
                    warn!("budget: failed to read state file: {}", e);
                    (HashMap::new(), Vec::new())
                }
            }
        } else {
            (HashMap::new(), Vec::new())
        };

        Self {
            budgets: Mutex::new(budgets),
            incidents: Mutex::new(incidents),
            state_file,
        }
    }

    /// Initialize budget tracking for an agent.
    pub async fn init_agent(&self, agent_id: &str, monthly_limit_usd: f64) {
        let mut budgets = self.budgets.lock().await;
        let month_key = current_month_key();
        budgets.insert(
            agent_id.to_string(),
            AgentBudget {
                agent_id: agent_id.to_string(),
                monthly_limit_usd,
                spent_this_month_usd: 0.0,
                month_key,
            },
        );
        debug!("budget: initialized {} with ${:.2}/month", agent_id, monthly_limit_usd);
    }

    /// Deduct cost and check budget status. Resets if the month has rolled over.
    pub async fn deduct_and_check(
        &self,
        agent_id: &str,
        cost_usd: f64,
    ) -> BudgetCheckResult {
        let mut budgets = self.budgets.lock().await;
        let budget = match budgets.get_mut(agent_id) {
            Some(b) => b,
            None => return BudgetCheckResult::Normal,
        };

        // Month rollover
        let current = current_month_key();
        if budget.month_key != current {
            info!("budget: month rollover for {} ({} -> {})", agent_id, budget.month_key, current);
            budget.month_key = current;
            budget.spent_this_month_usd = 0.0;
        }

        budget.spent_this_month_usd += cost_usd;
        let pct = (budget.spent_this_month_usd / budget.monthly_limit_usd) * 100.0;

        if pct >= 100.0 {
            let reason = format!(
                "budget exceeded: ${:.4} / ${:.2} ({:.1}%)",
                budget.spent_this_month_usd, budget.monthly_limit_usd, pct
            );
            warn!("budget: {} — {}", agent_id, reason);

            // Create hard incident
            let incident = BudgetIncident {
                id: format!("inc-{}-{}", agent_id, Utc::now().timestamp_millis()),
                agent_id: agent_id.to_string(),
                threshold_type: ThresholdType::Hard,
                amount_limit: budget.monthly_limit_usd,
                amount_observed: budget.spent_this_month_usd,
                status: IncidentStatus::Open,
                created_at: Utc::now().to_rfc3339(),
                resolved_at: None,
            };

            // Drop budgets lock before acquiring incidents lock
            let agent_id_owned = agent_id.to_string();
            let reason_clone = reason.clone();
            drop(budgets);

            let mut incidents = self.incidents.lock().await;
            // Only create if no open hard incident exists
            let has_open = incidents.iter().any(|i| {
                i.agent_id == agent_id_owned
                    && matches!(i.threshold_type, ThresholdType::Hard)
                    && i.status == IncidentStatus::Open
            });
            if !has_open {
                incidents.push(incident);
            }

            BudgetCheckResult::Paused { reason: reason_clone }
        } else if pct >= 80.0 {
            warn!("budget: {} at {:.1}% of monthly limit", agent_id, pct);

            let agent_id_owned = agent_id.to_string();
            drop(budgets);

            // Create soft incident
            let mut incidents = self.incidents.lock().await;
            let has_open = incidents.iter().any(|i| {
                i.agent_id == agent_id_owned
                    && matches!(i.threshold_type, ThresholdType::Soft)
                    && i.status == IncidentStatus::Open
            });
            if !has_open {
                incidents.push(BudgetIncident {
                    id: format!("inc-{}-{}", agent_id_owned, Utc::now().timestamp_millis()),
                    agent_id: agent_id_owned,
                    threshold_type: ThresholdType::Soft,
                    amount_limit: 0.0, // not applicable for soft
                    amount_observed: 0.0,
                    status: IncidentStatus::Open,
                    created_at: Utc::now().to_rfc3339(),
                    resolved_at: None,
                });
            }

            BudgetCheckResult::Warning { pct }
        } else {
            BudgetCheckResult::Normal
        }
    }

    /// Override an agent's monthly limit. Resolves all open incidents for the agent.
    pub async fn override_budget(&self, agent_id: &str, new_limit_usd: f64) {
        {
            let mut budgets = self.budgets.lock().await;
            if let Some(budget) = budgets.get_mut(agent_id) {
                budget.monthly_limit_usd = new_limit_usd;
                info!("budget: {} limit overridden to ${:.2}", agent_id, new_limit_usd);
            }
        }

        // Resolve open incidents
        let mut incidents = self.incidents.lock().await;
        let now = Utc::now().to_rfc3339();
        for incident in incidents.iter_mut() {
            if incident.agent_id == agent_id && incident.status == IncidentStatus::Open {
                incident.status = IncidentStatus::Resolved;
                incident.resolved_at = Some(now.clone());
            }
        }
    }

    /// Get current budget status for an agent.
    pub async fn get_budget_status(&self, agent_id: &str) -> Option<AgentBudget> {
        let budgets = self.budgets.lock().await;
        budgets.get(agent_id).cloned()
    }

    /// Get all open incidents for an agent.
    pub async fn get_open_incidents(&self, agent_id: &str) -> Vec<BudgetIncident> {
        let incidents = self.incidents.lock().await;
        incidents
            .iter()
            .filter(|i| i.agent_id == agent_id && i.status == IncidentStatus::Open)
            .cloned()
            .collect()
    }

    /// Persist current state to the JSON file.
    pub async fn persist(&self) -> Result<()> {
        let budgets = self.budgets.lock().await;
        let incidents = self.incidents.lock().await;

        let state = PersistedState {
            budgets: budgets.clone(),
            incidents: incidents.clone(),
        };

        let json = serde_json::to_string_pretty(&state)?;

        if let Some(parent) = self.state_file.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&self.state_file, json)?;
        debug!("budget: persisted state to {}", self.state_file.display());

        Ok(())
    }
}

fn current_month_key() -> String {
    Utc::now().format("%Y-%m").to_string()
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_state_file() -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("budget-test-{}.json", std::process::id()));
        p
    }

    #[tokio::test]
    async fn threshold_warning_at_80_pct() {
        let tracker = BudgetTracker::new(temp_state_file());
        tracker.init_agent("boot", 10.0).await;

        // Spend 8.5 of 10 => 85%
        let result = tracker.deduct_and_check("boot", 8.5).await;
        match result {
            BudgetCheckResult::Warning { pct } => assert!(pct >= 80.0),
            other => panic!("expected Warning, got {:?}", std::mem::discriminant(&other)),
        }
    }

    #[tokio::test]
    async fn hard_pause_at_100_pct() {
        let tracker = BudgetTracker::new(temp_state_file());
        tracker.init_agent("boot", 10.0).await;

        let result = tracker.deduct_and_check("boot", 10.5).await;
        assert!(matches!(result, BudgetCheckResult::Paused { .. }));
    }

    #[tokio::test]
    async fn month_rollover() {
        let path = temp_state_file();
        let tracker = BudgetTracker::new(path.clone());
        tracker.init_agent("boot", 10.0).await;

        // Manually set month_key to a past month
        {
            let mut budgets = tracker.budgets.lock().await;
            budgets.get_mut("boot").unwrap().month_key = "2025-01".to_string();
            budgets.get_mut("boot").unwrap().spent_this_month_usd = 9.0;
        }

        // Deducting should trigger rollover and reset spent
        let result = tracker.deduct_and_check("boot", 1.0).await;
        assert!(matches!(result, BudgetCheckResult::Normal));

        let status = tracker.get_budget_status("boot").await.unwrap();
        assert_eq!(status.spent_this_month_usd, 1.0);
        assert_eq!(status.month_key, current_month_key());

        let _ = std::fs::remove_file(&path);
    }

    #[tokio::test]
    async fn incident_lifecycle() {
        let tracker = BudgetTracker::new(temp_state_file());
        tracker.init_agent("boot", 10.0).await;

        // Trigger hard incident
        tracker.deduct_and_check("boot", 11.0).await;
        let incidents = tracker.get_open_incidents("boot").await;
        assert_eq!(incidents.len(), 1);
        assert!(matches!(incidents[0].threshold_type, ThresholdType::Hard));

        // Override resolves incidents
        tracker.override_budget("boot", 20.0).await;
        let incidents = tracker.get_open_incidents("boot").await;
        assert!(incidents.is_empty());
    }

    #[tokio::test]
    async fn persistence_round_trip() {
        let path = temp_state_file();

        // Write state
        {
            let tracker = BudgetTracker::new(path.clone());
            tracker.init_agent("boot", 50.0).await;
            tracker.deduct_and_check("boot", 5.0).await;
            tracker.persist().await.unwrap();
        }

        // Read state back
        {
            let tracker = BudgetTracker::new(path.clone());
            let status = tracker.get_budget_status("boot").await.unwrap();
            assert_eq!(status.monthly_limit_usd, 50.0);
            assert!((status.spent_this_month_usd - 5.0).abs() < f64::EPSILON);
        }

        let _ = std::fs::remove_file(&path);
    }
}
