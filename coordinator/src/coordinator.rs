/// Main coordinator loop — polls Matrix sync, routes messages to agents, handles approvals.
/// Phase 2: full approval workflow, circuit breaker enforcement, command handling,
/// relay loop output dedup, sendMessage retry, startup message.
/// Phase 3: delegate sessions, timers, status HUD.
use anyhow::{Context, Result};
use regex::Regex;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet, VecDeque};
use std::path::PathBuf;
use std::time::Instant;
use tokio::sync::broadcast;
use tokio::time::{interval, Duration};
use tracing::{debug, error, info, warn};

use crate::agent::{
    self, build_system_prompt, resolve_working_dir, send_to_agent, AgentSession,
};
use crate::approval::{
    ApprovalDecision, ApprovalRateLimiter, ApprovalRecord, ApprovalTracker, HmacSigner,
};
use crate::loop_engine::LoopManager;
use crate::run_events::{EventLevel, EventStream, RunEventLog, RunEventType};
use crate::budget::BudgetTracker;
use crate::runtime_state::RuntimeStateManager;
use crate::task_lease::TaskLeaseManager;
use crate::config::{self, Config, MatrixEvent};
use crate::delegate;
use crate::health::IncidentType;
use crate::infra::InfraChecker;
use crate::lifecycle::{AgentLifecycleManager, BreakerAction, TrustLevel};
use crate::matrix::{MatrixClient, Mentions, SyncTokenStore};
use crate::memory;
use crate::timer;

// ============================================================================
// Constants
// ============================================================================

const POLL_INTERVAL_MS: u64 = 3_000;
const DEDUP_BUFFER_SIZE: usize = 200;
const APPROVAL_RATE_LIMIT_MAX: u32 = 5;
const APPROVAL_RATE_LIMIT_WINDOW_MS: u64 = 60_000;
const STATUS_ROOM_ID: &str = "!jPovIiHiRrKTQWCOrp:matrix.org";
/// Coordinator-owned room where all agent approval requests are posted.
const COORD_APPROVAL_ROOM: &str = "!vTNmcZzRgfeFzMEzLc:matrix.org";
/// Approval timeout sweep interval.
const APPROVAL_SWEEP_INTERVAL_MS: u64 = 60_000;
/// Max agent output hashes to track per room (for relay loop output dedup).
const OUTPUT_DEDUP_BUFFER_SIZE: usize = 20;
/// Window within which duplicate agent output is suppressed.
const OUTPUT_DEDUP_WINDOW_SECS: u64 = 60;
/// Typing indicator timeout in ms.
const TYPING_TIMEOUT_MS: u64 = 30_000;

/// Shell metacharacter pattern — commands with these are never auto-approved.
const SHELL_METACHARS: &str = r"[|><;&`$()]|\.\.";

// Phase 3 constants
/// Status HUD update interval (60 seconds).
const HUD_UPDATE_INTERVAL_SECS: u64 = 60;
/// Infrastructure health check interval (5 minutes).
const INFRA_CHECK_INTERVAL_SECS: u64 = 300;
/// Identity drift check interval (5 minutes).
const IDENTITY_DRIFT_INTERVAL_SECS: u64 = 300;
/// Timer check interval (10 seconds).
const TIMER_CHECK_INTERVAL_SECS: u64 = 10;
/// LLM health check default interval (60 seconds).
const LLM_HEALTH_CHECK_INTERVAL_SECS: u64 = 60;
/// Max inter-agent routing hops per conversation.
const MAX_ROUTING_HOPS: u8 = 8;
/// Filesystem approval scan interval (3 seconds — matches hook poll cadence).
const FS_APPROVAL_SCAN_INTERVAL_SECS: u64 = 3;

/// MCP tools that are always auto-approved (read-only).
const AUTO_APPROVE_TOOLS: &[&str] = &[
    "mcp__qdrant__qdrant-find",
    "mcp__qdrant-mcp__qdrant_search",
    "mcp__graphiti__search_memory_facts",
    "mcp__graphiti__get_entity_edge",
    "mcp__graphiti__search_nodes",
    "mcp__graphiti__get_episodes",
    "mcp__graphiti__get_status",
    "mcp__matrix-boot__list-joined-rooms",
    "mcp__matrix-boot__get-room-info",
    "mcp__matrix-boot__get-room-members",
    "mcp__matrix-boot__get-room-messages",
    "mcp__matrix-boot__get-messages-by-date",
    "mcp__matrix-boot__get-direct-messages",
    "mcp__matrix-boot__get-notification-counts",
    "mcp__matrix-boot__get-user-profile",
    "mcp__matrix-boot__get-my-profile",
    "mcp__matrix-boot__identify-active-users",
    "mcp__matrix-boot__search-public-rooms",
    "mcp__matrix-boot__get-all-users",
    "mcp__matrix-boot__get-reactions",
    "mcp__matrix-boot__get-account-data",
    "mcp__research-mcp__qdrant_search",
    // IG-88 trading tools -- read-only market data (jupiter_swap stays OUT)
    "mcp__jupiter__jupiter_price",
    "mcp__jupiter__jupiter_quote",
    "mcp__jupiter__jupiter_portfolio",
    "mcp__dexscreener__dex_token_info",
    "mcp__dexscreener__dex_token_pairs",
    "mcp__dexscreener__dex_search",
    "mcp__dexscreener__dex_trending",
    "Read",
    "Glob",
    "Grep",
];

/// Parsed message content from a Matrix event.
enum MessageContent {
    Text {
        body: String,
        /// HTML formatted body (may contain Matrix mention pills with matrix.to links)
        formatted_body: Option<String>,
    },
    Image {
        mxc_url: String,
        mimetype: String,
        body: String,
    },
}

// ============================================================================
// State machine
// ============================================================================

/// A pending Matrix approval — posted as a message, awaiting reaction.
#[derive(Debug, Clone)]
struct PendingMatrixApproval {
    /// Room ID where the approval was posted
    room_id: String,
    agent_name: String,
    request_id: String,
    tool_name: String,
    created_at: Instant,
    /// If this approval came from a filesystem hook (not stream-json channel)
    fs_approval: bool,
    /// Thread ID of the agent turn that triggered this approval (e.g. "f3g8s")
    thread_id: String,
    /// Typed gate for this approval (FCT007 Borrow #2)
    gate_type: crate::approval::ApprovalGateType,
    /// HMAC tag embedded in the approval message for integrity verification
    hmac_tag: String,
}

/// Generate a 5-char human-readable thread ID from current time microseconds.
/// Uses an unambiguous alphabet (no i/l/o/0/1) to avoid visual confusion.
fn generate_thread_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_micros())
        .unwrap_or(0);
    const ALPHA: &[u8] = b"abcdefghjkmnpqrstuvwxyz23456789";
    let mut n = micros as usize;
    let mut id = String::with_capacity(5);
    for _ in 0..5 {
        let idx = n % ALPHA.len();
        id.push(*ALPHA.get(idx).unwrap_or(&b'x') as char);
        n /= ALPHA.len();
    }
    id
}

/// Returns true if the text looks like a CLI auth/init error that should
/// never be relayed to Matrix rooms.
fn is_suppressed_error(text: &str) -> bool {
    let lower = text.to_lowercase();
    lower.contains("invalid api key")
        || lower.contains("invalid_api_key")
        || lower.contains("authentication_error")
        || lower.contains("fix external api key")
        || (lower.contains("401") && lower.contains("unauthorized"))
}

/// Check if an inference error is retriable (provider-level, not agent-level).
/// These errors indicate the LLM provider is down or rate-limited, not that
/// the agent's request was malformed.
fn is_retriable_inference_error(text: &str) -> bool {
    let lower = text.to_lowercase();
    lower.contains("timed out")
        || lower.contains("rate limit")
        || lower.contains("overloaded")
        || lower.contains("503 service")
        || lower.contains("529")
        || lower.contains("capacity")
        || lower.contains("model_not_available")
        || lower.contains("server error")
}

/// Agent output hash entry for relay loop output dedup.
#[derive(Debug, Clone)]
struct OutputHashEntry {
    hash: String,
    timestamp: Instant,
}

struct CoordinatorState {
    config: Config,
    sessions: HashMap<String, AgentSession>,
    sync_tokens: SyncTokenStore,
    /// Processed event IDs per room — dedup ring buffer
    processed_events: HashMap<String, VecDeque<String>>,
    /// DM room cache: room_id -> is_dm
    dm_room_cache: HashMap<String, bool>,
    /// Room name cache from state events
    room_names: HashMap<String, String>,
    /// Room encryption set
    room_encryption: HashSet<String>,
    /// Approval infrastructure
    approval_tracker: ApprovalTracker,
    approval_rate_limiter: ApprovalRateLimiter,
    hmac_signer: HmacSigner,
    /// Pending Matrix approvals awaiting reaction (keyed by thread root event_id)
    pending_matrix_approvals: HashMap<String, PendingMatrixApproval>,
    /// Lifecycle manager (circuit breaker, audit log, trust levels)
    lifecycle: AgentLifecycleManager,
    /// Shell metachar regex
    shell_metachar_re: Regex,
    /// Shutdown broadcast
    shutdown_tx: broadcast::Sender<()>,
    /// Coordinator's own Matrix token (for sending status messages as @coord)
    coord_token: Option<String>,
    /// Coordinator's Matrix user_id resolved via whoami() at startup.
    coord_user_id: Option<String>,
    /// Agent output hashes per room — relay loop output dedup
    agent_output_hashes: HashMap<String, VecDeque<OutputHashEntry>>,
    /// Last approval sweep timestamp
    last_approval_sweep: Instant,
    // Phase 3 state
    /// Status HUD event ID (for edit_message updates)
    status_hud_event_id: Option<String>,
    /// Last HUD update timestamp
    last_hud_update: Instant,
    /// Infrastructure health checker with flap suppression
    infra_checker: InfraChecker,
    /// Last infra health check timestamp
    last_infra_check: Instant,
    /// Cached infra health for HUD display
    last_infra_health: Option<crate::infra::InfraHealth>,
    /// Identity file hashes (agent_name:file -> sha256)
    identity_hashes: HashMap<String, String>,
    /// Last identity drift check timestamp
    last_identity_check: Instant,
    /// Last timer check timestamp
    last_timer_check: Instant,
    /// Provider failover chain (ordered failover with health tracking)
    provider_chain: crate::provider_chain::ProviderChain,
    /// Last LLM health check timestamp
    last_llm_health_check: Instant,
    /// Inter-agent routing hop counts (keyed by original event_id)
    routing_hop_counts: HashMap<String, u8>,
    /// Memory write rate limiter
    memory_rate_limiter: memory::MemoryRateLimiter,
    /// Filesystem approval directory path
    approval_dir: String,
    /// Last filesystem approval scan timestamp
    last_fs_approval_scan: Instant,
    /// Sync token for the coordinator's own Matrix account (for approval room reactions).
    coord_sync_token: Option<String>,
    /// Loop engine manager (autoscope — FCT009)
    loop_manager: LoopManager,
    /// Per-agent budget tracking with soft/hard thresholds
    budget_tracker: BudgetTracker,
    /// Cumulative runtime state per agent
    runtime_state: RuntimeStateManager,
    /// Heartbeat event log for run observability
    run_event_log: RunEventLog,
    /// Atomic task checkout with TTL leases
    task_lease: TaskLeaseManager,
    /// Slash command rate limiter (per-user)
    command_rate_limiter: ApprovalRateLimiter,
    /// Consecutive sync failures across all agents — used to detect network outages
    sync_consecutive_failures: u32,
    /// Timestamp of last successful sync (any agent)
    last_sync_success: Instant,
    /// Per-agent suppressed error counts during network degradation (agent -> count)
    suppressed_error_counts: HashMap<String, u32>,
}

impl CoordinatorState {
    fn new(config: Config, shutdown_tx: broadcast::Sender<()>) -> Result<Self> {
        let home = std::env::var("HOME").unwrap_or_default();
        let audit_dir = format!("{}/.claude/audit", home);
        let state_dir = format!("{}/.config/ig88", home);

        let hmac_signer = HmacSigner::load(&format!("{}/.approval_hmac_secret", state_dir))
            .context("HMAC signer is required — ensure ~/.config/ig88/.approval_hmac_secret exists")?;

        let approval_dir = config.settings.approval_dir.clone()
            .unwrap_or_else(|| format!("{}/.config/ig88/approvals", home));
        // Ensure approval directory exists
        if let Err(e) = std::fs::create_dir_all(&approval_dir) {
            warn!("Failed to create approval dir {}: {}", approval_dir, e);
        }

        let lifecycle = AgentLifecycleManager::new(
            &audit_dir,
            config.settings.breaker_consecutive_timeout_threshold.unwrap_or(3),
            config.settings.breaker_pause_duration_ms.unwrap_or(300_000),
            config.settings.degradation_warning_ms.unwrap_or(300_000),
        );

        // Load coord token (env-only, no plaintext file fallback)
        let coord_token = std::env::var("MATRIX_TOKEN_PAN_COORD").ok();

        let infra_checker = InfraChecker::new(&config.settings);

        // Build provider chain before moving config into Self
        let provider_chain = {
            let providers = config.settings.llm_providers.clone();
            if providers.is_empty() {
                crate::provider_chain::ProviderChain::new(vec![
                    crate::config::LLMProviderConfig {
                        name: "anthropic".to_string(),
                        cli: "claude".to_string(),
                        model: "claude-haiku-4-5-20251001".to_string(),
                        fallback_model: "claude-sonnet-4-6".to_string(),
                        health_url: "https://api.anthropic.com/v1/messages".to_string(),
                        env: HashMap::new(),
                        timeout_ms: None,
                        retry_count: 1,
                        backoff_ms: 1000,
                        provider_type: crate::config::ProviderType::Cloud,
                    },
                ])
            } else {
                crate::provider_chain::ProviderChain::new(providers)
            }
        };

        Ok(Self {
            config,
            sessions: HashMap::new(),
            sync_tokens: SyncTokenStore::load(),
            processed_events: HashMap::new(),
            dm_room_cache: HashMap::new(),
            room_names: HashMap::new(),
            room_encryption: HashSet::new(),
            approval_tracker: ApprovalTracker::new(),
            approval_rate_limiter: ApprovalRateLimiter::new(
                APPROVAL_RATE_LIMIT_MAX,
                APPROVAL_RATE_LIMIT_WINDOW_MS,
            ),
            hmac_signer,
            pending_matrix_approvals: HashMap::new(),
            lifecycle,
            shell_metachar_re: Regex::new(SHELL_METACHARS).expect("valid regex"),
            shutdown_tx,
            coord_token,
            coord_user_id: None, // resolved async in init_agent_sessions
            agent_output_hashes: HashMap::new(),
            last_approval_sweep: Instant::now(),
            // Phase 3
            status_hud_event_id: None,
            last_hud_update: Instant::now(),
            infra_checker,
            last_infra_check: Instant::now(),
            last_infra_health: None,
            identity_hashes: HashMap::new(),
            last_identity_check: Instant::now(),
            last_timer_check: Instant::now(),
            provider_chain,
            last_llm_health_check: Instant::now(),
            routing_hop_counts: HashMap::new(),
            memory_rate_limiter: memory::MemoryRateLimiter::new(),
            approval_dir,
            last_fs_approval_scan: Instant::now(),
            coord_sync_token: None,
            loop_manager: LoopManager::new(),
            budget_tracker: BudgetTracker::new(PathBuf::from(format!("{}/budget.json", state_dir))),
            runtime_state: RuntimeStateManager::new(PathBuf::from(format!("{}/runtime-state.json", state_dir))),
            run_event_log: RunEventLog::new(PathBuf::from(format!("{}/runs", state_dir))),
            task_lease: TaskLeaseManager::new(std::time::Duration::from_secs(300)),
            command_rate_limiter: ApprovalRateLimiter::new(10, 60_000),
            sync_consecutive_failures: 0,
            last_sync_success: Instant::now(),
            suppressed_error_counts: HashMap::new(),
        })
    }

    /// Check if an event has already been processed (dedup).
    fn is_duplicate_event(&mut self, agent_name: &str, room_id: &str, event_id: &str) -> bool {
        let key = format!("{}:{}", agent_name, room_id);
        let buf = self.processed_events.entry(key).or_default();
        if buf.contains(&event_id.to_string()) {
            return true;
        }
        if buf.len() >= DEDUP_BUFFER_SIZE {
            buf.pop_front();
        }
        buf.push_back(event_id.to_string());
        false
    }

    /// Check if a user is on the allowlist.
    fn is_allowlisted(&self, user_id: &str) -> bool {
        self.config.allowlist.contains(&user_id.to_string())
    }

    /// Get message content from a Matrix event — supports m.text and m.image.
    fn get_message_content(event: &MatrixEvent) -> Option<MessageContent> {
        let content = &event.content;
        if event.event_type != "m.room.message" {
            return None;
        }
        let msgtype = content.get("msgtype")?.as_str()?;
        match msgtype {
            "m.text" => {
                let body = content.get("body")?.as_str()?.to_string();
                let formatted_body = content
                    .get("formatted_body")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                Some(MessageContent::Text { body, formatted_body })
            }
            "m.image" => {
                let mxc_url = content.get("url")?.as_str()?.to_string();
                let mimetype = content
                    .get("info")
                    .and_then(|i| i.get("mimetype"))
                    .and_then(|m| m.as_str())
                    .unwrap_or("image/jpeg")
                    .to_string();
                let body = content
                    .get("body")
                    .and_then(|b| b.as_str())
                    .unwrap_or("image")
                    .to_string();
                Some(MessageContent::Image { mxc_url, mimetype, body })
            }
            _ => None,
        }
    }

    /// Check if the event is coordinator-generated (avoid self-loops).
    fn is_coordinator_generated(event: &MatrixEvent) -> bool {
        event
            .content
            .get("dev.ig88.coordinator_generated")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }

    /// Determine which agents should receive a message in this room.
    fn get_agents_for_room<'a>(
        &'a self,
        room_id: &str,
        body: &str,
        formatted_body: Option<&str>,
        is_dm: bool,
    ) -> Vec<&'a str> {
        let room_config = match self.config.rooms.get(room_id) {
            Some(r) => r,
            None => {
                // Unknown room — DM mode check
                if is_dm {
                    return self.get_dm_agent(room_id);
                }
                return vec![];
            }
        };

        let mut agents: Vec<&str> = Vec::new();

        // Default agent
        if let Some(ref default_agent) = room_config.default_agent {
            // require_mention check
            let agent_cfg = self.config.agents.get(default_agent.as_str());
            let aliases = agent_cfg.map(|a| a.mention_aliases.as_slice()).unwrap_or(&[]);
            let matrix_user = agent_cfg.map(|a| a.matrix_user.as_str()).unwrap_or("");
            if !room_config.require_mention
                || agent_is_mentioned(body, formatted_body, default_agent, matrix_user, aliases)
                || is_dm
            {
                agents.push(default_agent.as_str());
            }
        }

        // Additional agents — only if @mentioned or all_agents_listen
        for agent_name in &room_config.agents {
            if agents.contains(&agent_name.as_str()) {
                continue;
            }
            let agent_cfg = self.config.agents.get(agent_name.as_str());
            let aliases = agent_cfg.map(|a| a.mention_aliases.as_slice()).unwrap_or(&[]);
            let matrix_user = agent_cfg.map(|a| a.matrix_user.as_str()).unwrap_or("");
            if room_config.all_agents_listen
                || agent_is_mentioned(body, formatted_body, agent_name, matrix_user, aliases)
            {
                agents.push(agent_name.as_str());
            }
        }

        agents
    }

    fn get_dm_agent<'b>(&'b self, _room_id: &str) -> Vec<&'b str> {
        // All agents handle their own DMs — the sync loop filter
        // (line ~1067) ensures only the owning agent processes each event.
        self.config.agents.keys().map(|k| k.as_str()).collect()
    }
}

/// Case-insensitive mention check: matches `@agent_name` or any `@alias` in body,
/// OR a Matrix mention pill (matrix.to link) in formatted_body pointing at matrix_user.
fn agent_is_mentioned(
    body: &str,
    formatted_body: Option<&str>,
    agent_name: &str,
    matrix_user: &str,
    aliases: &[String],
) -> bool {
    let body_lower = body.to_lowercase();
    if body_lower.contains(&format!("@{}", agent_name.to_lowercase())) {
        return true;
    }
    if aliases
        .iter()
        .any(|a| body_lower.contains(&format!("@{}", a.to_lowercase())))
    {
        return true;
    }
    // Check formatted_body for Element mention pills — these contain a
    // matrix.to link like: <a href="https://matrix.to/#/@boot.industries:matrix.org">
    if let Some(fb) = formatted_body {
        if !matrix_user.is_empty() {
            let fb_lower = fb.to_lowercase();
            let matrix_user_lower = matrix_user.to_lowercase();
            if fb_lower.contains(&format!("matrix.to/#/{}", matrix_user_lower)) {
                return true;
            }
        }
    }
    false
}

impl CoordinatorState {

    /// Check if agent output content is a duplicate of recent agent output in the same room.
    /// Returns true if the content hash matches a recent entry (within OUTPUT_DEDUP_WINDOW_SECS).
    fn is_duplicate_output(&mut self, room_id: &str, content: &str) -> bool {
        let hash = format!("{:x}", Sha256::digest(content.as_bytes()));
        let now = Instant::now();
        let cutoff = Duration::from_secs(OUTPUT_DEDUP_WINDOW_SECS);

        let buf = self
            .agent_output_hashes
            .entry(room_id.to_string())
            .or_default();

        // Prune old entries
        buf.retain(|e| now.duration_since(e.timestamp) < cutoff);

        // Check for duplicate
        if buf.iter().any(|e| e.hash == hash) {
            return true;
        }

        // Add entry
        if buf.len() >= OUTPUT_DEDUP_BUFFER_SIZE {
            buf.pop_front();
        }
        buf.push_back(OutputHashEntry {
            hash,
            timestamp: now,
        });
        false
    }

    /// Determine if auto-approval applies to this tool call.
    fn should_auto_approve(
        &self,
        tool_name: &str,
        tool_input: Option<&serde_json::Value>,
        trust_level: u8,
    ) -> bool {
        // L1 Observer: only read-only MCP tools
        if trust_level <= 1 {
            return AUTO_APPROVE_TOOLS.contains(&tool_name);
        }

        // Always auto-approve read-only MCP tools
        if AUTO_APPROVE_TOOLS.contains(&tool_name) {
            return true;
        }

        // For Bash commands, check auto_approve_patterns
        if tool_name == "Bash" {
            if let Some(cmd) = tool_input.and_then(|i| i.get("command")).and_then(|c| c.as_str())
            {
                // Never auto-approve commands with shell metacharacters
                if self.shell_metachar_re.is_match(cmd) {
                    return false;
                }
                // Check always_require_approval first (deny wins)
                for pattern in &self.config.settings.always_require_approval {
                    if glob_match(pattern, cmd) {
                        return false;
                    }
                }
                // Check auto_approve_patterns
                for pattern in &self.config.settings.auto_approve_patterns {
                    if glob_match(pattern, cmd) {
                        return true;
                    }
                }
            }
            return false;
        }

        // Edit/Write/Bash need explicit trust for L3+
        if trust_level >= 3 && matches!(tool_name, "Edit" | "Write" | "NotebookEdit") {
            return true;
        }

        false
    }
}

// ============================================================================
// Main entry point
// ============================================================================

pub async fn run() -> Result<()> {
    let config_path = std::env::var("CONFIG_PATH")
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            format!("{}/factory/coordinator/config/agent-config.yaml", home)
        });

    info!("Loading config from {}", config_path);
    let config = config::load(std::path::Path::new(&config_path))
        .with_context(|| format!("Failed to load config: {}", config_path))?;

    info!(
        "Loaded config: {} agents, {} rooms",
        config.agents.len(),
        config.rooms.len()
    );

    let (shutdown_tx, _shutdown_rx) = broadcast::channel::<()>(1);
    let shutdown_tx_clone = shutdown_tx.clone();

    // Set up signal handlers
    tokio::spawn(async move {
        wait_for_shutdown_signal().await;
        let _ = shutdown_tx_clone.send(());
    });

    let mut state = CoordinatorState::new(config, shutdown_tx.clone())?;

    // Initialize all agent sessions
    init_agent_sessions(&mut state).await?;

    // Send startup message to Status room
    send_startup_message(&state).await;

    // Main poll loop
    run_poll_loop(&mut state, shutdown_tx).await
}

// ============================================================================
// Agent initialization
// ============================================================================

async fn init_agent_sessions(state: &mut CoordinatorState) -> Result<()> {
    let home = std::env::var("HOME").unwrap_or_default();
    // Load session IDs saved during the previous clean shutdown for resume support.
    let saved_session_ids = load_saved_sessions(&home);
    if !saved_session_ids.is_empty() {
        info!("Loaded {} saved session IDs for --resume", saved_session_ids.len());
    }

    let agent_names: Vec<String> = state.config.agents.keys().cloned().collect();
    let saved_tokens: HashMap<String, String> = state
        .config
        .agents
        .keys()
        .filter_map(|name| {
            state
                .sync_tokens
                .get(name)
                .map(|t| (name.clone(), t.to_string()))
        })
        .collect();

    for agent_name in &agent_names {
        let agent_config = state.config.agents[agent_name].clone();
        let agent_base = PathBuf::from(
            agent_config.default_cwd.as_deref().unwrap_or(&home)
        );

        // Load Matrix token (env-only, no plaintext file fallback)
        let token = match config::read_token_env(&agent_config.token_env) {
            Ok(t) => t,
            Err(e) => {
                warn!("[{}] {}, skipping", agent_name, e);
                continue;
            }
        };

        // Get provider from failover chain (respects current active index)
        let provider = state.provider_chain.current().clone();

        // Build system prompt
        let system_prompt = build_system_prompt(agent_name, &agent_config, &agent_base);

        // Resolve working dir
        let working_dir = resolve_working_dir(agent_name, &state.config);

        // Resolve matrix user_id from token (lightweight whoami)
        let pantalaimon_url = state.config.settings.pantalaimon_url.as_deref();
        let temp_client = MatrixClient::new(pantalaimon_url, token.clone(), String::new())
            .context("Failed to build temp matrix client")?;
        let user_id = temp_client.whoami().await.unwrap_or_else(|_| agent_config.matrix_user.clone());

        let health_window_ms = state
            .config
            .settings
            .health_score_window_ms
            .unwrap_or(1_800_000);

        let resume_id = saved_session_ids.get(agent_name).cloned();
        if resume_id.is_some() {
            info!("[{}] Attempting session resume", agent_name);
        }

        // Log runtime selection
        if agent_config.runtime == crate::config::RuntimeType::Hermes {
            info!(
                "[{}] Runtime: Hermes (profile: {:?}, port: {:?})",
                agent_name, agent_config.hermes_profile, agent_config.hermes_port
            );
        }

        let shutdown_rx = state.shutdown_tx.subscribe();
        let console_enabled = state.config.settings.agent_console_enabled;
        let tmux_socket_dir = state.config.settings.agent_tmux_socket_dir.clone();
        let session = agent::start_agent_session(
            agent_name,
            agent_config,
            token,
            user_id,
            &provider,
            if system_prompt.is_empty() { None } else { Some(&system_prompt) },
            &working_dir,
            health_window_ms,
            shutdown_rx,
            resume_id,
            console_enabled,
            tmux_socket_dir,
        )
        .await
        .context(format!("Failed to start agent session for {}", agent_name))?;

        // Ensure memory dirs exist
        memory::ensure_memory_dirs(agent_name);

        // Restore sync token
        if let Some(token) = saved_tokens.get(agent_name) {
            let mut sess = session;
            sess.sync_token = Some(token.clone());
            state.sessions.insert(agent_name.clone(), sess);
        } else {
            state.sessions.insert(agent_name.clone(), session);
        }

        info!("[{}] Agent session initialized", agent_name);
    }

    // Resolve coordinator's Matrix user_id via whoami — required for startup.
    if let Some(ref coord_token) = state.coord_token.clone() {
        let pantalaimon_url = state.config.settings.pantalaimon_url.as_deref();
        let temp_client = MatrixClient::new(pantalaimon_url, coord_token.clone(), String::new())
            .context("Failed to build Matrix client for coord whoami")?;
        let uid = temp_client.whoami().await
            .context("Failed to resolve coord user_id via whoami — cannot start without coordinator identity")?;
        info!("Coordinator Matrix user_id: {}", uid);
        state.coord_user_id = Some(uid);
    }

    Ok(())
}

// ============================================================================
// Poll loop
// ============================================================================

async fn run_poll_loop(
    state: &mut CoordinatorState,
    shutdown_tx: broadcast::Sender<()>,
) -> Result<()> {
    let mut shutdown_rx = shutdown_tx.subscribe();
    let mut poll_ticker = interval(Duration::from_millis(POLL_INTERVAL_MS));

    info!("Coordinator poll loop started ({} agents)", state.sessions.len());

    loop {
        tokio::select! {
            _ = shutdown_rx.recv() => {
                info!("Shutdown signal received — saving state");
                save_agent_sessions(state);
                state.sync_tokens.save();
                break;
            }

            _ = poll_ticker.tick() => {
                poll_once(state).await;
            }
        }
    }

    info!("Coordinator exiting");
    Ok(())
}

/// Sync the coordinator's own Matrix account to catch reactions in COORD_APPROVAL_ROOM.
/// Agent tokens never see this room — only the coord account receives Chris's ✅/❌ reactions.
async fn sync_coord_approvals(state: &mut CoordinatorState) {
    let coord_token = match &state.coord_token {
        Some(t) => t.clone(),
        None => return, // No coord token at all — skip
    };
    // Use resolved user_id or fall back to the hardcoded string (same as process_pending_approvals)
    let coord_user_id = state.coord_user_id.clone()
        .unwrap_or_else(|| "@coord:matrix.org".to_string());

    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();

    let client = match MatrixClient::new(pantalaimon_url.as_deref(), coord_token, coord_user_id) {
        Ok(c) => c,
        Err(e) => {
            warn!("coord sync: failed to build client: {}", e);
            return;
        }
    };

    let since = state.coord_sync_token.clone();
    // timeout=0: non-blocking poll — return immediately with pending events.
    // Avoids blocking the 3s poll loop for 30s when the approval room is quiet.
    match client.sync(since.as_deref(), None, Some(0)).await {
        Err(e) => warn!("coord sync failed: {}", e),
        Ok(resp) => {
            state.coord_sync_token = Some(resp.next_batch.clone());

            // Only process reactions from COORD_APPROVAL_ROOM
            if let Some(room_data) = resp.rooms.join.get(COORD_APPROVAL_ROOM) {
                let events = room_data
                    .timeline
                    .as_ref()
                    .map(|t| t.events.clone())
                    .unwrap_or_default();

                // Skip backfill on first sync (no prior token)
                if since.is_none() {
                    debug!("coord sync: initial sync — skipping {} backfill events", events.len());
                    return;
                }

                for event in events {
                    if event.event_type == "m.reaction" {
                        // Dedup via coord namespace
                        if !state.is_duplicate_event("coord", COORD_APPROVAL_ROOM, &event.event_id) {
                            process_reaction(state, &event).await;
                        }
                    }
                }
            }
        }
    }
}

async fn poll_once(state: &mut CoordinatorState) {
    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();

    // Collect agent names to poll
    let agent_names: Vec<String> = state.sessions.keys().cloned().collect();

    for agent_name in agent_names {
        let session = match state.sessions.get_mut(&agent_name) {
            Some(s) => s,
            None => continue,
        };

        let token = session.matrix_token.clone();
        let since = session.sync_token.clone();
        let filter_id = session.sync_filter_id.clone();
        let user_id = session.matrix_user_id.clone();

        let matrix_client = match MatrixClient::new(pantalaimon_url.as_deref(), token, user_id) {
            Ok(c) => c,
            Err(e) => {
                error!("[{}] Failed to build Matrix client: {}", agent_name, e);
                continue;
            }
        };

        // Create sync filter if not yet created
        if session.sync_filter_id.is_none() {
            match matrix_client.create_sync_filter().await {
                Ok(fid) => {
                    info!("[{}] Created sync filter: {}", agent_name, fid);
                    session.sync_filter_id = Some(fid.clone());
                }
                Err(e) => {
                    warn!("[{}] Failed to create sync filter: {}", agent_name, e);
                }
            }
        }

        // Sync (long-poll, default 30s timeout)
        let sync_result = matrix_client.sync(since.as_deref(), filter_id.as_deref(), None).await;
        match sync_result {
            Err(e) => {
                state.sync_consecutive_failures += 1;
                // Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped)
                let backoff_secs = (1u64 << state.sync_consecutive_failures.min(4)) as u64;
                warn!("[{}] Sync failed (failure #{}, backoff {}s): {}", agent_name, state.sync_consecutive_failures, backoff_secs, e);
                tokio::time::sleep(Duration::from_secs(backoff_secs)).await;
                continue;
            }
            Ok(sync_resp) => {
                // Network recovered — reset degradation state and flush suppressed counts
                if state.sync_consecutive_failures > 0 {
                    info!("Network recovered after {} consecutive sync failures", state.sync_consecutive_failures);
                    state.sync_consecutive_failures = 0;
                }
                state.last_sync_success = Instant::now();
                // Update sync token
                let next_batch = sync_resp.next_batch.clone();
                let session = state.sessions.get_mut(&agent_name).unwrap();
                session.sync_token = Some(next_batch.clone());

                // Process state events (room names, encryption)
                for (room_id, room_data) in &sync_resp.rooms.join {
                    if let Some(ref state_evts) = room_data.state {
                        for evt in &state_evts.events {
                            if evt.event_type == "m.room.name" {
                                if let Some(name) = evt.content.get("name").and_then(|n| n.as_str()) {
                                    state.room_names.insert(room_id.clone(), name.to_string());
                                }
                            } else if evt.event_type == "m.room.encryption" {
                                state.room_encryption.insert(room_id.clone());
                            }
                        }
                    }
                }

                // Process timeline events
                for (room_id, room_data) in &sync_resp.rooms.join {
                    let events = room_data
                        .timeline
                        .as_ref()
                        .map(|t| t.events.clone())
                        .unwrap_or_default();

                    for event in events {
                        process_event(state, &agent_name, room_id, event, &matrix_client, since.is_none()).await;
                    }
                }

                // Save sync tokens periodically
                state.sync_tokens.set(&agent_name, next_batch);
            }
        }

        state.sync_tokens.maybe_save();
    }

    // Post pending approval requests to COORD_APPROVAL_ROOM first,
    // then sync the coord account to catch Chris's ✅/❌ reactions.
    process_pending_approvals(state).await;

    sync_coord_approvals(state).await;

    // Drain agent activity for verbose Matrix thread posts
    drain_agent_activity(state).await;

    // Scan filesystem approval requests from pretool hooks
    let now_fs = Instant::now();
    if now_fs.duration_since(state.last_fs_approval_scan).as_secs() >= FS_APPROVAL_SCAN_INTERVAL_SECS {
        state.last_fs_approval_scan = now_fs;
        scan_filesystem_approvals(state).await;
    }

    // Phase 3: periodic checks (counter-based, not separate timers)
    let now = Instant::now();

    // Timer check (every 10s)
    if now.duration_since(state.last_timer_check).as_secs() >= TIMER_CHECK_INTERVAL_SECS {
        state.last_timer_check = now;
        check_and_fire_timers(state).await;
    }

    // Status HUD update (every 60s)
    if now.duration_since(state.last_hud_update).as_secs() >= HUD_UPDATE_INTERVAL_SECS {
        state.last_hud_update = now;
        update_status_hud(state).await;
    }

    // Infra health check (every 5min)
    if now.duration_since(state.last_infra_check).as_secs() >= INFRA_CHECK_INTERVAL_SECS {
        state.last_infra_check = now;
        check_infra_health(state).await;
    }

    // Identity drift check (every 5min)
    if now.duration_since(state.last_identity_check).as_secs() >= IDENTITY_DRIFT_INTERVAL_SECS {
        state.last_identity_check = now;
        check_identity_drift(state).await;
    }

    // LLM provider health check
    let llm_interval = state
        .config
        .settings
        .llm_health_check_interval_ms
        .map(|ms| ms / 1000)
        .unwrap_or(LLM_HEALTH_CHECK_INTERVAL_SECS);
    if now.duration_since(state.last_llm_health_check).as_secs() >= llm_interval {
        state.last_llm_health_check = now;
        check_llm_health(state).await;
    }
}

// ============================================================================
// Event processing
// ============================================================================

async fn process_event(
    state: &mut CoordinatorState,
    agent_name: &str,
    room_id: &str,
    event: MatrixEvent,
    matrix_client: &MatrixClient,
    is_initial_sync: bool,
) {
    // Skip non-message events (but allow reactions for approval flow)
    if event.event_type != "m.room.message" && event.event_type != "m.reaction" {
        return;
    }

    // Handle reactions — check if this is an approval decision
    if event.event_type == "m.reaction" {
        process_reaction(state, &event).await;
        return;
    }

    // Skip coordinator-generated messages (prevent self-loops)
    if CoordinatorState::is_coordinator_generated(&event) {
        return;
    }

    // Skip own messages
    let session = match state.sessions.get(agent_name) {
        Some(s) => s,
        None => return,
    };
    if event.sender == session.matrix_user_id {
        return;
    }

    // Dedup
    if state.is_duplicate_event(agent_name, room_id, &event.event_id) {
        return;
    }

    // Skip messages from non-allowlisted senders
    if !state.is_allowlisted(&event.sender) {
        debug!(
            "[{}] Skipping message from non-allowlisted sender: {}",
            agent_name, event.sender
        );
        return;
    }

    // Skip initial sync backfill messages
    if is_initial_sync {
        debug!("[{}] Skipping initial sync backfill event {}", agent_name, event.event_id);
        return;
    }

    let message_content = match CoordinatorState::get_message_content(&event) {
        Some(c) => c,
        None => return,
    };

    // Extract body text for routing/command checks (images use their filename)
    let (body, formatted_body) = match &message_content {
        MessageContent::Text { body, formatted_body } => (body.clone(), formatted_body.clone()),
        MessageContent::Image { body, .. } => (body.clone(), None),
    };

    if body.trim().is_empty() {
        return;
    }

    // Check if this room is known (or if it's a DM)
    let is_dm = {
        if let Some(&cached) = state.dm_room_cache.get(room_id) {
            cached
        } else {
            // Check member count
            let count = matrix_client.get_joined_member_count(room_id).await.unwrap_or(3);
            let is_dm = count == 2;
            state.dm_room_cache.insert(room_id.to_string(), is_dm);
            is_dm
        }
    };

    // Slash commands bypass require_mention — handle before the mention gate.
    // Guard to the default_agent's sync loop to avoid duplicate handling when
    // multiple agents share a room.
    if body.trim_start().starts_with('/') {
        let is_default_agent = state
            .config
            .rooms
            .get(room_id)
            .and_then(|r| r.default_agent.as_ref())
            .map(|d| d == agent_name)
            .unwrap_or(false);

        if is_default_agent {
            let command_handled =
                handle_command(state, agent_name, room_id, &body, &event.sender, matrix_client).await;
            if command_handled {
                return;
            }
        }
    }

    // Determine which agents should respond
    let agents_to_notify: Vec<String> = state
        .get_agents_for_room(room_id, &body, formatted_body.as_deref(), is_dm)
        .iter()
        .filter(|&&a| a == agent_name) // only process for THIS agent's sync loop
        .map(|&a| a.to_string())
        .collect();

    if agents_to_notify.is_empty() {
        return;
    }

    // Dispatch to agent
    dispatch_to_agent(state, agent_name, room_id, &body, &event, &message_content, matrix_client).await;
}

async fn dispatch_to_agent(
    state: &mut CoordinatorState,
    agent_name: &str,
    room_id: &str,
    body: &str,
    event: &MatrixEvent,
    message_content: &MessageContent,
    matrix_client: &MatrixClient,
) {
    // Circuit breaker check — skip dispatch if agent is paused/killed
    let breaker_action = state.lifecycle.tick_circuit_breaker(agent_name);
    match breaker_action {
        BreakerAction::Pause => {
            info!("[{}] Circuit breaker PAUSED — skipping dispatch", agent_name);
            return;
        }
        BreakerAction::Kill => {
            warn!("[{}] Circuit breaker KILL — terminating session", agent_name);
            // The agent task will detect the exit and auto-restart after delay
            return;
        }
        _ => {}
    }

    let session = match state.sessions.get_mut(agent_name) {
        Some(s) => s,
        None => return,
    };

    // Check if session is ready
    {
        let proc = session.process.try_lock();
        if let Ok(p) = proc {
            if !p.is_ready {
                if let Err(e) = matrix_client
                    .send_message(room_id, "_(Agent session starting…)_", None, None)
                    .await
                {
                    warn!("[{}] Failed to send 'starting' message: {}", agent_name, e);
                }
                return;
            }
        }
    }

    session.current_room_id = Some(room_id.to_string());
    session.processing_started_at = Some(Instant::now());

    // Send typing indicator
    let _ = matrix_client.send_typing(room_id, true, TYPING_TIMEOUT_MS).await;

    // Build memory context injection (Phase 3 will populate this)
    // Context mode: Thin skips memory injection to reduce token usage (FCT007 Borrow #4)
    let memory_context = if session.config.context_mode == crate::config::ContextMode::Thin {
        String::new()
    } else {
        memory::build_memory_context_injection(agent_name)
    };

    // Build content_blocks for image messages (download + base64)
    let content_blocks = match message_content {
        MessageContent::Image { mxc_url, mimetype, body: img_body } => {
            match matrix_client.download_media(mxc_url).await {
                Ok((bytes, _content_type)) => {
                    use base64::Engine;
                    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
                    let text = if memory_context.is_empty() {
                        img_body.clone()
                    } else {
                        format!("{}\n\n---\n{}", memory_context, img_body)
                    };
                    Some(serde_json::json!([
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mimetype,
                                "data": b64
                            }
                        },
                        { "type": "text", "text": text }
                    ]))
                }
                Err(e) => {
                    warn!("[{}] Failed to download media {}: {}", agent_name, mxc_url, e);
                    None
                }
            }
        }
        _ => None,
    };

    let full_message = if content_blocks.is_some() {
        body.to_string() // text body for UserMessage.content (used for logging)
    } else if memory_context.is_empty() {
        body.to_string()
    } else {
        format!("{}\n\n---\n{}", memory_context, body)
    };

    // Generate a thread ID for this dispatch turn — session is already a &mut AgentSession
    let dispatch_thread_id = generate_thread_id();
    session.current_thread_id = Some(dispatch_thread_id);
    session.thread_header_posted = false;
    session.relay_delivered = false;
    // DM rooms: no threading (visual noise, relation conflicts per MSC3440)
    // Group rooms: task-per-thread anchor pattern — send a fresh m.notice anchor
    // and thread off it. This avoids MSC3440 relation conflicts because the anchor
    // is a new event we control, guaranteed relation-free.
    let is_dm = state.dm_room_cache.get(room_id).copied().unwrap_or(false);
    if is_dm {
        session.current_thread_root_event_id = None;
    } else {
        // Task-per-thread: send a clean anchor message, thread off it.
        let anchor_body = format!("\u{26a1} {}", agent_name);
        match matrix_client.send_anchor(room_id, &anchor_body).await {
            Ok(anchor_event_id) => {
                session.current_thread_root_event_id = Some(anchor_event_id);
            }
            Err(e) => {
                warn!("[{}] Failed to send thread anchor, falling back to plain messages: {}", agent_name, e);
                session.current_thread_root_event_id = None;
            }
        }
    }

    // Agent console: render input attribution to tmux pty (FCT048)
    if state.config.settings.agent_console_enabled {
        let socket_dir = state.config.settings.agent_tmux_socket_dir
            .as_deref()
            .unwrap_or("/tmp/tmux-nesbitt");
        let ts = console_timestamp();
        let sender_short = event.sender.trim_start_matches('@').split(':').next().unwrap_or(&event.sender);
        let preview = if body.len() > 120 { format!("{}...", &body[..120]) } else { body.to_string() };
        let attribution = format!("[{}] matrix/{}  {}", ts, sender_short, preview);
        write_to_agent_console(agent_name, &attribution, socket_dir);
    }

    let timeout_ms = state.config.settings.claude_timeout_ms;
    let result = send_to_agent(
        session,
        full_message,
        content_blocks,
        room_id.to_string(),
        event.event_id.clone(),
        timeout_ms,
    )
    .await;

    // Stop typing indicator
    let _ = matrix_client.send_typing(room_id, false, 0).await;

    let session = state.sessions.get_mut(agent_name).unwrap();
    session.processing_started_at = None;
    session.last_response_at = Some(Instant::now());

    match result {
        Ok(res) => {
            // Record provider success/failure for failover chain
            let provider_name = state.provider_chain.current().name.clone();
            if res.subtype == "error" && is_retriable_inference_error(&res.result) {
                if let Some(event) = state.provider_chain.record_failure(&provider_name, &res.result) {
                    match &event {
                        crate::provider_chain::ProviderEvent::Failover { from, to, reason } => {
                            warn!("[{}] Provider failover triggered by inference error: {} -> {} ({})", agent_name, from, to, reason);
                        }
                        crate::provider_chain::ProviderEvent::Exhausted { tried } => {
                            warn!("[{}] All providers exhausted after inference error: {:?}", agent_name, tried);
                        }
                        _ => {}
                    }
                }
            } else if res.subtype != "error" {
                state.provider_chain.record_success(&provider_name, 0);
            }

            // If Claude returned subtype="error", route through the context-aware error relay
            // rather than broadcasting raw error text as a normal agent response.
            if res.subtype == "error" {
                let err_str = res.result.trim().to_string();
                if !err_str.is_empty() {
                    // If the relay loop already delivered a successful response this turn,
                    // the error is a trailing artifact (e.g. session init noise after recovery).
                    // Suppress it — the turn already completed successfully.
                    let relay_delivered = state.sessions.get(agent_name)
                        .map(|s| s.relay_delivered)
                        .unwrap_or(false);
                    if relay_delivered {
                        warn!("[{}] Suppressing subtype=error — relay already delivered this turn: {}", agent_name, err_str);
                        return;
                    }

                    // Always suppress CLI auth/init errors regardless of network state
                    if is_suppressed_error(&err_str) {
                        warn!("[{}] Suppressed CLI error in subtype=error: {}", agent_name, err_str);
                        return;
                    }

                    let is_auth_error = err_str.to_lowercase().contains("authentication")
                        || err_str.contains("401")
                        || err_str.contains("403")
                        || err_str.to_lowercase().contains("unauthorized");
                    let network_degraded = state.sync_consecutive_failures > 0
                        || state.last_sync_success.elapsed().as_secs() > 30;

                    if network_degraded && is_auth_error {
                        let count = state.suppressed_error_counts
                            .entry(agent_name.to_string())
                            .or_insert(0);
                        *count += 1;
                        warn!("[{}] Suppressing auth error (subtype=error) during network degradation (suppressed: {}): {}", agent_name, count, err_str);
                    } else {
                        if let Some(suppressed) = state.suppressed_error_counts.remove(agent_name) {
                            let summary = format!(
                                "_(Note: {} auth error(s) suppressed during recent network outage)_",
                                suppressed
                            );
                            let _ = matrix_client.send_message(room_id, &summary, None, None).await;
                        }
                        error!("[{}] Agent returned subtype=error: {}", agent_name, err_str);
                        let msg = format!("_(Error: {})_", err_str);
                        let _ = matrix_client.send_message(room_id, &msg, None, None).await;
                    }
                }
                return;
            }

            if !res.result.trim().is_empty() {
                // Suppress CLI auth/init errors that leak through with subtype=success
                if is_suppressed_error(&res.result) {
                    warn!("[{}] Suppressed CLI error in Ok result text: {}", agent_name, res.result);
                    return;
                }

                // Relay loop output dedup — check if this response matches recent agent output
                if state.is_duplicate_output(room_id, &res.result) {
                    warn!(
                        "[{}] Suppressed duplicate agent output in room {} (relay loop prevention)",
                        agent_name, room_id
                    );
                    return;
                }

                // Extract [REMEMBER] observations from output
                memory::extract_observations(
                    agent_name,
                    &res.result,
                    &mut state.memory_rate_limiter,
                );

                let session = state.sessions.get_mut(agent_name).unwrap();
                session.last_response_text = Some(res.result.clone());
                // Persist session ID for resume support on next coordinator startup.
                if res.session_id.is_some() {
                    session.last_session_id = res.session_id.clone();
                }

                // Check for inter-agent routing pattern (>> @agentname)
                if let Some(routing_result) =
                    check_inter_agent_routing(state, agent_name, room_id, &res.result, event)
                {
                    // Routing was handled — still send the response to Matrix
                    let _ = routing_result;
                }

                let session = state.sessions.get(agent_name).unwrap();
                let send_result = if let Some(ref thread_root) = session.current_thread_root_event_id {
                    matrix_client.send_thread_reply(room_id, thread_root, &res.result, None).await
                } else {
                    matrix_client.send_message(room_id, &res.result, None, None).await
                };
                match send_result {
                    Ok(_event_id) => {
                        // Mark turn as delivered so activity drain skips text_blocks
                        if let Some(s) = state.sessions.get_mut(agent_name) {
                            s.relay_delivered = true;
                        }

                        // Send read receipt for the original message
                        let _ = matrix_client
                            .send_read_receipt(room_id, &event.event_id)
                            .await;

                        // Record successful response for health
                        state.lifecycle.reset_circuit_breaker(agent_name);
                    }
                    Err(e) => {
                        error!("[{}] Failed to send response: {}", agent_name, e);
                        // Record send failure as a health incident
                        if let Some(session) = state.sessions.get(agent_name) {
                            let mut proc = session.process.lock().await;
                            proc.health.record_incident(
                                IncidentType::ToolFailure,
                                Some("Matrix send failed"),
                                None,
                            );
                        }
                    }
                }
            }
        }
        Err(e) => {
            error!("[{}] Agent returned error: {}", agent_name, e);

            // Record retriable errors in provider chain for failover tracking
            let err_text = e.to_string();
            if is_retriable_inference_error(&err_text) {
                let provider_name = state.provider_chain.current().name.clone();
                if let Some(event) = state.provider_chain.record_failure(&provider_name, &err_text) {
                    match &event {
                        crate::provider_chain::ProviderEvent::Failover { from, to, reason } => {
                            warn!("[{}] Provider failover triggered by dispatch error: {} -> {} ({})", agent_name, from, to, reason);
                        }
                        crate::provider_chain::ProviderEvent::Exhausted { tried } => {
                            warn!("[{}] All providers exhausted after dispatch error: {:?}", agent_name, tried);
                        }
                        _ => {}
                    }
                }
            }

            // Record failure for circuit breaker
            let is_timeout = err_text.contains("timed out");
            let incident = if is_timeout {
                IncidentType::Timeout
            } else {
                IncidentType::ToolFailure
            };
            state.lifecycle.record_failure(agent_name, &incident);

            if let Some(session) = state.sessions.get(agent_name) {
                let mut proc = session.process.lock().await;
                proc.health.record_incident(incident, Some(&err_text), None);
            }

            // Always suppress CLI auth/init errors — these are never useful to relay
            if is_suppressed_error(&err_text) {
                warn!("[{}] Suppressed CLI error in Err branch: {}", agent_name, err_text);
                return;
            }

            // Context-aware error relay for remaining errors:
            // During a network outage, auth-adjacent errors are suppressed and summarized on recovery.
            let is_auth_error = err_text.contains("authentication")
                || err_text.contains("401")
                || err_text.contains("403")
                || err_text.contains("Unauthorized")
                || err_text.contains("Permission denied");
            let network_degraded = state.sync_consecutive_failures > 0
                || state.last_sync_success.elapsed().as_secs() > 30;

            if network_degraded && is_auth_error {
                // Suppress — count for later summary
                let count = state.suppressed_error_counts
                    .entry(agent_name.to_string())
                    .or_insert(0);
                *count += 1;
                warn!("[{}] Suppressing auth error during network degradation (suppressed: {}): {}", agent_name, count, err_text);
            } else {
                // Network healthy or non-auth error — relay immediately
                // Flush any suppressed count for this agent first
                if let Some(suppressed) = state.suppressed_error_counts.remove(agent_name) {
                    let summary = format!(
                        "_(Note: {} auth error(s) suppressed during recent network outage)_",
                        suppressed
                    );
                    let _ = matrix_client.send_message(room_id, &summary, None, None).await;
                }
                let msg = format!("_(Error: {})_", err_text);
                let _ = matrix_client.send_message(room_id, &msg, None, None).await;
            }
        }
    }
}

// ============================================================================
// Approval request processing
// ============================================================================

async fn process_pending_approvals(state: &mut CoordinatorState) {
    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();
    let agent_names: Vec<String> = state.sessions.keys().cloned().collect();

    for agent_name in agent_names {
        // Drain pending approval requests from the agent subprocess
        let approval_requests: Vec<_> = {
            let session = match state.sessions.get(&agent_name) {
                Some(s) => s,
                None => continue,
            };
            let mut rx = match session.approval_request_rx.try_lock() {
                Ok(rx) => rx,
                Err(_) => continue,
            };
            let mut requests = Vec::new();
            while let Ok(req) = rx.try_recv() {
                requests.push(req);
            }
            requests
        };

        for req in approval_requests {
            let session = match state.sessions.get(&agent_name) {
                Some(s) => s,
                None => continue,
            };

            let trust_level = session.config.trust_level.unwrap_or(2);
            let tool_name = req.tool_name.as_deref().unwrap_or("unknown");

            // Frozen harness enforcement (autoscope — FCT009)
            if !state.loop_manager.get_active_loops_for_agent(&agent_name).is_empty() {
                let frozen_violation = match tool_name {
                    "Write" | "Edit" => {
                        req.tool_input.as_ref().and_then(|input| {
                            let path = input.get("file_path").or_else(|| input.get("path"))
                                .and_then(|v| v.as_str());
                            path.filter(|p| state.loop_manager.is_frozen(&agent_name, p))
                                .map(|p| p.to_string())
                        })
                    }
                    "Bash" => {
                        req.tool_input.as_ref().and_then(|input| {
                            let cmd = input.get("command").and_then(|v| v.as_str()).unwrap_or("");
                            // Scan for any frozen path substring in the command
                            let loops = state.loop_manager.get_active_loops_for_agent(&agent_name);
                            for lp in &loops {
                                for frozen in &lp.spec.frozen_harness {
                                    if cmd.contains(frozen.as_str()) {
                                        return Some(frozen.clone());
                                    }
                                }
                            }
                            None
                        })
                    }
                    _ => None,
                };

                if let Some(frozen_path) = frozen_violation {
                    warn!("[{}] Frozen harness violation: {} attempted on {}", agent_name, tool_name, frozen_path);
                    if let Some(session) = state.sessions.get(&agent_name) {
                        let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                    }
                    state.approval_tracker.record(ApprovalRecord {
                        agent_name: agent_name.clone(),
                        tool_name: tool_name.to_string(),
                        room_id: req.room_id.clone(),
                        decision: ApprovalDecision::MatrixDenied,
                        requested_at: now_ms(),
                        resolved_at: now_ms(),
                        latency_ms: 0,
                        gate_type: None,
                    });
                    let _ = state.run_event_log.append_event(
                        &agent_name,
                        RunEventType::FrozenHarnessViolation,
                        EventStream::System,
                        EventLevel::Warn,
                        &format!("frozen harness violation: {} attempted on {}", tool_name, frozen_path),
                        Some(serde_json::json!({
                            "tool": tool_name,
                            "path": frozen_path,
                            "request_id": req.request_id,
                        })),
                    ).await;
                    continue;
                }
            }

            // Auto-approve check
            let auto_approved =
                state.should_auto_approve(tool_name, req.tool_input.as_ref(), trust_level);

            if auto_approved {
                debug!("[{}] Auto-approving: {}", agent_name, tool_name);
                let _ = session.approval_tx.try_send((req.request_id.clone(), true, None));

                // Record in tracker
                state.approval_tracker.record(ApprovalRecord {
                    agent_name: agent_name.clone(),
                    tool_name: tool_name.to_string(),
                    room_id: req.room_id.clone(),
                    decision: ApprovalDecision::Auto,
                    requested_at: now_ms(),
                    resolved_at: now_ms(),
                    latency_ms: 0,
                    gate_type: None,
                });
                continue;
            }

            // Rate limit check
            if state.approval_rate_limiter.check_and_increment(&agent_name) {
                warn!(
                    "[{}] Approval rate limit exceeded, denying {}",
                    agent_name, tool_name
                );
                let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                state.approval_tracker.record(ApprovalRecord {
                    agent_name: agent_name.clone(),
                    tool_name: tool_name.to_string(),
                    room_id: req.room_id.clone(),
                    decision: ApprovalDecision::RateLimited,
                    requested_at: now_ms(),
                    resolved_at: now_ms(),
                    latency_ms: 0,
                    gate_type: None,
                });
                continue;
            }

            // Post approval request to Matrix via coordinator account — all approvals
            // funnel to COORD_APPROVAL_ROOM regardless of which agent triggered them.
            let thread_id = state.sessions.get(&agent_name)
                .and_then(|s| s.current_thread_id.clone())
                .unwrap_or_default();

            let coord_token = match state.coord_token.clone() {
                Some(t) => t,
                None => {
                    error!("[{}] No coord token — cannot post approval, denying {}", agent_name, tool_name);
                    if let Some(session) = state.sessions.get(&agent_name) {
                        let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                    }
                    continue;
                }
            };

            let coord_user_id = state.coord_user_id.as_deref()
                .unwrap_or("@coord:matrix.org")
                .to_string();
            let matrix_client = match MatrixClient::new(
                pantalaimon_url.as_deref(),
                coord_token,
                coord_user_id,
            ) {
                Ok(c) => c,
                Err(e) => {
                    error!("[{}] Failed to build Matrix client for approval: {}", agent_name, e);
                    if let Some(session) = state.sessions.get(&agent_name) {
                        let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                    }
                    continue;
                }
            };

            // Format approval message with truncated input
            let input_preview = req
                .tool_input
                .as_ref()
                .map(|v| {
                    let s = v.to_string();
                    if s.len() > 200 {
                        format!("{}…", &s[..200])
                    } else {
                        s
                    }
                })
                .unwrap_or_default();

            let thread_label = if thread_id.is_empty() {
                String::new()
            } else {
                format!(" [{}]", thread_id)
            };
            let hmac_tag = state.hmac_signer.sign(&req.request_id);
            let approval_msg = format!(
                "**⚠️ {} needs approval{}**\n\nTool: `{}`\nInput:\n```\n{}\n```\n\nReact ✅ to approve, ❌ to deny\n\n`hmac:{}`",
                agent_name, thread_label, tool_name, input_preview, hmac_tag
            );

            match matrix_client
                .send_message(COORD_APPROVAL_ROOM, &approval_msg, None,
                    Some(&Mentions { user_ids: vec![state.config.settings.approval_owner.clone()], room: false }))
                .await
            {
                Ok(event_id) => {
                    info!(
                        "[{}] Posted approval request for {} [{}] (event: {})",
                        agent_name, tool_name, thread_id, event_id
                    );

                    state.pending_matrix_approvals.insert(
                        event_id.clone(),
                        PendingMatrixApproval {
                            room_id: COORD_APPROVAL_ROOM.to_string(),
                            agent_name: agent_name.clone(),
                            request_id: req.request_id.clone(),
                            tool_name: tool_name.to_string(),
                            created_at: Instant::now(),
                            fs_approval: false,
                            thread_id: thread_id.clone(),
                            gate_type: crate::approval::ApprovalGateType::ToolCall,
                            hmac_tag,
                        },
                    );
                }
                Err(e) => {
                    warn!(
                        "[{}] Failed to post approval to COORD_APPROVAL_ROOM ({}), trying agent token fallback",
                        agent_name, e
                    );
                    // Fallback: use agent's own token + get_approval_room so the approval
                    // request is never silently lost regardless of coord room membership.
                    let fallback_room = get_approval_room(state, &agent_name);
                    let (fb_token, fb_user_id) = match state.sessions.get(&agent_name) {
                        Some(s) => (s.matrix_token.clone(), s.matrix_user_id.clone()),
                        None => {
                            error!("[{}] No session for approval fallback — denying {}", agent_name, tool_name);
                            continue;
                        }
                    };
                    match MatrixClient::new(pantalaimon_url.as_deref(), fb_token, fb_user_id) {
                        Ok(fb_client) => {
                            match fb_client.send_message(&fallback_room, &approval_msg, None,
                                    Some(&Mentions { user_ids: vec![state.config.settings.approval_owner.clone()], room: false })).await {
                                Ok(event_id) => {
                                    info!("[{}] Posted approval via agent token to {} (event: {})", agent_name, fallback_room, event_id);
                                    state.pending_matrix_approvals.insert(
                                        event_id.clone(),
                                        PendingMatrixApproval {
                                            room_id: fallback_room,
                                            agent_name: agent_name.clone(),
                                            request_id: req.request_id.clone(),
                                            tool_name: tool_name.to_string(),
                                            created_at: Instant::now(),
                                            fs_approval: false,
                                            thread_id: thread_id.clone(),
                                            gate_type: crate::approval::ApprovalGateType::ToolCall,
                                            hmac_tag: hmac_tag.clone(),
                                        },
                                    );
                                }
                                Err(e2) => {
                                    error!("[{}] Fallback approval post also failed ({}), denying {}", agent_name, e2, tool_name);
                                    if let Some(session) = state.sessions.get(&agent_name) {
                                        let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                                    }
                                }
                            }
                        }
                        Err(e2) => {
                            error!("[{}] Failed to build fallback Matrix client ({}), denying {}", agent_name, e2, tool_name);
                            if let Some(session) = state.sessions.get(&agent_name) {
                                let _ = session.approval_tx.try_send((req.request_id.clone(), false, None));
                            }
                        }
                    }
                }
            }
        }
    }

    // Sweep timed-out approvals
    sweep_timed_out_approvals(state).await;
}

/// Process a reaction event — check if it's an approval decision (✅ or ❌).
async fn process_reaction(state: &mut CoordinatorState, event: &MatrixEvent) {
    // Only process reactions from the approval owner
    let approval_owner = &state.config.settings.approval_owner;
    if event.sender != *approval_owner {
        return;
    }

    // Extract m.relates_to.event_id and key
    let relates_to = match event.content.get("m.relates_to") {
        Some(r) => r,
        None => return,
    };
    let target_event_id = match relates_to.get("event_id").and_then(|v| v.as_str()) {
        Some(id) => id,
        None => return,
    };
    let key = match relates_to.get("key").and_then(|v| v.as_str()) {
        Some(k) => k,
        None => return,
    };

    // Check if this reaction targets a pending approval
    let pending = match state.pending_matrix_approvals.remove(target_event_id) {
        Some(p) => p,
        None => return, // Not a tracked approval
    };

    // C2: Verify HMAC integrity — ensure the pending approval was created by this coordinator
    let expected_tag = state.hmac_signer.sign(&pending.request_id);
    if pending.hmac_tag != expected_tag {
        warn!(
            "[{}] HMAC verification failed for approval {} — rejecting reaction",
            pending.agent_name, pending.request_id
        );
        return;
    }

    let approved = key.contains('✅') || key.contains("approve") || key.contains("yes");
    let denied = key.contains('❌') || key.contains("deny") || key.contains("no");

    if !approved && !denied {
        // Unknown reaction — put it back
        state
            .pending_matrix_approvals
            .insert(target_event_id.to_string(), pending);
        return;
    }

    info!(
        "[{}] Approval {} for tool {} (reaction: {})",
        pending.agent_name,
        if approved { "GRANTED" } else { "DENIED" },
        pending.tool_name,
        key
    );

    // Send decision to agent
    if pending.fs_approval {
        // Filesystem hook approval — write .response file
        let decision_str = if approved { "allow" } else { "deny" };
        if let Err(e) = state.hmac_signer.write_approval_response(
            &state.approval_dir, &pending.request_id, decision_str,
        ) {
            error!("[{}] Failed to write fs approval response: {}", pending.agent_name, e);
        }
        info!("[{}] Wrote fs approval response: {} for {}", pending.agent_name, decision_str, pending.tool_name);
    } else if let Some(session) = state.sessions.get(&pending.agent_name) {
        // Include coordinator note so Claude can reference the thread ID conversationally
        let note = if !pending.thread_id.is_empty() {
            Some(format!(
                "[Coordinator: approval request was posted to Matrix as thread {}]",
                pending.thread_id
            ))
        } else {
            None
        };
        let _ = session
            .approval_tx
            .try_send((pending.request_id.clone(), approved, note));
    }

    let latency = pending.created_at.elapsed().as_millis() as u64;
    state.approval_tracker.record(ApprovalRecord {
        agent_name: pending.agent_name.clone(),
        tool_name: pending.tool_name.clone(),
        room_id: pending.room_id.clone(),
        decision: if approved {
            ApprovalDecision::MatrixApproved
        } else {
            ApprovalDecision::MatrixDenied
        },
        requested_at: now_ms() - latency,
        resolved_at: now_ms(),
        latency_ms: latency,
        gate_type: None,
    });
}

/// Auto-deny approvals that have been pending longer than approval_timeout_ms.
async fn sweep_timed_out_approvals(state: &mut CoordinatorState) {
    if state.last_approval_sweep.elapsed() < Duration::from_millis(APPROVAL_SWEEP_INTERVAL_MS) {
        return;
    }
    state.last_approval_sweep = Instant::now();

    let timeout_ms = state.config.settings.approval_timeout_ms;
    let timeout_duration = Duration::from_millis(timeout_ms);

    let expired: Vec<String> = state
        .pending_matrix_approvals
        .iter()
        .filter(|(_, p)| p.created_at.elapsed() > timeout_duration)
        .map(|(k, _)| k.clone())
        .collect();

    for event_id in expired {
        if let Some(pending) = state.pending_matrix_approvals.remove(&event_id) {
            warn!(
                "[{}] Approval timed out for tool {} after {}ms",
                pending.agent_name, pending.tool_name, timeout_ms
            );

            if pending.fs_approval {
                // Write deny .response for filesystem hook
                let _ = state.hmac_signer.write_approval_response(
                    &state.approval_dir, &pending.request_id, "deny",
                );
            } else if let Some(session) = state.sessions.get(&pending.agent_name) {
                let _ = session
                    .approval_tx
                    .try_send((pending.request_id.clone(), false, None));
            }

            state.approval_tracker.record(ApprovalRecord {
                agent_name: pending.agent_name.clone(),
                tool_name: pending.tool_name.clone(),
                room_id: pending.room_id.clone(),
                decision: ApprovalDecision::TimedOut,
                requested_at: now_ms() - pending.created_at.elapsed().as_millis() as u64,
                resolved_at: now_ms(),
                latency_ms: pending.created_at.elapsed().as_millis() as u64,
                gate_type: None,
            });
        }
    }
}

// ============================================================================
// Agent console — tmux pty rendering (FCT048)
// ============================================================================

/// Write a line to the agent's tmux console session (if enabled).
/// Non-blocking: spawns a background process, logs errors but never fails the caller.
fn write_to_agent_console(
    agent_name: &str,
    line: &str,
    _socket_dir: &str,
) {
    let socket_name = format!("agent-{}", agent_name);
    let session_name = socket_name.clone();
    // Escape single quotes for shell safety
    let escaped = line.replace('\'', "'\\''");
    // Use -L (named socket) which tmux stores in its default socket dir
    let cmd = format!(
        "tmux -L '{}' send-keys -t '{}' '{}' Enter 2>/dev/null",
        socket_name, session_name, escaped
    );
    let _ = std::process::Command::new("sh")
        .args(["-c", &cmd])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
}

/// Format a timestamp for console display (HH:MM).
fn console_timestamp() -> String {
    use std::time::SystemTime;
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let hours = (now % 86400) / 3600;
    let minutes = (now % 3600) / 60;
    format!("{:02}:{:02}", hours, minutes)
}

// ============================================================================
// Verbose tool activity — drain and post to Matrix threads
// ============================================================================

async fn drain_agent_activity(state: &mut CoordinatorState) {
    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();

    // Collect activities from all agents
    let mut activities: Vec<agent::AgentActivity> = Vec::new();
    for session in state.sessions.values_mut() {
        while let Ok(activity) = session.activity_rx.try_recv() {
            activities.push(activity);
        }
    }

    for activity in activities {
        // In DMs, skip verbose tool activity thread posts entirely — they add noise
        let is_dm = state.dm_room_cache.get(&activity.room_id).copied().unwrap_or(false);
        if is_dm {
            continue;
        }

        // Extract session fields in a scoped borrow, then drop before async work
        let (is_first, thread_id, relay_delivered, token, user_id) = {
            let session = match state.sessions.get_mut(&activity.agent_name) {
                Some(s) => s,
                None => continue,
            };
            let is_first = !session.thread_header_posted;
            if is_first {
                session.thread_header_posted = true;
            }
            let tid = session.current_thread_id.clone().unwrap_or_default();
            (is_first, tid, session.relay_delivered, session.matrix_token.clone(), session.matrix_user_id.clone())
        }; // mutable borrow dropped here

        let client = match MatrixClient::new(
            pantalaimon_url.as_deref(),
            token,
            user_id,
        ) {
            Ok(c) => c,
            Err(_) => continue,
        };

        // Post reasoning text (Claude's narration before/between tool calls).
        // Skip if relay loop already delivered the final response for this turn —
        // flag-based check is deterministic, unlike content-hash dedup which breaks
        // on truncation differences or partial text blocks.
        // Also filter auth error text blocks — these are emitted by the CLI during
        // session init/resume and are not meaningful agent output.
        let filtered_blocks: Vec<String> = activity.text_blocks.iter()
            .filter(|t| {
                if is_suppressed_error(t) {
                    warn!("[{}] Suppressed CLI error in activity text_block: {}", activity.agent_name, t);
                    false
                } else {
                    true
                }
            })
            .cloned()
            .collect();
        if !filtered_blocks.is_empty() && !relay_delivered {
            let text = filtered_blocks.join("\n\n");
            let truncated = if text.len() > 1000 {
                format!("{}…", &text[..1000])
            } else {
                text
            };
            let body = if is_first && !thread_id.is_empty() {
                format!("[{}] {}", thread_id, truncated)
            } else {
                truncated
            };
            if let Err(e) = client
                .send_thread_message(&activity.room_id, &body, &activity.thread_root_event_id)
                .await
            {
                info!("[{}] Failed to post text activity: {}", activity.agent_name, e);
            }
        } else if !activity.text_blocks.is_empty() && relay_delivered {
            // Relay already delivered — suppress text, but post thread label if first activity
            if is_first && !thread_id.is_empty() {
                info!("[{}] Relay delivered turn, suppressing activity text for room {}",
                    activity.agent_name, activity.room_id);
            }
        } else if is_first && !thread_id.is_empty() {
            // No text block on first activity — post a standalone label so the thread
            // is always identifiable even for pure tool-call turns.
            if let Err(e) = client
                .send_thread_message(
                    &activity.room_id,
                    &format!("[{}]", thread_id),
                    &activity.thread_root_event_id,
                )
                .await
            {
                debug!("[{}] Failed to post thread label: {}", activity.agent_name, e);
            }
        }

        // Then post tool names
        if !activity.tool_names.is_empty() {
            let summary = activity
                .tool_names
                .iter()
                .map(|n| format!("⚙️ {}", n))
                .collect::<Vec<_>>()
                .join("\n");
            if let Err(e) = client
                .send_thread_message(&activity.room_id, &summary, &activity.thread_root_event_id)
                .await
            {
                debug!("[{}] Failed to post tool activity: {}", activity.agent_name, e);
            }
        }

        // Agent console: render output to tmux pty (FCT048)
        if state.config.settings.agent_console_enabled {
            let socket_dir = state.config.settings.agent_tmux_socket_dir
                .as_deref()
                .unwrap_or("/tmp/tmux-nesbitt");
            let ts = console_timestamp();
            // Render text blocks (agent reasoning/response)
            for block in &activity.text_blocks {
                if !is_suppressed_error(block) {
                    let preview = if block.len() > 200 {
                        format!("{}...", &block[..200])
                    } else {
                        block.clone()
                    };
                    let line = format!("[{}] {} -> response: {}", ts, activity.agent_name, preview);
                    write_to_agent_console(&activity.agent_name, &line, socket_dir);
                }
            }
            // Render tool calls
            for tool in &activity.tool_names {
                let line = format!("[{}] {} -> tool_call: {}", ts, activity.agent_name, tool);
                write_to_agent_console(&activity.agent_name, &line, socket_dir);
            }
        }
    }
}

/// Scan filesystem for approval request files written by pretool-approval.sh hooks.
/// Reads .request files, maps session_id to agent, posts to Matrix, stores as pending.
async fn scan_filesystem_approvals(state: &mut CoordinatorState) {
    let entries = match std::fs::read_dir(&state.approval_dir) {
        Ok(e) => e,
        Err(_) => return, // Dir doesn't exist or unreadable — skip silently
    };

    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();
    let approval_timeout = Duration::from_millis(state.config.settings.approval_timeout_ms);

    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };

        // Only process .request files
        if !file_name.ends_with(".request") {
            continue;
        }

        // Read and parse the request JSON
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => {
                warn!("Failed to read approval request {}: {}", file_name, e);
                continue;
            }
        };

        let request: serde_json::Value = match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(e) => {
                warn!("Malformed approval request {}: {} — deleting", file_name, e);
                let _ = std::fs::remove_file(&path);
                continue;
            }
        };

        let request_id = match request.get("request_id").and_then(|v| v.as_str()) {
            Some(id) => id.to_string(),
            None => {
                warn!("Approval request {} missing request_id — deleting", file_name);
                let _ = std::fs::remove_file(&path);
                continue;
            }
        };

        // Check for stale requests (older than approval timeout)
        if let Some(ts_str) = request.get("timestamp").and_then(|v| v.as_str()) {
            if let Ok(ts) = chrono::DateTime::parse_from_rfc3339(ts_str) {
                let age = chrono::Utc::now().signed_duration_since(ts);
                if age.num_milliseconds() > approval_timeout.as_millis() as i64 {
                    warn!("Stale approval request {} (age: {}s) — auto-denying", request_id, age.num_seconds());
                    let _ = std::fs::remove_file(&path);
                    // Write deny response for the timed-out hook
                    let _ = state.hmac_signer.write_approval_response(&state.approval_dir, &request_id, "deny");
                    continue;
                }
            }
        }

        let tool_name = request.get("tool_name").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
        let tool_input = request.get("tool_input").cloned();
        let session_id = request.get("session_id").and_then(|v| v.as_str()).unwrap_or("").to_string();

        // Map session_id to agent name by checking running sessions
        let mut agent_name = "unknown".to_string();
        for (name, session) in &state.sessions {
            if let Ok(proc) = session.process.try_lock() {
                if let Some(ref sid) = proc.session_id {
                    if *sid == session_id {
                        agent_name = name.clone();
                        break;
                    }
                }
            }
        }

        // Delete the .request file (consumed — prevents re-processing)
        let _ = std::fs::remove_file(&path);

        info!(
            "[{}] Filesystem approval request: tool={}, request_id={}",
            agent_name, tool_name, request_id
        );

        // Frozen harness enforcement (autoscope — FCT009)
        if !state.loop_manager.get_active_loops_for_agent(&agent_name).is_empty() {
            let frozen_violation = match tool_name.as_str() {
                "Write" | "Edit" => {
                    tool_input.as_ref().and_then(|input| {
                        let path = input.get("file_path").or_else(|| input.get("path"))
                            .and_then(|v| v.as_str());
                        path.filter(|p| state.loop_manager.is_frozen(&agent_name, p))
                            .map(|p| p.to_string())
                    })
                }
                "Bash" => {
                    tool_input.as_ref().and_then(|input| {
                        let cmd = input.get("command").and_then(|v| v.as_str()).unwrap_or("");
                        let loops = state.loop_manager.get_active_loops_for_agent(&agent_name);
                        for lp in &loops {
                            for frozen in &lp.spec.frozen_harness {
                                if cmd.contains(frozen.as_str()) {
                                    return Some(frozen.clone());
                                }
                            }
                        }
                        None
                    })
                }
                _ => None,
            };

            if let Some(frozen_path) = frozen_violation {
                warn!("[{}] Frozen harness violation (fs): {} attempted on {}", agent_name, tool_name, frozen_path);
                let _ = state.hmac_signer.write_approval_response(&state.approval_dir, &request_id, "deny");
                let _ = state.run_event_log.append_event(
                    &agent_name,
                    RunEventType::FrozenHarnessViolation,
                    EventStream::System,
                    EventLevel::Warn,
                    &format!("frozen harness violation (fs): {} attempted on {}", tool_name, frozen_path),
                    Some(serde_json::json!({
                        "tool": tool_name,
                        "path": frozen_path,
                        "request_id": request_id,
                    })),
                ).await;
                continue;
            }
        }

        // Auto-approve check (same logic as stream-json approvals)
        let trust_level = if agent_name != "unknown" {
            state.sessions.get(&agent_name)
                .map(|s| s.config.trust_level.unwrap_or(2))
                .unwrap_or(2)
        } else {
            2
        };

        if state.should_auto_approve(&tool_name, tool_input.as_ref(), trust_level) {
            debug!("[{}] Auto-approving fs request: {}", agent_name, tool_name);
            let _ = state.hmac_signer.write_approval_response(&state.approval_dir, &request_id, "allow");
            state.approval_tracker.record(ApprovalRecord {
                agent_name: agent_name.clone(),
                tool_name: tool_name.clone(),
                room_id: String::new(),
                decision: ApprovalDecision::Auto,
                requested_at: now_ms(),
                resolved_at: now_ms(),
                latency_ms: 0,
                gate_type: None,
            });
            continue;
        }

        // Post approval request to Matrix
        let approval_room_id = get_approval_room(state, &agent_name);

        // Build a Matrix client — use the agent's token if known, otherwise coord token
        let (token, user_id) = if agent_name != "unknown" {
            if let Some(session) = state.sessions.get(&agent_name) {
                (session.matrix_token.clone(), session.matrix_user_id.clone())
            } else if let Some(ref ct) = state.coord_token {
                (ct.clone(), "@coord:matrix.org".to_string())
            } else {
                error!("[{}] No Matrix token available for fs approval", agent_name);
                continue;
            }
        } else if let Some(ref ct) = state.coord_token {
            (ct.clone(), "@coord:matrix.org".to_string())
        } else {
            error!("No Matrix token available for unknown-agent fs approval");
            continue;
        };

        let matrix_client = match MatrixClient::new(pantalaimon_url.as_deref(), token, user_id) {
            Ok(c) => c,
            Err(e) => {
                error!("[{}] Failed to build Matrix client for fs approval: {}", agent_name, e);
                continue;
            }
        };

        let input_preview = tool_input
            .as_ref()
            .map(|v| {
                let s = v.to_string();
                if s.len() > 200 {
                    format!("{}…", &s[..200])
                } else {
                    s
                }
            })
            .unwrap_or_default();

        let hmac_tag = state.hmac_signer.sign(&request_id);
        let approval_msg = format!(
            "**🔐 Approval Required** (hook)\n\n\
             Agent: `{}`\n\
             Tool: `{}`\n\
             Input: ```{}```\n\n\
             React ✅ to approve, ❌ to deny\n\n`hmac:{}`",
            agent_name, tool_name, input_preview, hmac_tag
        );

        match matrix_client
            .send_message(&approval_room_id, &approval_msg, None,
                Some(&Mentions { user_ids: vec![state.config.settings.approval_owner.clone()], room: false }))
            .await
        {
            Ok(event_id) => {
                info!(
                    "[{}] Posted fs approval request for {} (event: {})",
                    agent_name, tool_name, event_id
                );
                let fs_thread_id = state.sessions.get(&agent_name)
                    .and_then(|s| s.current_thread_id.clone())
                    .unwrap_or_default();
                state.pending_matrix_approvals.insert(
                    event_id.clone(),
                    PendingMatrixApproval {
                        room_id: approval_room_id,
                        agent_name: agent_name.clone(),
                        request_id: request_id.clone(),
                        tool_name: tool_name.clone(),
                        created_at: Instant::now(),
                        fs_approval: true,
                        thread_id: fs_thread_id,
                        gate_type: crate::approval::ApprovalGateType::ToolCall,
                        hmac_tag,
                    },
                );
            }
            Err(e) => {
                error!(
                    "[{}] Failed to post fs approval to Matrix: {} — auto-denying",
                    agent_name, e
                );
                let _ = state.hmac_signer.write_approval_response(&state.approval_dir, &request_id, "deny");
            }
        }
    }
}

/// Get the room ID where approval requests should be posted for an agent.
fn get_approval_room(state: &CoordinatorState, agent_name: &str) -> String {
    // Check agent's room config for an approval_delegate setting
    for (room_id, room) in &state.config.rooms {
        if room.approval_delegate.is_some() {
            let is_agent_room = room.default_agent.as_deref() == Some(agent_name)
                || room.agents.iter().any(|a| a == agent_name);
            if is_agent_room {
                return room_id.clone();
            }
        }
    }

    // Default: use the agent's current room or the status room
    if let Some(session) = state.sessions.get(agent_name) {
        if let Some(ref room_id) = session.current_room_id {
            return room_id.clone();
        }
    }

    STATUS_ROOM_ID.to_string()
}

// ============================================================================
// Session persistence (BKX093: resume support)
// ============================================================================

/// Load agent session IDs saved from the previous clean shutdown.
/// Returns an empty map if the file is absent or malformed (safe fresh start).
fn load_saved_sessions(home: &str) -> HashMap<String, String> {
    let path = format!("{}/.config/ig88/agent-sessions.json", home);
    match std::fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str::<HashMap<String, String>>(&content)
            .unwrap_or_else(|e| {
                warn!("Failed to parse agent sessions file ({}): {} — starting fresh", path, e);
                HashMap::new()
            }),
        Err(_) => HashMap::new(), // File absent on first run — normal
    }
}

/// Persist the most recent session ID for each agent so they can be resumed
/// on the next coordinator startup with `--resume <id>`.
fn save_agent_sessions(state: &CoordinatorState) {
    let home = std::env::var("HOME").unwrap_or_default();
    let path = format!("{}/.config/ig88/agent-sessions.json", home);

    let sessions: HashMap<String, String> = state
        .sessions
        .iter()
        .filter_map(|(name, session)| {
            session.last_session_id.clone().map(|id| (name.clone(), id))
        })
        .collect();

    if sessions.is_empty() {
        debug!("No agent session IDs to save (agents may not have responded yet this run)");
        return;
    }

    match serde_json::to_string_pretty(&sessions) {
        Ok(json) => {
            if let Err(e) = std::fs::write(&path, &json) {
                warn!("Failed to save agent sessions to {}: {}", path, e);
            } else {
                info!("Saved {} agent session ID(s) for resume: {:?}", sessions.len(), sessions.keys().collect::<Vec<_>>());
            }
        }
        Err(e) => warn!("Failed to serialize agent sessions: {}", e),
    }
}

// ============================================================================
// Command handling (2F)
// ============================================================================

fn is_privileged_command(parts: &[&str]) -> bool {
    if parts.is_empty() {
        return false;
    }
    let cmd = parts[0];
    if matches!(cmd, "/approve" | "/deny" | "/delegate") {
        return true;
    }
    if cmd == "/agent" && parts.get(1) == Some(&"recover") {
        return true;
    }
    if cmd == "/loop" && matches!(parts.get(1).copied(), Some("start") | Some("abort")) {
        return true;
    }
    false
}

/// Handle coordinator commands (messages starting with /). Returns true if handled.
async fn handle_command(
    state: &mut CoordinatorState,
    _agent_name: &str,
    room_id: &str,
    body: &str,
    sender: &str,
    matrix_client: &MatrixClient,
) -> bool {
    let parts: Vec<&str> = body.trim().split_whitespace().collect();
    let cmd = parts.first().copied().unwrap_or("");

    // M5: Rate limit slash commands — max 10 per user per 60s
    if state.command_rate_limiter.check_and_increment(sender) {
        let _ = matrix_client
            .send_message(room_id, "Rate limited — too many commands. Try again shortly.", None, None)
            .await;
        return true;
    }

    // C1: RBAC — privileged commands require owner or high trust
    if is_privileged_command(&parts) {
        let is_owner = sender == state.config.settings.approval_owner;
        if !is_owner {
            let _ = matrix_client
                .send_message(room_id, "Permission denied — this command requires owner privileges.", None, None)
                .await;
            return true;
        }
    }

    let response = match cmd {
        "/health" => Some(format_health_report(state)),
        "/status" => Some(format_status_report(state)),
        "/pending" => Some(format_pending_approvals(state)),
        "/agent" => {
            if parts.len() >= 2 {
                match parts[1] {
                    "list" => Some(format_agent_list(state)),
                    "recover" if parts.len() >= 3 => {
                        let target = parts[2];
                        Some(recover_agent(state, target))
                    }
                    _ => Some("Usage: `/agent list` | `/agent recover <name>`".to_string()),
                }
            } else {
                Some("Usage: `/agent list` | `/agent recover <name>`".to_string())
            }
        }
        "/approve" if parts.len() >= 2 => {
            let prefix = parts[1];
            Some(manual_approve(state, prefix, true).await)
        }
        "/deny" if parts.len() >= 2 => {
            let prefix = parts[1];
            Some(manual_approve(state, prefix, false).await)
        }
        "/delegate" if parts.len() >= 4 => {
            let repo = parts[1].to_string();
            let model = parts[2].to_string();
            let remaining = &parts[3..];
            // Extract and validate optional loop_spec: token
            let spec_error: Option<String> = remaining.iter().find_map(|p| {
                p.strip_prefix("loop_spec:").and_then(|name| {
                    if name.contains("..") || name.contains('/') || name.contains('\\') {
                        return Some(format!("Invalid loop spec: name must not contain path separators or '..' (got '{}')", name));
                    }
                    let home = std::env::var("HOME").unwrap_or_default();
                    let specs_dir = format!("{}/dev/autoresearch/loop-specs", home);
                    let md_path = format!("{}/{}.md", specs_dir, name);
                    let yaml_path = format!("{}/{}.yaml", specs_dir, name);
                    let md_exists = std::path::Path::new(&md_path).exists();
                    let yaml_exists = std::path::Path::new(&yaml_path).exists();
                    match (md_exists, yaml_exists) {
                        (true, true) => Some(format!("Invalid loop spec: ambiguous — both .md and .yaml exist for '{}'", name)),
                        (false, false) => Some(format!("Invalid loop spec: '{}' not found in {}", name, specs_dir)),
                        _ => None, // valid — one file found
                    }
                })
            });
            if let Some(err) = spec_error {
                Some(err)
            } else {
                let loop_spec_path = remaining.iter().find_map(|p| {
                    p.strip_prefix("loop_spec:").map(|name| {
                        let home = std::env::var("HOME").unwrap_or_default();
                        let specs_dir = format!("{}/dev/autoresearch/loop-specs", home);
                        let md_path = format!("{}/{}.md", specs_dir, name);
                        if std::path::Path::new(&md_path).exists() {
                            md_path
                        } else {
                            format!("{}/{}.yaml", specs_dir, name)
                        }
                    })
                });
                let prompt_parts: Vec<&str> = remaining.iter()
                    .filter(|p| !p.starts_with("loop_spec:"))
                    .copied()
                    .collect();
                let prompt = prompt_parts.join(" ");
                Some(
                    handle_delegate_command(state, _agent_name, room_id, &repo, &model, &prompt, loop_spec_path.as_deref(), matrix_client)
                        .await,
                )
            }
        }
        "/delegate" => Some(
            "Usage: `/delegate <repo> <model> <prompt>`".to_string(),
        ),
        "/loop" if parts.len() >= 3 && parts[1] == "start" => {
            let spec_path = parts[2];
            if spec_path.contains("..") {
                Some("Invalid spec path: must not contain '..'".to_string())
            } else {
                let home = std::env::var("HOME").unwrap_or_default();
                let allowed_dir = state.config.settings.loop_specs_dir.clone()
                    .unwrap_or_else(|| format!("{}/dev/autoresearch/loop-specs", home));
                let resolved = std::path::Path::new(spec_path);
                if resolved.is_absolute() && !resolved.starts_with(&allowed_dir) {
                    Some(format!("Invalid spec path: must be within {}", allowed_dir))
                } else {
                    match state.loop_manager.load_and_register(std::path::Path::new(spec_path)) {
                        Ok(loop_id) => {
                            let _ = state.loop_manager.start_loop(&loop_id);
                            Some(format!("Loop **{}** started from `{}`", loop_id, spec_path))
                        }
                        Err(e) => Some(format!("Failed to start loop: {}", e)),
                    }
                }
            }
        }
        "/loop" if parts.len() >= 3 && parts[1] == "abort" => {
            let loop_id = parts[2];
            match state.loop_manager.abort_loop(loop_id) {
                Ok(()) => Some(format!("Loop **{}** aborted", loop_id)),
                Err(e) => Some(format!("Failed to abort loop: {}", e)),
            }
        }
        "/loop" if parts.len() >= 2 && parts[1] == "status" => {
            let mut lines = vec!["**Active Loops**".to_string()];
            let mut any = false;
            for lp in state.loop_manager.all_loops() {
                any = true;
                lines.push(format!(
                    "- **{}** ({}) — iter {}/{} | status: {:?} | best: {}",
                    lp.loop_id,
                    lp.spec.agent_id,
                    lp.current_iteration,
                    lp.spec.budget.max_iterations,
                    lp.status,
                    lp.best_metric.map(|v| format!("{:.4}", v)).unwrap_or_else(|| "—".to_string()),
                ));
            }
            if !any {
                lines.push("No active loops.".to_string());
            }
            Some(lines.join("\n"))
        }
        "/loop" => Some("Usage: `/loop start <spec-path>` | `/loop status` | `/loop abort <loop-id>`".to_string()),
        _ => None, // Not a coordinator command — pass to agent
    };

    if let Some(msg) = response {
        let _ = matrix_client.send_message(room_id, &msg, None, None).await;
        true
    } else {
        false
    }
}

fn format_health_report(state: &mut CoordinatorState) -> String {
    let mut lines = vec!["**Agent Health Dashboard**".to_string(), String::new()];

    let agent_names: Vec<String> = state.sessions.keys().cloned().collect();
    for name in &agent_names {
        let session = state.sessions.get(name).unwrap();
        let mut proc = match session.process.try_lock() {
            Ok(p) => p,
            Err(_) => {
                lines.push(format!("| {} | 🔒 locked | — |", name));
                continue;
            }
        };

        let indicator = proc.health.get_status_indicator();
        let score = proc.health.get_score();
        let trust = TrustLevel::from_u8(session.config.trust_level.unwrap_or(2));
        let status = if proc.is_running() { "running" } else { "stopped" };

        lines.push(format!(
            "{} **{}** — {} score: {} | trust: {} | status: {}",
            indicator, name, indicator, score, trust.name(), status
        ));
    }

    lines.push(String::new());
    lines.push(format!(
        "Pending approvals: {}",
        state.pending_matrix_approvals.len()
    ));

    lines.join("\n")
}

fn format_status_report(state: &CoordinatorState) -> String {
    let mut lines = vec!["**Agent Status**".to_string(), String::new()];

    for (name, session) in &state.sessions {
        let uptime = session
            .last_response_at
            .map(|t| format!("{}s ago", t.elapsed().as_secs()))
            .unwrap_or_else(|| "never".to_string());

        let proc = match session.process.try_lock() {
            Ok(p) => p,
            Err(_) => {
                lines.push(format!("**{}** — 🔒 busy", name));
                continue;
            }
        };

        let session_id = proc
            .session_id
            .as_deref()
            .unwrap_or("none");

        lines.push(format!(
            "**{}** — session: `{}` | last response: {} | tools: {}",
            name, session_id, uptime, session.tool_call_count
        ));
    }

    lines.join("\n")
}

fn format_agent_list(state: &CoordinatorState) -> String {
    let mut lines = vec!["**Agents**".to_string(), String::new()];

    for (name, session) in &state.sessions {
        let trust = TrustLevel::from_u8(session.config.trust_level.unwrap_or(2));
        let proc = match session.process.try_lock() {
            Ok(p) => p,
            Err(_) => {
                lines.push(format!("- **{}** [{}] 🔒", name, trust.name()));
                continue;
            }
        };
        let status = if proc.is_running() { "✅" } else { "⬛" };
        lines.push(format!(
            "- {} **{}** [{}] — {}",
            status,
            name,
            trust.name(),
            session.config.description
        ));
    }

    lines.join("\n")
}

fn format_pending_approvals(state: &CoordinatorState) -> String {
    if state.pending_matrix_approvals.is_empty() {
        return "No pending approvals.".to_string();
    }

    let mut lines = vec!["**Pending Approvals**".to_string(), String::new()];
    for (event_id, p) in &state.pending_matrix_approvals {
        let age = p.created_at.elapsed().as_secs();
        lines.push(format!(
            "- `{}…` [{}] tool: `{}` — agent: {} — {}s ago",
            &event_id[..event_id.len().min(12)],
            p.request_id,
            p.tool_name,
            p.agent_name,
            age
        ));
    }
    lines.join("\n")
}

fn recover_agent(state: &mut CoordinatorState, agent_name: &str) -> String {
    if !state.sessions.contains_key(agent_name) {
        return format!("Unknown agent: `{}`", agent_name);
    }

    state.lifecycle.reset_circuit_breaker(agent_name);
    state.lifecycle.clear_trust_override(agent_name);
    state.approval_rate_limiter.reset(agent_name);

    if let Some(session) = state.sessions.get(agent_name) {
        if let Ok(mut proc) = session.process.try_lock() {
            proc.health.reset();
        }
    }

    info!("[{}] Agent recovered — circuit breaker reset, health cleared", agent_name);
    format!("Agent `{}` recovered — circuit breaker reset, health cleared, trust override removed.", agent_name)
}

async fn manual_approve(state: &mut CoordinatorState, prefix: &str, approved: bool) -> String {
    // Find pending approval by request_id prefix
    let matching: Vec<String> = state
        .pending_matrix_approvals
        .iter()
        .filter(|(_, p)| p.request_id.starts_with(prefix))
        .map(|(k, _)| k.clone())
        .collect();

    if matching.is_empty() {
        return format!("No pending approval matching `{}`", prefix);
    }
    if matching.len() > 1 {
        return format!(
            "Ambiguous prefix `{}` — matches {} approvals",
            prefix,
            matching.len()
        );
    }

    let event_id = &matching[0];
    if let Some(pending) = state.pending_matrix_approvals.remove(event_id) {
        if pending.fs_approval {
            // Filesystem hook approval — write .response file
            let decision_str = if approved { "allow" } else { "deny" };
            if let Err(e) = state.hmac_signer.write_approval_response(
                &state.approval_dir, &pending.request_id, decision_str,
            ) {
                error!("[{}] Failed to write fs approval response: {}", pending.agent_name, e);
            }
        } else if let Some(session) = state.sessions.get(&pending.agent_name) {
            let _ = session
                .approval_tx
                .try_send((pending.request_id.clone(), approved, None));
        }

        let action = if approved { "Approved" } else { "Denied" };
        format!(
            "{} `{}` for agent `{}`",
            action, pending.tool_name, pending.agent_name
        )
    } else {
        "Approval not found.".to_string()
    }
}

// ============================================================================
// Startup message (2E)
// ============================================================================

async fn send_startup_message(state: &CoordinatorState) {
    let token = match &state.coord_token {
        Some(t) => t.clone(),
        None => {
            warn!("No coord token — skipping startup message");
            return;
        }
    };

    let client = match MatrixClient::new(
        state.config.settings.pantalaimon_url.as_deref(),
        token,
        "@coord:matrix.org".to_string(),
    ) {
        Ok(c) => c,
        Err(e) => {
            warn!("Failed to build coord Matrix client: {}", e);
            return;
        }
    };

    let agent_count = state.sessions.len();
    let msg = format!("Whitebox online (coordinator-rs v{}, {} agents)", env!("CARGO_PKG_VERSION"), agent_count);

    match client.send_message(STATUS_ROOM_ID, &msg, None, None).await {
        Ok(_) => info!("Startup message sent to Status room"),
        Err(e) => warn!("Failed to send startup message: {}", e),
    }
}

// ============================================================================
// Signal handling
// ============================================================================

async fn wait_for_shutdown_signal() {
    use tokio::signal;

    let ctrl_c = async {
        signal::ctrl_c().await.expect("Failed to listen for ctrl_c");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to listen for SIGTERM")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => { info!("Received SIGINT"); }
        _ = terminate => { info!("Received SIGTERM"); }
    }
}

// ============================================================================
// Glob pattern matching (for auto-approve patterns like "ls *")
// ============================================================================

fn glob_match(pattern: &str, input: &str) -> bool {
    let pattern_parts: Vec<&str> = pattern.splitn(2, '*').collect();
    match pattern_parts.len() {
        1 => pattern == input,
        2 => input.starts_with(pattern_parts[0]) && input.ends_with(pattern_parts[1]),
        _ => false,
    }
}

// ============================================================================
// Phase 3E: Status HUD
// ============================================================================

async fn update_status_hud(state: &mut CoordinatorState) {
    let token = match &state.coord_token {
        Some(t) => t.clone(),
        None => return,
    };

    let client = match MatrixClient::new(
        state.config.settings.pantalaimon_url.as_deref(),
        token,
        "@coord:matrix.org".to_string(),
    ) {
        Ok(c) => c,
        Err(_) => return,
    };

    let mut lines = vec![
        format!(
            "**Whitebox Status HUD** (coordinator-rs v{})",
            env!("CARGO_PKG_VERSION")
        ),
        String::new(),
    ];

    // Agent status
    let agent_names: Vec<String> = state.sessions.keys().cloned().collect();
    for name in &agent_names {
        let session = state.sessions.get(name).unwrap();
        let trust = TrustLevel::from_u8(session.config.trust_level.unwrap_or(2));
        let (indicator, score) = match session.process.try_lock() {
            Ok(mut p) => (
                p.health.get_status_indicator().to_string(),
                p.health.get_score(),
            ),
            Err(_) => ("🔒".to_string(), -1),
        };
        let last_active = session
            .last_response_at
            .map(|t| format!("{}s ago", t.elapsed().as_secs()))
            .unwrap_or_else(|| "—".to_string());

        // Two trailing spaces = CommonMark hard line break (<br>), keeping
        // all agent rows in one paragraph rather than separate <p> blocks.
        lines.push(format!(
            "{} **{}** | {} | score:{} | last:{}  ",
            indicator,
            name,
            trust.name(),
            score,
            last_active
        ));
    }

    // Infra status
    lines.push(String::new());
    if let Some(ref health) = state.last_infra_health {
        lines.push(health.summary_line());
    } else {
        lines.push("Infra: not yet checked".to_string());
    }

    // Pending approvals
    let pending_count = state.pending_matrix_approvals.len();
    if pending_count > 0 {
        lines.push(format!("Pending approvals: {}", pending_count));
    }

    // LLM provider (from failover chain)
    {
        let provider = state.provider_chain.current();
        let metrics = state.provider_chain.get_metrics();
        let failures: u32 = metrics.iter().map(|m| m.consecutive_failures).sum();
        let active_idx = state.provider_chain.active_index();
        if active_idx > 0 || failures > 0 {
            lines.push(format!(
                "LLM: {} ({}) [failover idx={}, failures={}]",
                provider.name, provider.model, active_idx, failures
            ));
        } else {
            lines.push(format!("LLM: {} ({})", provider.name, provider.model));
        }
    }

    // Timestamp
    lines.push(String::new());
    {
        let now_utc = chrono::Utc::now();
        let now_et = now_utc.with_timezone(&chrono_tz::America::New_York);
        let et_label = now_et.format("%Z"); // "EDT" or "EST" automatically
        lines.push(format!(
            "_Updated: {} UTC / {} {}_",
            now_utc.format("%H:%M:%S"),
            now_et.format("%H:%M:%S"),
            et_label,
        ));
    }

    let hud_text = lines.join("\n");

    match &state.status_hud_event_id {
        Some(event_id) => {
            // Edit existing HUD message
            match client
                .edit_message(STATUS_ROOM_ID, event_id, &hud_text)
                .await
            {
                Ok(_) => debug!("HUD updated"),
                Err(e) => {
                    warn!("HUD edit failed, sending new: {}", e);
                    if let Ok(new_id) = client.send_message(STATUS_ROOM_ID, &hud_text, None, None).await {
                        state.status_hud_event_id = Some(new_id);
                    }
                }
            }
        }
        None => {
            // First HUD message
            match client.send_message(STATUS_ROOM_ID, &hud_text, None, None).await {
                Ok(event_id) => {
                    info!("Status HUD created: {}", event_id);
                    state.status_hud_event_id = Some(event_id);
                }
                Err(e) => warn!("Failed to create HUD: {}", e),
            }
        }
    }
}

// ============================================================================
// Phase 3F: Infrastructure health checks
// ============================================================================

async fn check_infra_health(state: &mut CoordinatorState) {
    let (health, alerts) = state.infra_checker.check().await;
    state.last_infra_health = Some(health);

    if alerts.is_empty() {
        return;
    }

    // Post alerts to STATUS_ROOM_ID
    let token = match &state.coord_token {
        Some(t) => t.clone(),
        None => return,
    };

    let client = match MatrixClient::new(
        state.config.settings.pantalaimon_url.as_deref(),
        token,
        "@coord:matrix.org".to_string(),
    ) {
        Ok(c) => c,
        Err(_) => return,
    };

    // Use a tight CommonMark list — each item on its own line in Element.
    let alert_msg = format!("**Infra Alert**\n\n{}", alerts.join("\n\n"));
    let _ = client.send_message(STATUS_ROOM_ID, &alert_msg, None, None).await;
}

// ============================================================================
// Phase 3I: Identity drift detection
// ============================================================================

fn hash_file(path: &std::path::Path) -> Option<String> {
    let content = std::fs::read(path).ok()?;
    Some(format!("{:x}", Sha256::digest(&content)))
}

fn compute_identity_hashes(config: &Config, home: &str) -> HashMap<String, String> {
    let mut hashes = HashMap::new();
    for (agent_name, agent_config) in &config.agents {
        if let Some(ref files) = agent_config.identity_files {
            let agent_base = PathBuf::from(
                agent_config.default_cwd.as_deref().unwrap_or(home)
            );
            for (label, relative_path) in [
                ("soul", &files.soul),
                ("principles", &files.principles),
                ("agents", &files.agents),
            ] {
                let full = agent_base.join(relative_path);
                if let Some(hash) = hash_file(&full) {
                    let key = format!("{}:{}", agent_name, label);
                    hashes.insert(key, hash);
                }
            }
        }
    }
    hashes
}

async fn check_identity_drift(state: &mut CoordinatorState) {
    let home = std::env::var("HOME").unwrap_or_default();
    let current = compute_identity_hashes(&state.config, &home);

    if state.identity_hashes.is_empty() {
        // First run — store baseline
        state.identity_hashes = current;
        info!("Identity baseline established ({} files)", state.identity_hashes.len());
        return;
    }

    let mut drifted = Vec::new();
    for (key, hash) in &current {
        match state.identity_hashes.get(key) {
            Some(old_hash) if old_hash != hash => {
                drifted.push(key.clone());
            }
            None => {
                drifted.push(format!("{} (new)", key));
            }
            _ => {}
        }
    }

    // Check for deleted files
    for key in state.identity_hashes.keys() {
        if !current.contains_key(key) {
            drifted.push(format!("{} (deleted)", key));
        }
    }

    if !drifted.is_empty() {
        warn!("Identity drift detected: {:?}", drifted);

        let token = match &state.coord_token {
            Some(t) => t.clone(),
            None => return,
        };

        let client = match MatrixClient::new(
            state.config.settings.pantalaimon_url.as_deref(),
            token,
            "@coord:matrix.org".to_string(),
        ) {
            Ok(c) => c,
            Err(_) => return,
        };

        let alert = format!(
            "**⚠️ Identity Drift Detected**\n{}",
            drifted
                .iter()
                .map(|d| format!("- `{}`", d))
                .collect::<Vec<_>>()
                .join("\n")
        );
        let _ = client.send_message(STATUS_ROOM_ID, &alert, None, None).await;
    }

    // Update baseline
    state.identity_hashes = current;
}

// ============================================================================
// Phase 3D: Timer firing
// ============================================================================

async fn check_and_fire_timers(state: &mut CoordinatorState) {
    let timer_dir = match &state.config.settings.timer_dir {
        Some(d) => d.clone(),
        None => return,
    };

    let fired = timer::check_timers(&timer_dir).await;

    for t in fired {
        // Check if agent session exists and is not busy
        let session = match state.sessions.get(&t.agent) {
            Some(s) => s,
            None => {
                warn!("Timer fired for unknown agent: {}", t.agent);
                continue;
            }
        };

        if session.processing_started_at.is_some() {
            debug!("[{}] Timer skipped — agent is busy", t.agent);
            continue;
        }

        info!("[{}] Injecting timer message to room {}", t.agent, t.room_id);
        let timeout_ms = state.config.settings.claude_timeout_ms;
        let result =
            send_to_agent(session, t.message.clone(), None, t.room_id.clone(), String::new(), timeout_ms).await;

        match result {
            Ok(res) => {
                if !res.result.trim().is_empty() && !is_suppressed_error(&res.result) {
                    let pantalaimon_url = state.config.settings.pantalaimon_url.clone();
                    let session = state.sessions.get(&t.agent).unwrap();
                    let client = MatrixClient::new(
                        pantalaimon_url.as_deref(),
                        session.matrix_token.clone(),
                        session.matrix_user_id.clone(),
                    );
                    if let Ok(c) = client {
                        let _ = c.send_message(&t.room_id, &res.result, None, None).await;
                    }
                } else if is_suppressed_error(&res.result) {
                    warn!("[{}] Suppressed CLI error in timer result: {}", t.agent, res.result);
                }
            }
            Err(e) => {
                warn!("[{}] Timer message failed: {}", t.agent, e);
            }
        }
    }
}

// ============================================================================
// Phase 3B: Inter-agent routing
// ============================================================================

fn check_inter_agent_routing(
    state: &mut CoordinatorState,
    sender_agent: &str,
    room_id: &str,
    response: &str,
    original_event: &MatrixEvent,
) -> Option<()> {
    // Check first line for >> @agentname pattern
    let first_line = response.lines().next()?;
    if !first_line.starts_with(">> @") {
        return None;
    }

    let target = first_line
        .strip_prefix(">> @")?
        .split_whitespace()
        .next()?;

    // Verify target agent exists
    if !state.sessions.contains_key(target) {
        debug!(
            "[{}] Routing target @{} not found, ignoring",
            sender_agent, target
        );
        return None;
    }

    // Check hop count
    let hop_key = original_event.event_id.clone();
    let hops = state.routing_hop_counts.entry(hop_key.clone()).or_insert(0);
    *hops += 1;

    if *hops > MAX_ROUTING_HOPS {
        warn!(
            "[{}] Routing hop limit ({}) reached for event {}",
            sender_agent, MAX_ROUTING_HOPS, original_event.event_id
        );
        return None;
    }

    info!(
        "[{}] Routing to @{} (hop {}/{})",
        sender_agent, target, hops, MAX_ROUTING_HOPS
    );

    // Build routing message with sender context
    let routing_msg = format!(
        "[Routed from @{} in {}]\n{}\n---\nOriginal: {}",
        sender_agent,
        room_id,
        response,
        original_event
            .content
            .get("body")
            .and_then(|b| b.as_str())
            .unwrap_or("")
    );

    // Queue the routing message — it'll be dispatched in the next poll cycle
    // by injecting it into the target agent's message channel
    let session = state.sessions.get(target)?;

    // Use try_send to avoid blocking — routing is best-effort
    let (result_tx, _result_rx) = tokio::sync::oneshot::channel();
    let msg = crate::agent::UserMessage {
        role: "user".to_string(),
        content: routing_msg,
        content_blocks: None,
        room_id: room_id.to_string(),
        event_id: original_event.event_id.clone(),
    };
    let _ = session.message_tx.try_send((msg, result_tx));

    Some(())
}

// ============================================================================
// Phase 3H: LLM provider failover
// ============================================================================

async fn check_llm_health(state: &mut CoordinatorState) {
    let provider_name = state.provider_chain.current().name.clone();
    let health_url = state.provider_chain.current().health_url.clone();

    let timeout_ms = state
        .config
        .settings
        .llm_health_check_timeout_ms
        .unwrap_or(10_000);

    let client = reqwest::Client::builder()
        .timeout(Duration::from_millis(timeout_ms))
        .build();

    let healthy = match client {
        Ok(c) => match c.get(&health_url).send().await {
            Ok(resp) => resp.status().is_success(),
            Err(e) => {
                debug!("LLM health check failed for {}: {}", provider_name, e);
                false
            }
        },
        Err(_) => false,
    };

    let event = state
        .provider_chain
        .record_health_check(&provider_name, healthy);

    match event {
        Some(crate::provider_chain::ProviderEvent::Failover {
            ref from,
            ref to,
            ref reason,
        }) => {
            warn!("LLM failover: {} -> {} ({})", from, to, reason);

            // Alert to STATUS_ROOM_ID
            if let Some(ref token) = state.coord_token {
                let client = MatrixClient::new(
                    state.config.settings.pantalaimon_url.as_deref(),
                    token.clone(),
                    "@coord:matrix.org".to_string(),
                );
                if let Ok(c) = client {
                    let alert = format!(
                        "**LLM Failover**\n`{}` -> `{}` ({})",
                        from, to, reason
                    );
                    let _ = c.send_message(STATUS_ROOM_ID, &alert, None, None).await;
                }
            }
        }
        Some(crate::provider_chain::ProviderEvent::Recovered { ref provider }) => {
            info!("LLM primary provider {} recovered — resetting to primary", provider);

            // Reset to primary and alert
            if let Some(crate::provider_chain::ProviderEvent::Failover {
                ref from,
                ref to,
                ..
            }) = state.provider_chain.reset_to_primary()
            {
                if let Some(ref token) = state.coord_token {
                    let client = MatrixClient::new(
                        state.config.settings.pantalaimon_url.as_deref(),
                        token.clone(),
                        "@coord:matrix.org".to_string(),
                    );
                    if let Ok(c) = client {
                        let alert = format!(
                            "**LLM Recovered**\n`{}` -> `{}` (primary healthy again)",
                            from, to
                        );
                        let _ = c.send_message(STATUS_ROOM_ID, &alert, None, None).await;
                    }
                }
            }
        }
        Some(crate::provider_chain::ProviderEvent::Exhausted { ref tried }) => {
            warn!("All LLM providers exhausted: {:?}", tried);

            if let Some(ref token) = state.coord_token {
                let client = MatrixClient::new(
                    state.config.settings.pantalaimon_url.as_deref(),
                    token.clone(),
                    "@coord:matrix.org".to_string(),
                );
                if let Ok(c) = client {
                    let alert = format!(
                        "**All LLM Providers Exhausted**\nTried: {}",
                        tried.join(", ")
                    );
                    let _ = c.send_message(STATUS_ROOM_ID, &alert, None, None).await;
                }
            }
        }
        None => {
            // No state change — normal health check pass/fail within retry threshold
        }
    }
}

// ============================================================================
// Phase 3C: Delegate command handler
// ============================================================================

async fn handle_delegate_command(
    state: &mut CoordinatorState,
    agent_name: &str,
    room_id: &str,
    repo: &str,
    model: &str,
    prompt: &str,
    loop_spec_path: Option<&str>,
    matrix_client: &MatrixClient,
) -> String {
    let _ = matrix_client
        .send_message(
            room_id,
            &format!(
                "_(Starting delegate session on {} — repo={} model={}{})_",
                state.config.settings.delegate_device, repo, model,
                loop_spec_path.map(|p| format!(" loop_spec={}", p)).unwrap_or_default()
            ),
            None,
            None,
        )
        .await;

    // Register loop if spec provided
    let loop_id = if let Some(spec_path) = loop_spec_path {
        match state.loop_manager.load_and_register(std::path::Path::new(spec_path)) {
            Ok(id) => {
                let _ = state.loop_manager.start_loop(&id);
                let _ = state.run_event_log.append_event(
                    &id, RunEventType::LoopStart, EventStream::System, EventLevel::Info,
                    &format!("Loop started: agent={} repo={}", agent_name, repo), None
                ).await;
                let _ = state.run_event_log.append_event(
                    &id, RunEventType::IterationStart, EventStream::System, EventLevel::Info,
                    "Iteration 1 started", None
                ).await;
                Some(id)
            }
            Err(e) => {
                return format!("Failed to load loop spec: {}", e);
            }
        }
    } else {
        None
    };

    // Compute timeout override from loop spec
    let timeout_override = loop_id.as_ref().and_then(|id| {
        state.loop_manager.get_loop(id).map(|lp| {
            Duration::from_secs(lp.spec.budget.wall_clock_minutes * 60)
        })
    });

    // Build final prompt — prepend Loop Spec path if provided
    let final_prompt = match loop_spec_path {
        Some(path) => format!(
            "Your Loop Spec is at: {}. Read it before executing any iteration.\n\n{}",
            path, prompt
        ),
        None => prompt.to_string(),
    };

    let config = state.config.clone();
    let auto_approve_tools: HashSet<String> = config
        .settings
        .delegate_auto_approve_tools
        .iter()
        .cloned()
        .collect();

    let result = delegate::run_delegate_session(
        &config,
        agent_name,
        repo,
        model,
        &final_prompt,
        loop_spec_path,
        timeout_override,
        &|tool_name, _tool_input| {
            auto_approve_tools.contains(tool_name)
        },
    )
    .await;

    // Completion signaling
    if let Some(ref loop_id) = loop_id {
        match &result {
            Ok(ref dr) if dr.success => {
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::IterationEnd, EventStream::System, EventLevel::Info,
                    "Iteration completed successfully",
                    dr.cost_usd.map(|c| serde_json::json!({"cost_usd": c}))
                ).await;
                let _ = state.loop_manager.complete_loop(loop_id);
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::LoopComplete, EventStream::System, EventLevel::Info,
                    "Loop completed", None
                ).await;
            }
            Ok(_) => {
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::IterationEnd, EventStream::System, EventLevel::Warn,
                    "Iteration ended with failure", None
                ).await;
                let _ = state.loop_manager.abort_loop(loop_id);
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::LoopAborted, EventStream::System, EventLevel::Warn,
                    "Loop aborted — delegate failed", None
                ).await;
            }
            Err(ref e) => {
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::IterationEnd, EventStream::System, EventLevel::Error,
                    &format!("Iteration error: {}", e), None
                ).await;
                let _ = state.loop_manager.abort_loop(loop_id);
                let _ = state.run_event_log.append_event(
                    loop_id, RunEventType::LoopAborted, EventStream::System, EventLevel::Error,
                    &format!("Loop aborted — error: {}", e), None
                ).await;
            }
        }
    }

    match result {
        Ok(delegate_result) => {
            let status = if delegate_result.success { "completed" } else { "failed" };
            let cost = delegate_result.cost_usd
                .map(|c| format!(" (${:.4})", c))
                .unwrap_or_default();
            if delegate_result.output.trim().is_empty() {
                format!("Delegate session {} {}", status, cost)
            } else {
                format!("**Delegate Result** ({}{})\n\n{}", status, cost, delegate_result.output)
            }
        }
        Err(e) => format!("Delegate session failed: {}", e),
    }
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

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn suppressed_error_catches_invalid_api_key() {
        assert!(is_suppressed_error("Invalid API key · Fix external API key"));
        assert!(is_suppressed_error("invalid api key provided"));
        assert!(is_suppressed_error("invalid_api_key"));
        assert!(is_suppressed_error("authentication_error from provider"));
        assert!(is_suppressed_error("fix external api key"));
        assert!(is_suppressed_error("HTTP 401 Unauthorized"));
    }

    #[test]
    fn suppressed_error_allows_normal_text() {
        assert!(!is_suppressed_error("Hello, how can I help?"));
        assert!(!is_suppressed_error("The API returned a 200 OK"));
        assert!(!is_suppressed_error(""));
        assert!(!is_suppressed_error("Error: file not found"));
        // 401 alone without "unauthorized" should pass through
        assert!(!is_suppressed_error("status code 401"));
    }

    #[test]
    fn retriable_inference_error_detection() {
        assert!(is_retriable_inference_error("Request timed out after 30s"));
        assert!(is_retriable_inference_error("Rate limit exceeded"));
        assert!(is_retriable_inference_error("API overloaded, try again"));
        assert!(is_retriable_inference_error("503 Service Unavailable"));
        assert!(is_retriable_inference_error("529 overloaded"));
        assert!(is_retriable_inference_error("model_not_available"));
        assert!(is_retriable_inference_error("Internal server error"));
        // Not retriable
        assert!(!is_retriable_inference_error("Invalid JSON in response"));
        assert!(!is_retriable_inference_error("file not found"));
        assert!(!is_retriable_inference_error("Hello, how can I help?"));
    }
}
