/// Approval pipeline — analytics, HMAC signing, rate limiting, pending state.
/// Ported from approval-tracker.ts + matrix-coordinator.ts approval logic (BKX062/BKX063).
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::collections::{HashMap, VecDeque};
use std::fs;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::time::{SystemTime, UNIX_EPOCH};

type HmacSha256 = Hmac<Sha256>;

// ============================================================================
// Approval Analytics Ring Buffer (BKX062)
// ============================================================================

const MAX_RECORDS: usize = 500;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalDecision {
    Auto,
    MatrixApproved,
    MatrixDenied,
    TimedOut,
    RateLimited,
}

impl std::fmt::Display for ApprovalDecision {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Auto => write!(f, "auto"),
            Self::MatrixApproved => write!(f, "matrix_approved"),
            Self::MatrixDenied => write!(f, "matrix_denied"),
            Self::TimedOut => write!(f, "timed_out"),
            Self::RateLimited => write!(f, "rate_limited"),
        }
    }
}

// ============================================================================
// Typed Approval Gates (FCT007 Borrow #2)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalGateType {
    ToolCall,
    TradingExecution,
    AgentElevation,
    LoopSpecDeploy,
    BudgetOverride,
    LoopIteration,
    InfraChange,
}

impl ApprovalGateType {
    /// Timeout in milliseconds for this gate type.
    pub fn timeout_ms(&self) -> u64 {
        match self {
            Self::ToolCall => 60_000,
            Self::TradingExecution => 300_000,
            Self::AgentElevation => 3_600_000,
            Self::LoopSpecDeploy => 3_600_000,
            Self::BudgetOverride => 86_400_000,
            Self::LoopIteration => 300_000,
            Self::InfraChange => 3_600_000,
        }
    }

    /// Whether this gate type can be auto-approved.
    pub fn can_auto_approve(&self) -> bool {
        matches!(self, Self::ToolCall)
    }

    /// Whether this gate type blocks the agent until resolved.
    pub fn is_blocking(&self) -> bool {
        !matches!(self, Self::ToolCall)
    }

    /// Human-readable label for Matrix messages.
    pub fn label(&self) -> &'static str {
        match self {
            Self::ToolCall => "Tool Call",
            Self::TradingExecution => "Trading Execution",
            Self::AgentElevation => "Agent Elevation",
            Self::LoopSpecDeploy => "Loop Spec Deploy",
            Self::BudgetOverride => "Budget Override",
            Self::LoopIteration => "Loop Iteration",
            Self::InfraChange => "Infra Change",
        }
    }
}

impl std::fmt::Display for ApprovalGateType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.label())
    }
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct ApprovalRecord {
    pub agent_name: String,
    pub tool_name: String,
    pub room_id: String,
    pub decision: ApprovalDecision,
    pub requested_at: u64,
    pub resolved_at: u64,
    pub latency_ms: u64,
    pub gate_type: Option<ApprovalGateType>,
}

pub struct ApprovalTracker {
    records: VecDeque<ApprovalRecord>,
}

impl ApprovalTracker {
    pub fn new() -> Self {
        Self {
            records: VecDeque::with_capacity(MAX_RECORDS),
        }
    }

    pub fn record(&mut self, record: ApprovalRecord) {
        if self.records.len() >= MAX_RECORDS {
            self.records.pop_front();
        }
        self.records.push_back(record);
    }

}

// ============================================================================
// HMAC Signing (BKX063)
// ============================================================================

pub struct HmacSigner {
    secret: Vec<u8>,
}

impl HmacSigner {
    /// Load HMAC secret from file. If the file doesn't exist, generate a new
    /// 32-byte random secret and write it with mode 0600.
    pub fn load(secret_file: &str) -> anyhow::Result<Self> {
        let path = std::path::Path::new(secret_file);

        let hex_secret = if path.exists() {
            fs::read_to_string(path)?.trim().to_string()
        } else {
            // Generate 32 random bytes, hex-encode
            let mut bytes = [0u8; 32];
            getrandom(&mut bytes);
            let hex_str = hex::encode(bytes);

            // Ensure parent directory exists
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }

            // Write with mode 0o600
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(0o600)
                .open(path)?;
            file.write_all(hex_str.as_bytes())?;

            hex_str
        };

        let secret = hex::decode(&hex_secret)?;
        Ok(Self { secret })
    }

    /// Sign data with HMAC-SHA256, returning hex-encoded signature.
    pub fn sign(&self, data: &str) -> String {
        let mut mac =
            HmacSha256::new_from_slice(&self.secret).expect("HMAC can take key of any size");
        mac.update(data.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }

    /// Write an approval response file in the format `{decision}:{hex_sig}`.
    /// Data signed is `{request_id}|{decision}`.
    pub fn write_approval_response(
        &self,
        approval_dir: &str,
        request_id: &str,
        decision: &str,
    ) -> anyhow::Result<()> {
        let data = format!("{}|{}", request_id, decision);
        let sig = self.sign(&data);
        let path = format!("{}/{}.response", approval_dir, request_id);
        fs::write(&path, format!("{}:{}", decision, sig))?;
        Ok(())
    }
}

/// Fill buffer with random bytes using the rand crate.
fn getrandom(buf: &mut [u8]) {
    use rand::RngCore;
    rand::thread_rng().fill_bytes(buf);
}

// ============================================================================
// Rate Limiting (BKX062)
// ============================================================================

pub struct ApprovalRateLimiter {
    counts: HashMap<String, (u32, u64)>, // agent_name -> (count, window_start_ms)
    max: u32,
    window_ms: u64,
}

impl ApprovalRateLimiter {
    pub fn new(max: u32, window_ms: u64) -> Self {
        Self {
            counts: HashMap::new(),
            max,
            window_ms,
        }
    }

    /// Check if an agent is rate-limited. Returns true if rate limited.
    /// Increments the counter as a side effect.
    pub fn check_and_increment(&mut self, agent_name: &str) -> bool {
        let now = now_ms();
        let entry = self.counts.get_mut(agent_name);

        match entry {
            Some((count, window_start)) => {
                if now - *window_start > self.window_ms {
                    // Window expired, reset
                    *count = 1;
                    *window_start = now;
                    false
                } else {
                    *count += 1;
                    *count > self.max
                }
            }
            None => {
                self.counts.insert(agent_name.to_string(), (1, now));
                false
            }
        }
    }

    pub fn reset(&mut self, agent_name: &str) {
        self.counts.remove(agent_name);
    }
}

// ============================================================================
// Helpers
// ============================================================================

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gate_type_timeouts() {
        assert_eq!(ApprovalGateType::ToolCall.timeout_ms(), 60_000);
        assert_eq!(ApprovalGateType::TradingExecution.timeout_ms(), 300_000);
        assert_eq!(ApprovalGateType::AgentElevation.timeout_ms(), 3_600_000);
        assert_eq!(ApprovalGateType::LoopSpecDeploy.timeout_ms(), 3_600_000);
        assert_eq!(ApprovalGateType::BudgetOverride.timeout_ms(), 86_400_000);
        assert_eq!(ApprovalGateType::LoopIteration.timeout_ms(), 300_000);
        assert_eq!(ApprovalGateType::InfraChange.timeout_ms(), 3_600_000);
    }

    #[test]
    fn can_auto_approve_only_tool_call() {
        assert!(ApprovalGateType::ToolCall.can_auto_approve());
        assert!(!ApprovalGateType::TradingExecution.can_auto_approve());
        assert!(!ApprovalGateType::AgentElevation.can_auto_approve());
        assert!(!ApprovalGateType::LoopSpecDeploy.can_auto_approve());
        assert!(!ApprovalGateType::BudgetOverride.can_auto_approve());
        assert!(!ApprovalGateType::LoopIteration.can_auto_approve());
        assert!(!ApprovalGateType::InfraChange.can_auto_approve());
    }

    #[test]
    fn is_blocking_false_only_for_tool_call() {
        assert!(!ApprovalGateType::ToolCall.is_blocking());
        assert!(ApprovalGateType::TradingExecution.is_blocking());
        assert!(ApprovalGateType::AgentElevation.is_blocking());
        assert!(ApprovalGateType::LoopSpecDeploy.is_blocking());
        assert!(ApprovalGateType::BudgetOverride.is_blocking());
        assert!(ApprovalGateType::LoopIteration.is_blocking());
        assert!(ApprovalGateType::InfraChange.is_blocking());
    }

    #[test]
    fn gate_type_labels() {
        assert_eq!(ApprovalGateType::ToolCall.label(), "Tool Call");
        assert_eq!(ApprovalGateType::TradingExecution.label(), "Trading Execution");
        assert_eq!(ApprovalGateType::AgentElevation.label(), "Agent Elevation");
        assert_eq!(ApprovalGateType::LoopSpecDeploy.label(), "Loop Spec Deploy");
        assert_eq!(ApprovalGateType::BudgetOverride.label(), "Budget Override");
        assert_eq!(ApprovalGateType::LoopIteration.label(), "Loop Iteration");
        assert_eq!(ApprovalGateType::InfraChange.label(), "Infra Change");
        // Display trait uses label()
        assert_eq!(format!("{}", ApprovalGateType::ToolCall), "Tool Call");
    }
}
