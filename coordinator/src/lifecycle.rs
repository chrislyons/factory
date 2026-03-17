/// Agent lifecycle management: circuit breaker, trust levels, audit log.
/// Port of agent-lifecycle.ts (BKX042).
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use tracing::error;

use crate::health::IncidentType;

// ============================================================================
// Trust levels
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum TrustLevel {
    L1Observer = 1,
    L2Advisor = 2,
    L3Operator = 3,
    L4Autonomous = 4,
}

impl TrustLevel {
    pub fn from_u8(n: u8) -> Self {
        match n {
            1 => Self::L1Observer,
            2 => Self::L2Advisor,
            3 => Self::L3Operator,
            4 => Self::L4Autonomous,
            _ => Self::L2Advisor,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            Self::L1Observer => "L1_OBSERVER",
            Self::L2Advisor => "L2_ADVISOR",
            Self::L3Operator => "L3_OPERATOR",
            Self::L4Autonomous => "L4_AUTONOMOUS",
        }
    }
}

// ============================================================================
// Circuit breaker
// ============================================================================

#[derive(Debug, Clone, PartialEq)]
pub enum BreakerState {
    Closed,
    OpenPausing { pause_until_ms: u64 },
    OpenKilling { kill_scheduled_at_ms: u64 },
    HalfOpen,
}

#[derive(Debug, Clone)]
pub struct CircuitBreaker {
    pub state: BreakerState,
    pub transitioned_at_ms: u64,
    pub failure_count: u32,
    pub consecutive_timeouts: u32,
}

impl CircuitBreaker {
    fn new() -> Self {
        Self {
            state: BreakerState::Closed,
            transitioned_at_ms: now_ms(),
            failure_count: 0,
            consecutive_timeouts: 0,
        }
    }
}

// ============================================================================
// Trust change records
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct TrustChange {
    pub timestamp_ms: u64,
    pub agent_name: String,
    pub from_level: TrustLevel,
    pub to_level: TrustLevel,
    pub reason: String,
    pub approver: String,
    pub warning_issued_at_ms: Option<u64>,
}

// ============================================================================
// Trust override persistence (survives restarts)
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone, Serialize, Deserialize)]
struct TrustOverrideEntry {
    level: u8,
    reason: String,
    timestamp: String,
}

// ============================================================================
// AgentLifecycleManager
// ============================================================================

#[allow(dead_code)]
pub struct AgentLifecycleManager {
    audit_log_path: PathBuf,
    trust_history: Vec<TrustChange>,
    circuit_breakers: HashMap<String, CircuitBreaker>,
    breaker_threshold: u32,
    breaker_pause_ms: u64,
    degradation_warning_ms: u64,
}

#[allow(dead_code)]
impl AgentLifecycleManager {
    pub fn new(
        audit_log_dir: &str,
        breaker_threshold: u32,
        breaker_pause_ms: u64,
        degradation_warning_ms: u64,
    ) -> Self {
        let dir = PathBuf::from(audit_log_dir);
        let path = dir.join("agent-changes.log");

        let mut mgr = Self {
            audit_log_path: path,
            trust_history: Vec::new(),
            circuit_breakers: HashMap::new(),
            breaker_threshold,
            breaker_pause_ms,
            degradation_warning_ms,
        };

        mgr.ensure_audit_log();
        mgr.load_trust_history();
        mgr
    }

    pub fn with_defaults(audit_log_dir: &str) -> Self {
        Self::new(audit_log_dir, 3, 300_000, 300_000)
    }

    // ============================================================================
    // Audit log
    // ============================================================================

    fn ensure_audit_log(&self) {
        if let Some(parent) = self.audit_log_path.parent() {
            if let Err(e) = fs::create_dir_all(parent) {
                error!("Failed to create audit log dir: {}", e);
                return;
            }
            // Set directory permissions to 700 (owner only)
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(parent, fs::Permissions::from_mode(0o700));
            }
        }

        if !self.audit_log_path.exists() {
            if let Err(e) = fs::write(&self.audit_log_path, "") {
                error!("Failed to create audit log: {}", e);
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(
                    &self.audit_log_path,
                    fs::Permissions::from_mode(0o600),
                );
            }
        }
    }

    /// Append an audit event line: `ISO_TIMESTAMP | EVENT_TYPE | agent | k:v | k:v | by: approver`
    pub fn log_audit_event(
        &self,
        event_type: &str,
        agent_name: &str,
        details: &[(&str, &str)],
        approver: &str,
    ) {
        let now = chrono::Utc::now().to_rfc3339();
        let detail_str = details
            .iter()
            .map(|(k, v)| format!("{}: {}", k, v))
            .collect::<Vec<_>>()
            .join(" | ");

        let line = format!(
            "{} | {} | {} | {} | by: {}\n",
            now, event_type, agent_name, detail_str, approver
        );

        if let Ok(mut f) = fs::OpenOptions::new()
            .append(true)
            .create(true)
            .open(&self.audit_log_path)
        {
            let _ = f.write_all(line.as_bytes());
        }
    }

    fn load_trust_history(&mut self) {
        let content = match fs::read_to_string(&self.audit_log_path) {
            Ok(c) => c,
            Err(_) => return,
        };

        for line in content.lines() {
            let parts: Vec<&str> = line.split(" | ").collect();
            if parts.len() < 4 {
                continue;
            }
            let event_type = parts[1];
            if event_type == "DEGRADE" || event_type == "UPGRADE" {
                let agent_name = parts[2].to_string();
                // Parse "L3→L2" level transition from parts[3]
                if let Some(levels_part) = parts.get(3) {
                    let levels: Vec<&str> = levels_part.split('→').collect();
                    if levels.len() == 2 {
                        let from = parse_trust_level_str(levels[0]);
                        let to = parse_trust_level_str(levels[1]);
                        self.trust_history.push(TrustChange {
                            timestamp_ms: 0,
                            agent_name,
                            from_level: from,
                            to_level: to,
                            reason: parts.get(4).unwrap_or(&"").to_string(),
                            approver: parts.last().unwrap_or(&"system").to_string(),
                            warning_issued_at_ms: None,
                        });
                    }
                }
            }
        }
    }

    // ============================================================================
    // Trust level management
    // ============================================================================

    pub fn trust_override_path() -> PathBuf {
        let home = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(home).join(".config/ig88/trust-overrides.json")
    }

    pub fn save_trust_override(&self, agent_name: &str, level: TrustLevel, reason: &str) {
        let path = Self::trust_override_path();
        let mut overrides: HashMap<String, TrustOverrideEntry> = path
            .exists()
            .then(|| {
                fs::read_to_string(&path)
                    .ok()
                    .and_then(|s| serde_json::from_str(&s).ok())
            })
            .flatten()
            .unwrap_or_default();

        overrides.insert(
            agent_name.to_string(),
            TrustOverrideEntry {
                level: level as u8,
                reason: reason.to_string(),
                timestamp: chrono::Utc::now().to_rfc3339(),
            },
        );

        if let Ok(json) = serde_json::to_string_pretty(&overrides) {
            let _ = fs::write(&path, json);
        }
    }

    pub fn load_trust_overrides(&self) -> HashMap<String, TrustLevel> {
        let path = Self::trust_override_path();
        if !path.exists() {
            return HashMap::new();
        }
        let raw: HashMap<String, TrustOverrideEntry> = fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();

        raw.into_iter()
            .map(|(k, v)| (k, TrustLevel::from_u8(v.level)))
            .collect()
    }

    pub fn clear_trust_override(&self, agent_name: &str) {
        let path = Self::trust_override_path();
        if !path.exists() {
            return;
        }
        if let Ok(mut overrides) =
            fs::read_to_string(&path).and_then(|s| Ok(serde_json::from_str::<serde_json::Value>(&s)?))
        {
            if let Some(obj) = overrides.as_object_mut() {
                obj.remove(agent_name);
                if let Ok(json) = serde_json::to_string_pretty(&overrides) {
                    let _ = fs::write(&path, json);
                }
            }
        }
        self.log_audit_event(
            "OVERRIDE_CLEARED",
            agent_name,
            &[("reason", "manual recovery cleared trust override")],
            "system",
        );
    }

    /// Execute trust degradation immediately, log and persist.
    pub fn execute_degradation(
        &mut self,
        agent_name: &str,
        from_level: TrustLevel,
        to_level: TrustLevel,
        reason: &str,
        approver: &str,
    ) {
        self.trust_history.push(TrustChange {
            timestamp_ms: now_ms(),
            agent_name: agent_name.to_string(),
            from_level,
            to_level,
            reason: reason.to_string(),
            approver: approver.to_string(),
            warning_issued_at_ms: None,
        });

        self.log_audit_event(
            "DEGRADE",
            agent_name,
            &[
                ("fromLevel", from_level.name()),
                ("toLevel", to_level.name()),
                ("reason", reason),
            ],
            approver,
        );

        self.save_trust_override(agent_name, to_level, reason);
    }

    // ============================================================================
    // Circuit breaker
    // ============================================================================

    pub fn get_circuit_breaker(&mut self, agent_name: &str) -> &mut CircuitBreaker {
        self.circuit_breakers
            .entry(agent_name.to_string())
            .or_insert_with(CircuitBreaker::new)
    }

    /// Record a failure and return what action to take.
    pub fn record_failure(
        &mut self,
        agent_name: &str,
        incident_type: &IncidentType,
    ) -> BreakerAction {
        let threshold = self.breaker_threshold;
        let pause_ms = self.breaker_pause_ms;
        let breaker = self.get_circuit_breaker(agent_name);

        breaker.failure_count += 1;

        match incident_type {
            IncidentType::Timeout => {
                breaker.consecutive_timeouts += 1;
            }
            _ => {
                breaker.consecutive_timeouts = 0;
            }
        }

        if breaker.state == BreakerState::Closed
            && breaker.consecutive_timeouts >= threshold
        {
            let pause_until = now_ms() + pause_ms;
            breaker.state = BreakerState::OpenPausing { pause_until_ms: pause_until };
            breaker.transitioned_at_ms = now_ms();

            self.log_audit_event(
                "BREAKER_PAUSE",
                agent_name,
                &[
                    ("reason", &format!("{} consecutive timeouts", threshold)),
                ],
                "system",
            );
            return BreakerAction::Pause;
        }

        BreakerAction::None
    }

    /// Check and advance circuit breaker state based on elapsed time.
    pub fn tick_circuit_breaker(&mut self, agent_name: &str) -> BreakerAction {
        let breaker = match self.circuit_breakers.get_mut(agent_name) {
            Some(b) => b,
            None => return BreakerAction::None,
        };

        match breaker.state.clone() {
            BreakerState::OpenPausing { pause_until_ms } => {
                if now_ms() >= pause_until_ms {
                    breaker.state = BreakerState::OpenKilling {
                        kill_scheduled_at_ms: now_ms(),
                    };
                    return BreakerAction::Kill;
                }
                BreakerAction::None
            }
            BreakerState::OpenKilling { .. } => {
                // Transition to half-open after kill
                breaker.state = BreakerState::HalfOpen;
                breaker.transitioned_at_ms = now_ms();
                BreakerAction::HalfOpen
            }
            BreakerState::HalfOpen => {
                // Let a probe through
                BreakerAction::None
            }
            BreakerState::Closed => BreakerAction::None,
        }
    }

    pub fn reset_circuit_breaker(&mut self, agent_name: &str) {
        if let Some(breaker) = self.circuit_breakers.get_mut(agent_name) {
            breaker.state = BreakerState::Closed;
            breaker.failure_count = 0;
            breaker.consecutive_timeouts = 0;
            breaker.transitioned_at_ms = now_ms();
        }
    }
}

#[allow(dead_code)]
#[derive(Debug, PartialEq)]
pub enum BreakerAction {
    None,
    Pause,
    Kill,
    HalfOpen,
    Recover,
}

// ============================================================================
// Helpers
// ============================================================================

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn parse_trust_level_str(s: &str) -> TrustLevel {
    match s.trim() {
        "L1_OBSERVER" | "L1" => TrustLevel::L1Observer,
        "L2_ADVISOR" | "L2" => TrustLevel::L2Advisor,
        "L3_OPERATOR" | "L3" => TrustLevel::L3Operator,
        "L4_AUTONOMOUS" | "L4" => TrustLevel::L4Autonomous,
        _ => TrustLevel::L2Advisor,
    }
}
