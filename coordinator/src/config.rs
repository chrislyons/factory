/// Configuration types for agent-config.yaml deserialization.
/// Schema matches the YAML exactly — do not change field names without updating the YAML too.
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ============================================================================
// Top-level
// ============================================================================

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub settings: Settings,
    pub allowlist: Vec<String>,
    pub devices: HashMap<String, Device>,
    pub agents: HashMap<String, AgentConfig>,
    pub rooms: HashMap<String, Room>,
    #[serde(default)]
    pub budget: Option<HashMap<String, BudgetConfig>>,
}

// ============================================================================
// Budget (per-agent)
// ============================================================================

#[derive(Debug, Clone, Deserialize)]
pub struct BudgetConfig {
    pub monthly_limit_usd: f64,
    #[serde(default = "default_cost_per_invocation")]
    pub cost_per_invocation_usd: f64,
}

fn default_cost_per_invocation() -> f64 {
    0.05
}

// ============================================================================
// Settings
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct Settings {
    pub dm_policy: DmPolicy,
    pub group_policy: GroupPolicy,
    pub fallback_device: String,
    pub pantalaimon_url: Option<String>,
    pub graphiti_url: Option<String>,
    pub graphiti_token_env: Option<String>,
    pub credential_source: Option<CredentialSource>,
    pub credential_path: Option<String>,

    // Timeouts
    pub claude_timeout_ms: u64,
    pub ssh_timeout_ms: u64,
    pub approval_timeout_ms: u64,
    pub approval_owner: String,
    pub approval_dir: Option<String>,

    // Resource limits
    pub max_claude_sessions: usize,

    // Auto-approval patterns
    #[serde(default)]
    pub auto_approve_patterns: Vec<String>,
    #[serde(default)]
    pub always_require_approval: Vec<String>,
    #[serde(default)]
    pub trusted_ssh_hosts: Vec<String>,

    // Multi-agent stagger (BKX027)
    pub multi_agent_stagger_ms: u64,
    pub multi_agent_max_wait_ms: u64,
    pub multi_agent_post_signal_delay_ms: u64,
    pub multi_agent_context_char_limit: usize,

    // LLM failover
    #[serde(default)]
    pub llm_providers: Vec<LLMProviderConfig>,
    pub llm_health_check_interval_ms: Option<u64>,
    pub llm_health_check_timeout_ms: Option<u64>,

    // Agent lifecycle (BKX042)
    pub health_score_window_ms: Option<u64>,
    pub breaker_consecutive_timeout_threshold: Option<u32>,
    pub breaker_pause_duration_ms: Option<u64>,
    pub degradation_warning_ms: Option<u64>,
    pub degradation_tool_rejection_threshold: Option<u32>,
    pub degradation_timeout_threshold: Option<u32>,

    // Delegate sessions (BKX036)
    pub delegate_timeout_ms: u64,
    pub delegate_device: String,
    #[serde(default)]
    pub delegate_auto_approve_tools: Vec<String>,
    #[serde(default)]
    pub delegate_auto_approve_bash: Vec<String>,
    #[serde(default)]
    pub delegate_require_approval_bash: Vec<String>,

    // Agent timers
    pub timer_dir: Option<String>,
    pub timer_check_interval_ms: Option<u64>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum DmPolicy {
    Respond,
    Pairing,
    Allowlist,
    Disabled,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum GroupPolicy {
    Mention,
    Allowlist,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CredentialSource {
    Age,
    Systemd,
    Gpg,
    Env,
}

// ============================================================================
// LLM Providers
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct LLMProviderConfig {
    pub name: String,
    pub cli: String,
    pub model: String,
    pub fallback_model: String,
    pub health_url: String,
    #[serde(default)]
    pub env: HashMap<String, String>,
}

// ============================================================================
// Devices
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct Device {
    #[serde(rename = "type")]
    pub device_type: DeviceType,
    pub tailscale_ip: Option<String>,
    pub ssh_alias: Option<String>,
    pub tmux_socket: Option<String>,
    pub api_base: Option<String>,
    #[serde(default)]
    pub models: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum DeviceType {
    Local,
    Remote,
    Cloud,
}

// ============================================================================
// Agents
// ============================================================================

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ContextMode {
    Fat,
    Thin,
}

impl Default for ContextMode {
    fn default() -> Self {
        Self::Fat
    }
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct AgentConfig {
    pub matrix_user: String,
    pub token_file: String,
    pub description: String,
    pub sandbox_profile: SandboxProfile,
    pub default_device: String,
    pub trust_level: Option<u8>,
    #[serde(default)]
    pub trust_domains: Vec<String>,
    #[serde(default)]
    pub ssh_dispatch: Vec<String>,
    pub system_prompt: Option<String>,
    pub identity_files: Option<IdentityFiles>,
    #[serde(default)]
    pub mention_aliases: Vec<String>,
    pub default_cwd: Option<String>,
    #[serde(default)]
    pub context_mode: ContextMode,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum SandboxProfile {
    Personal,
    Work,
    Restricted,
}

#[derive(Debug, Clone, Deserialize)]
pub struct IdentityFiles {
    pub soul: String,
    pub principles: String,
    pub agents: String,
}

// ============================================================================
// Rooms
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
pub struct Room {
    pub name: String,
    pub prefix: Option<String>,
    pub default_agent: Option<String>,
    #[serde(default)]
    pub agents: Vec<String>,
    #[serde(default)]
    pub all_agents_listen: bool,
    pub graphiti_group: Option<String>,
    pub sandbox_profile: SandboxProfile,
    pub worker_cwd: Option<String>,
    pub tmux_session: Option<String>,
    #[serde(default)]
    pub require_mention: bool,
    pub approval_delegate: Option<String>,
}

// ============================================================================
// Matrix event types (shared across matrix.rs and coordinator.rs)
// ============================================================================

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SyncResponse {
    pub next_batch: String,
    #[serde(default)]
    pub rooms: SyncRooms,
}

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct SyncRooms {
    #[serde(default)]
    pub join: HashMap<String, JoinedRoom>,
    #[serde(default)]
    pub leave: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JoinedRoom {
    pub timeline: Option<Timeline>,
    pub state: Option<StateEvents>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Timeline {
    #[serde(default)]
    pub events: Vec<MatrixEvent>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct StateEvents {
    #[serde(default)]
    pub events: Vec<MatrixStateEvent>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MatrixEvent {
    #[serde(rename = "type")]
    pub event_type: String,
    pub sender: String,
    pub event_id: String,
    pub content: serde_json::Value,
    pub origin_server_ts: Option<u64>,
    pub room_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MatrixStateEvent {
    #[serde(rename = "type")]
    pub event_type: String,
    pub state_key: String,
    pub content: serde_json::Value,
    pub sender: String,
    pub event_id: String,
    pub origin_server_ts: Option<u64>,
}

// ============================================================================
// Claude stream-json types
// ============================================================================

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "type")]
pub enum ClaudeResponse {
    #[serde(rename = "system")]
    System(ClaudeSystemMessage),
    #[serde(rename = "assistant")]
    Assistant(ClaudeAssistantMessage),
    #[serde(rename = "result")]
    Result(ClaudeResultMessage),
    #[serde(rename = "input_request")]
    InputRequest(ClaudeInputRequest),
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeSystemMessage {
    pub subtype: String,
    pub session_id: Option<String>,
    pub model: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeAssistantMessage {
    pub message: ClaudeMessageContent,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeMessageContent {
    #[serde(default)]
    pub content: Vec<ClaudeContentBlock>,
    pub usage: Option<ClaudeUsage>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeContentBlock {
    #[serde(rename = "type")]
    pub block_type: String,
    pub text: Option<String>,
    pub name: Option<String>,
    pub input: Option<serde_json::Value>,
    pub id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeUsage {
    pub input_tokens: u64,
    pub output_tokens: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeResultMessage {
    pub subtype: String,
    pub result: Option<String>,
    pub error: Option<String>,
    pub total_cost_usd: Option<f64>,
    pub usage: Option<ClaudeUsage>,
    pub session_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClaudeInputRequest {
    pub request_id: String,
    pub tool_name: Option<String>,
    pub tool_input: Option<serde_json::Value>,
}

// ============================================================================
// Config loading
// ============================================================================

pub fn load(path: &std::path::Path) -> Result<Config> {
    let content = std::fs::read_to_string(path)
        .with_context(|| format!("Failed to read config: {}", path.display()))?;

    let mut config: Config = serde_yaml::from_str(&content)
        .with_context(|| format!("Failed to parse config YAML: {}", path.display()))?;

    expand_paths(&mut config);

    Ok(config)
}

/// Expand ${HOME} and ~ in token_file and worker_cwd fields.
fn expand_paths(config: &mut Config) {
    let home = std::env::var("HOME").unwrap_or_default();

    for agent in config.agents.values_mut() {
        agent.token_file = agent.token_file.replace("${HOME}", &home);
        agent.token_file = expand_tilde(&agent.token_file, &home);
    }

    for room in config.rooms.values_mut() {
        if let Some(ref cwd) = room.worker_cwd.clone() {
            room.worker_cwd = Some(expand_tilde(cwd, &home));
        }
    }

    for agent in config.agents.values_mut() {
        if let Some(ref dcwd) = agent.default_cwd.clone() {
            agent.default_cwd = Some(expand_tilde(dcwd, &home));
        }
    }

    if let Some(ref dir) = config.settings.timer_dir.clone() {
        config.settings.timer_dir = Some(expand_tilde(dir, &home));
    }
}

fn expand_tilde(s: &str, home: &str) -> String {
    if s == "~" {
        home.to_string()
    } else if let Some(rest) = s.strip_prefix("~/") {
        format!("{}/{}", home, rest)
    } else {
        s.to_string()
    }
}

/// Read a Matrix access token from a file. Trims whitespace.
pub fn read_token(token_file: &str) -> Result<String> {
    std::fs::read_to_string(token_file)
        .with_context(|| format!("Failed to read token file: {}", token_file))
        .map(|s| s.trim().to_string())
}

/// Read identity file content (soul, principles, agents) for system prompt construction.
pub fn read_identity(base_dir: &std::path::Path, relative_path: &str) -> Result<String> {
    let full = base_dir.join(relative_path);
    std::fs::read_to_string(&full)
        .with_context(|| format!("Failed to read identity file: {}", full.display()))
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_mode_defaults_to_fat() {
        let mode = ContextMode::default();
        assert_eq!(mode, ContextMode::Fat);
    }
}
