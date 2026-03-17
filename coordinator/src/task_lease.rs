/// Atomic task checkout — ensures only one agent holds a task at a time.
/// Leases expire after a configurable TTL to prevent deadlocks from crashed agents.
use std::collections::HashMap;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tracing::debug;

// ============================================================================
// Types
// ============================================================================

#[derive(Debug, Clone)]
pub struct TaskLease {
    pub task_id: String,
    pub agent_id: String,
    pub claimed_at: Instant,
    pub ttl: Duration,
}

#[derive(Debug, Clone)]
pub enum LeaseError {
    AlreadyClaimed { holder: String },
}

impl std::fmt::Display for LeaseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AlreadyClaimed { holder } => {
                write!(f, "task already claimed by {}", holder)
            }
        }
    }
}

impl std::error::Error for LeaseError {}

// ============================================================================
// TaskLeaseManager
// ============================================================================

pub struct TaskLeaseManager {
    leases: Mutex<HashMap<String, TaskLease>>,
    default_ttl: Duration,
}

impl TaskLeaseManager {
    pub fn new(default_ttl: Duration) -> Self {
        Self {
            leases: Mutex::new(HashMap::new()),
            default_ttl,
        }
    }

    /// Attempt to claim a task for an agent. Fails if another agent holds it.
    pub async fn try_claim(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> {
        let mut leases = self.leases.lock().await;

        // Check for existing non-expired lease
        if let Some(existing) = leases.get(task_id) {
            if existing.claimed_at.elapsed() < existing.ttl {
                if existing.agent_id != agent_id {
                    return Err(LeaseError::AlreadyClaimed {
                        holder: existing.agent_id.clone(),
                    });
                }
                // Same agent re-claiming — refresh the lease
                debug!("task_lease: {} re-claimed by {}", task_id, agent_id);
            }
        }

        leases.insert(
            task_id.to_string(),
            TaskLease {
                task_id: task_id.to_string(),
                agent_id: agent_id.to_string(),
                claimed_at: Instant::now(),
                ttl: self.default_ttl,
            },
        );

        debug!("task_lease: {} claimed by {}", task_id, agent_id);
        Ok(())
    }

    /// Release a lease. Returns false if the agent doesn't hold it.
    pub async fn release_lease(&self, task_id: &str, agent_id: &str) -> bool {
        let mut leases = self.leases.lock().await;
        if let Some(existing) = leases.get(task_id) {
            if existing.agent_id == agent_id {
                leases.remove(task_id);
                debug!("task_lease: {} released by {}", task_id, agent_id);
                return true;
            }
        }
        false
    }

    /// Remove expired leases and return the freed task IDs.
    pub async fn cleanup_expired(&self) -> Vec<String> {
        let mut leases = self.leases.lock().await;
        let expired: Vec<String> = leases
            .iter()
            .filter(|(_, lease)| lease.claimed_at.elapsed() >= lease.ttl)
            .map(|(id, _)| id.clone())
            .collect();

        for id in &expired {
            debug!("task_lease: {} expired, removing", id);
            leases.remove(id);
        }

        expired
    }

    /// Check if a task is currently claimed (and not expired).
    pub async fn is_claimed(&self, task_id: &str) -> bool {
        let leases = self.leases.lock().await;
        if let Some(lease) = leases.get(task_id) {
            lease.claimed_at.elapsed() < lease.ttl
        } else {
            false
        }
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn claim_and_release() {
        let mgr = TaskLeaseManager::new(Duration::from_secs(300));

        mgr.try_claim("task-1", "boot").await.unwrap();
        assert!(mgr.is_claimed("task-1").await);

        assert!(mgr.release_lease("task-1", "boot").await);
        assert!(!mgr.is_claimed("task-1").await);
    }

    #[tokio::test]
    async fn double_claim_rejected() {
        let mgr = TaskLeaseManager::new(Duration::from_secs(300));

        mgr.try_claim("task-1", "boot").await.unwrap();
        let err = mgr.try_claim("task-1", "ig88").await.unwrap_err();

        match err {
            LeaseError::AlreadyClaimed { holder } => assert_eq!(holder, "boot"),
        }
    }

    #[tokio::test]
    async fn expiry_cleanup() {
        let mgr = TaskLeaseManager::new(Duration::from_millis(1));

        mgr.try_claim("task-1", "boot").await.unwrap();
        mgr.try_claim("task-2", "ig88").await.unwrap();

        // Wait for TTL to expire
        tokio::time::sleep(Duration::from_millis(10)).await;

        let freed = mgr.cleanup_expired().await;
        assert_eq!(freed.len(), 2);
        assert!(!mgr.is_claimed("task-1").await);
        assert!(!mgr.is_claimed("task-2").await);
    }

    #[tokio::test]
    async fn wrong_agent_release_fails() {
        let mgr = TaskLeaseManager::new(Duration::from_secs(300));

        mgr.try_claim("task-1", "boot").await.unwrap();
        assert!(!mgr.release_lease("task-1", "ig88").await);
        // Original holder still has it
        assert!(mgr.is_claimed("task-1").await);
    }

    #[tokio::test]
    async fn same_agent_reclaim_refreshes() {
        let mgr = TaskLeaseManager::new(Duration::from_secs(300));

        mgr.try_claim("task-1", "boot").await.unwrap();
        // Same agent re-claiming should succeed
        mgr.try_claim("task-1", "boot").await.unwrap();
        assert!(mgr.is_claimed("task-1").await);
    }
}
