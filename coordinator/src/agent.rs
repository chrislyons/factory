/// Claude subprocess lifecycle and stream-json I/O.
///
/// Each agent gets one persistent Claude process. The coordinator writes JSON to
/// stdin and reads newline-delimited JSON from stdout. Tool approval requests
/// (input_request) are forwarded to the approval module and Matrix.
use anyhow::{bail, Context, Result};
use serde_json::json;
use std::collections::HashSet;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::Duration;
use tracing::{debug, error, info, warn};

use crate::config::{
    AgentConfig, ClaudeResponse, Config, LLMProviderConfig,
};
use crate::health::HealthScorer;

// ============================================================================
// Constants
// ============================================================================

const CLAUDE_RESTART_DELAY_MS: u64 = 5_000;

// ============================================================================
// Message to Claude subprocess (written to stdin)
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct UserMessage {
    pub role: String,
    pub content: String,
    /// Structured content blocks for multimodal messages (images).
    /// When present, sent as `content` array instead of plain string.
    pub content_blocks: Option<serde_json::Value>,
    pub room_id: String,
    /// Matrix event_id of the triggering message (used as thread root for verbose activity).
    pub event_id: String,
}

/// Agent tool activity — sent to coordinator for verbose Matrix thread posts.
#[allow(dead_code)]
#[derive(Debug)]
pub struct AgentActivity {
    pub agent_name: String,
    pub room_id: String,
    pub thread_root_event_id: String,
    pub tool_names: Vec<String>,
    /// Claude's reasoning text blocks (narration before/between tool calls).
    pub text_blocks: Vec<String>,
}

// ============================================================================
// Result of a Claude session turn
// ============================================================================

#[allow(dead_code)]
#[derive(Debug)]
pub struct SessionResult {
    pub result: String,
    pub subtype: String, // "success" | "error"
    pub cost_usd: Option<f64>,
    pub session_id: Option<String>,
}

// ============================================================================
// Approval request — sent out of the agent task for the coordinator to handle
// ============================================================================

#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct ToolApprovalRequest {
    pub request_id: String,
    pub tool_name: Option<String>,
    pub tool_input: Option<serde_json::Value>,
    pub agent_name: String,
    pub room_id: String,
}

// ============================================================================
// AgentProcess — owns the Child and channels
// ============================================================================

#[allow(dead_code)]
pub struct AgentProcess {
    pub agent_name: String,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    /// Channel for sending completed session results back
    result_tx: Option<oneshot::Sender<Result<SessionResult>>>,
    /// Channel for inbound approval decisions
    approval_rx: Option<mpsc::Receiver<(String, bool, Option<String>)>>,
    pub session_id: Option<String>,
    pub is_ready: bool,
    pub health: HealthScorer,
    pub pending_approval_ids: HashSet<String>,
    /// Set to true when the subprocess emits system/init — used for bad-resume detection.
    pub init_received: bool,
}

impl AgentProcess {
    pub fn new(agent_name: &str, window_ms: u64) -> Self {
        Self {
            agent_name: agent_name.to_string(),
            child: None,
            stdin: None,
            result_tx: None,
            approval_rx: None,
            session_id: None,
            is_ready: false,
            health: HealthScorer::new(window_ms),
            pending_approval_ids: HashSet::new(),
            init_received: false,
        }
    }

    pub fn is_running(&self) -> bool {
        self.child.is_some() && self.is_ready
    }
}

// ============================================================================
// AgentSession — coordinator-facing handle for an agent
// ============================================================================

/// All per-agent state accessible from the coordinator poll loop.
#[allow(dead_code)]
pub struct AgentSession {
    pub name: String,
    pub config: AgentConfig,
    pub matrix_token: String,
    pub matrix_user_id: String,
    pub sync_token: Option<String>,
    pub sync_filter_id: Option<String>,
    pub rooms: HashSet<String>,

    /// Claude subprocess handle
    pub process: Arc<Mutex<AgentProcess>>,

    /// Channel for sending messages to the Claude subprocess task
    pub message_tx: mpsc::Sender<(UserMessage, oneshot::Sender<Result<SessionResult>>)>,

    /// Channel for sending approval decisions into the subprocess task
    pub approval_tx: mpsc::Sender<(String, bool, Option<String>)>,

    /// Channel for receiving approval requests from the subprocess task
    pub approval_request_rx: Arc<Mutex<mpsc::Receiver<ToolApprovalRequest>>>,

    /// Channel for receiving tool activity for verbose Matrix thread posts
    pub activity_rx: mpsc::UnboundedReceiver<AgentActivity>,

    /// Live status
    pub current_room_id: Option<String>,
    pub processing_started_at: Option<std::time::Instant>,
    pub last_response_at: Option<std::time::Instant>,
    pub last_tool_call: Option<String>,
    pub tool_call_count: u64,
    pub verbose_mode: bool,

    /// 5-char thread ID for the current turn (generated at dispatch)
    pub current_thread_id: Option<String>,
    /// Whether the thread header [id] has been posted for the current turn
    pub thread_header_posted: bool,
    /// Matrix event_id of the message that triggered this session — used as thread root for replies.
    pub current_thread_root_event_id: Option<String>,

    /// Whether the relay loop (Path A) already delivered res.result for this turn.
    /// When true, drain_agent_activity skips text_blocks to prevent duplicates.
    pub relay_delivered: bool,

    /// Last response content (for multi-agent context injection)
    pub last_response_text: Option<String>,

    /// Session ID from the last successful Claude turn (persisted across restarts for resume).
    pub last_session_id: Option<String>,
}

// ============================================================================
// Spawn the per-agent background task
// ============================================================================

/// Start an agent session. Returns the AgentSession handle.
/// Spawns a background tokio task that owns the Claude subprocess.
pub async fn start_agent_session(
    agent_name: &str,
    agent_config: AgentConfig,
    matrix_token: String,
    matrix_user_id: String,
    provider: &LLMProviderConfig,
    system_prompt: Option<&str>,
    working_dir: &str,
    health_window_ms: u64,
    shutdown_rx: tokio::sync::broadcast::Receiver<()>,
    resume_id: Option<String>,
) -> Result<AgentSession> {
    // message_tx -> message_rx: coordinator sends messages, task receives
    let (message_tx, message_rx) =
        mpsc::channel::<(UserMessage, oneshot::Sender<Result<SessionResult>>)>(8);
    // approval_tx -> approval_rx: coordinator sends approval decisions, task receives
    let (approval_tx, approval_rx) = mpsc::channel::<(String, bool, Option<String>)>(32);
    // approval_request_tx -> approval_request_rx: task sends requests, coordinator receives
    let (approval_request_tx, approval_request_rx) = mpsc::channel::<ToolApprovalRequest>(32);
    // activity_tx -> activity_rx: task sends tool activity, coordinator posts to Matrix threads
    let (activity_tx, activity_rx) = mpsc::unbounded_channel::<AgentActivity>();

    let process = Arc::new(Mutex::new(AgentProcess::new(agent_name, health_window_ms)));

    // Clone for the background task
    let name = agent_name.to_string();
    let prov = provider.clone();
    let prompt = system_prompt.map(|s| s.to_string());
    let cwd = working_dir.to_string();
    let proc_clone = process.clone();

    tokio::spawn(agent_task(
        name.clone(),
        prov,
        prompt,
        cwd,
        proc_clone,
        message_rx,
        approval_rx,
        approval_request_tx,
        activity_tx,
        health_window_ms,
        shutdown_rx,
        resume_id,
    ));

    let rooms = HashSet::new();

    Ok(AgentSession {
        name: agent_name.to_string(),
        config: agent_config,
        matrix_token,
        matrix_user_id,
        sync_token: None,
        sync_filter_id: None,
        rooms,
        process,
        message_tx,
        approval_tx,
        approval_request_rx: Arc::new(Mutex::new(approval_request_rx)),
        activity_rx,
        current_room_id: None,
        processing_started_at: None,
        last_response_at: None,
        last_tool_call: None,
        tool_call_count: 0,
        verbose_mode: false,
        current_thread_id: None,
        thread_header_posted: false,
        current_thread_root_event_id: None,
        relay_delivered: false,
        last_response_text: None,
        last_session_id: None,
    })
}

// ============================================================================
// Background task: owns Claude subprocess, handles I/O
// ============================================================================

async fn agent_task(
    agent_name: String,
    provider: LLMProviderConfig,
    system_prompt: Option<String>,
    working_dir: String,
    process: Arc<Mutex<AgentProcess>>,
    mut message_rx: mpsc::Receiver<(UserMessage, oneshot::Sender<Result<SessionResult>>)>,
    mut approval_rx: mpsc::Receiver<(String, bool, Option<String>)>,
    approval_request_tx: mpsc::Sender<ToolApprovalRequest>,
    activity_tx: mpsc::UnboundedSender<AgentActivity>,
    _health_window_ms: u64,
    mut shutdown_rx: tokio::sync::broadcast::Receiver<()>,
    resume_id: Option<String>,
) {
    // Track resume state across respawns — cleared on bad resume to avoid retry loops.
    let mut current_resume: Option<String> = resume_id;

    loop {
        // Spawn the Claude subprocess
        match spawn_claude(&agent_name, &provider, system_prompt.as_deref(), &working_dir, current_resume.as_deref()).await {
            Ok((mut child, stdin, stdout)) => {
                let spawn_instant = std::time::Instant::now();
                let was_resume = current_resume.is_some();
                {
                    let mut p = process.lock().await;
                    p.is_ready = true;
                    p.init_received = false; // reset for this spawn
                }
                info!("[{}] Claude session started ({}) resume={}", agent_name, provider.cli, was_resume);

                let result = run_session(
                    &agent_name,
                    &mut child,
                    stdin,
                    stdout,
                    &mut message_rx,
                    &mut approval_rx,
                    &approval_request_tx,
                    &activity_tx,
                    &process,
                    &mut shutdown_rx,
                )
                .await;

                // Snapshot init_received before clearing it
                let init_seen = process.lock().await.init_received;
                let elapsed = spawn_instant.elapsed();

                // Mark not ready
                {
                    let mut p = process.lock().await;
                    p.is_ready = false;
                    p.session_id = None;
                    p.child = None;
                    p.stdin = None;
                    p.init_received = false;
                }

                // Bad-resume detection: if we spawned with --resume and the process
                // exited within 10s without emitting system/init, the session ID is
                // stale (e.g. expired cloud session or local model). Respawn fresh.
                if was_resume && elapsed < Duration::from_secs(10) && !init_seen {
                    warn!(
                        "[{}] --resume failed (quick exit in {:.1}s without init) — respawning fresh",
                        agent_name, elapsed.as_secs_f32()
                    );
                    current_resume = None;
                    tokio::time::sleep(Duration::from_millis(CLAUDE_RESTART_DELAY_MS)).await;
                    continue;
                }

                // After a successful resume, clear current_resume so subsequent respawns start fresh.
                // (The session's context is already in-memory once init is seen.)
                if was_resume && init_seen {
                    current_resume = None;
                }

                match result {
                    SessionEnd::Shutdown => {
                        info!("[{}] Agent task shutting down", agent_name);
                        return;
                    }
                    SessionEnd::ProcessExited(code) => {
                        if code == Some(0) {
                            info!("[{}] Claude exited cleanly, stopping agent task", agent_name);
                            return;
                        }
                        warn!(
                            "[{}] Claude exited unexpectedly (code {:?}), restarting in {}ms",
                            agent_name, code, CLAUDE_RESTART_DELAY_MS
                        );
                        tokio::time::sleep(Duration::from_millis(CLAUDE_RESTART_DELAY_MS)).await;
                    }
                    SessionEnd::Error(e) => {
                        error!("[{}] Session error: {}", agent_name, e);
                        tokio::time::sleep(Duration::from_millis(CLAUDE_RESTART_DELAY_MS)).await;
                    }
                }
            }
            Err(e) => {
                error!("[{}] Failed to spawn Claude: {:#}", agent_name, e);
                tokio::time::sleep(Duration::from_millis(CLAUDE_RESTART_DELAY_MS * 2)).await;
            }
        }
    }
}

#[derive(Debug)]
enum SessionEnd {
    Shutdown,
    ProcessExited(Option<i32>),
    Error(anyhow::Error),
}

async fn run_session(
    agent_name: &str,
    child: &mut Child,
    mut stdin: ChildStdin,
    stdout: ChildStdout,
    message_rx: &mut mpsc::Receiver<(UserMessage, oneshot::Sender<Result<SessionResult>>)>,
    approval_rx: &mut mpsc::Receiver<(String, bool, Option<String>)>,
    approval_request_tx: &mpsc::Sender<ToolApprovalRequest>,
    activity_tx: &mpsc::UnboundedSender<AgentActivity>,
    process: &Arc<Mutex<AgentProcess>>,
    shutdown_rx: &mut tokio::sync::broadcast::Receiver<()>,
) -> SessionEnd {
    let mut lines = BufReader::new(stdout).lines();

    // State for the current in-flight request
    let mut current_result_tx: Option<oneshot::Sender<Result<SessionResult>>> = None;
    let mut pending_approval_ids: HashSet<String> = HashSet::new();
    // Track current message context for verbose thread posts
    let mut current_room_id = String::new();
    let mut current_thread_root = String::new();

    loop {
        tokio::select! {
            // Shutdown signal
            _ = shutdown_rx.recv() => {
                info!("[{}] Shutdown signal received, terminating Claude", agent_name);
                let _ = child.kill().await;
                return SessionEnd::Shutdown;
            }

            // Process exited
            status = child.wait() => {
                let code = status.ok().and_then(|s| s.code());
                if let Some(tx) = current_result_tx.take() {
                    let _ = tx.send(Err(anyhow::anyhow!("Claude process exited")));
                }
                return SessionEnd::ProcessExited(code);
            }

            // Incoming message from coordinator
            msg = message_rx.recv() => {
                match msg {
                    None => return SessionEnd::Shutdown,
                    Some((user_msg, result_tx)) => {
                        // Reject if another request is in flight
                        if current_result_tx.is_some() {
                            let _ = result_tx.send(Err(anyhow::anyhow!(
                                "Agent {} is busy processing another message", agent_name
                            )));
                            continue;
                        }

                        // Track context for verbose thread posts
                        current_room_id = user_msg.room_id.clone();
                        current_thread_root = user_msg.event_id.clone();

                        // Use content_blocks for multimodal, plain string for text
                        let message_content = if let Some(ref blocks) = user_msg.content_blocks {
                            blocks.clone()
                        } else {
                            json!(user_msg.content)
                        };
                        let input = json!({
                            "type": "user",
                            "message": { "role": "user", "content": message_content }
                        });
                        let line = format!("{}\n", input);

                        if let Err(e) = stdin.write_all(line.as_bytes()).await {
                            let _ = result_tx.send(Err(anyhow::anyhow!("Failed to write to Claude stdin: {}", e)));
                            return SessionEnd::Error(e.into());
                        }

                        current_result_tx = Some(result_tx);
                    }
                }
            }

            // Approval decision from coordinator — write permission response to Claude stdin
            decision = approval_rx.recv() => {
                if let Some((request_id, approved, note)) = decision {
                    pending_approval_ids.remove(&request_id);

                    // Inject coordinator note into Claude's context before permission_response
                    if let Some(ref note_content) = note {
                        let note_msg = json!({
                            "type": "user",
                            "message": {"role": "user", "content": note_content}
                        });
                        let line = format!("{}\n", note_msg);
                        if let Err(e) = stdin.write_all(line.as_bytes()).await {
                            error!("[{}] Failed to write coordinator note: {}", agent_name, e);
                            return SessionEnd::Error(e.into());
                        }
                    }

                    let response = json!({
                        "type": "permission_response",
                        "request_id": request_id,
                        "allowed": approved
                    });
                    let line = format!("{}\n", response);

                    debug!("[{}] Writing approval response: {} -> {}", agent_name, request_id, approved);
                    if let Err(e) = stdin.write_all(line.as_bytes()).await {
                        error!("[{}] Failed to write approval to stdin: {}", agent_name, e);
                        return SessionEnd::Error(e.into());
                    }
                }
            }

            // Line from Claude stdout
            line = lines.next_line() => {
                match line {
                    Err(e) => return SessionEnd::Error(e.into()),
                    Ok(None) => return SessionEnd::ProcessExited(None),
                    Ok(Some(line)) => {
                        if line.trim().is_empty() { continue; }

                        let response: ClaudeResponse = match serde_json::from_str(&line) {
                            Ok(r) => r,
                            Err(_) => {
                                debug!("[{}] Claude non-JSON: {}", agent_name, &line[..line.len().min(100)]);
                                continue;
                            }
                        };

                        match response {
                            ClaudeResponse::System(sys) => {
                                if sys.subtype == "init" {
                                    let sid = sys.session_id.clone();
                                    let mut p = process.lock().await;
                                    p.session_id = sid.clone();
                                    p.init_received = true;
                                    info!("[{}] Claude initialized: model={:?} session={:?}",
                                        agent_name, sys.model, sid);
                                }
                            }

                            ClaudeResponse::Assistant(msg) => {
                                // Collect tool names for telemetry + verbose thread posts
                                let tool_names: Vec<String> = msg.message.content.iter()
                                    .filter(|b| b.block_type == "tool_use")
                                    .filter_map(|b| b.name.clone())
                                    .collect();
                                let text_blocks: Vec<String> = msg.message.content.iter()
                                    .filter(|b| b.block_type == "text" || b.block_type == "thinking")
                                    .filter_map(|b| b.text.clone())
                                    .filter(|t| !t.trim().is_empty())
                                    .collect();
                                for name in &tool_names {
                                    debug!("[{}] Tool call: {}", agent_name, name);
                                }
                                // Send activity to coordinator for Matrix thread posting.
                                // Post text/thinking blocks whenever present (including reasoning-only
                                // turns with no tool calls — extended thinking output).
                                if !current_thread_root.is_empty() && (!tool_names.is_empty() || !text_blocks.is_empty()) {
                                    let _ = activity_tx.send(AgentActivity {
                                        agent_name: agent_name.to_string(),
                                        room_id: current_room_id.clone(),
                                        thread_root_event_id: current_thread_root.clone(),
                                        tool_names,
                                        text_blocks,
                                    });
                                }
                            }

                            ClaudeResponse::Result(result) => {
                                if let Some(tx) = current_result_tx.take() {
                                    let res = SessionResult {
                                        result: result.result.unwrap_or_default(),
                                        subtype: result.subtype,
                                        cost_usd: result.total_cost_usd,
                                        session_id: result.session_id,
                                    };
                                    let _ = tx.send(Ok(res));
                                }
                            }

                            ClaudeResponse::InputRequest(req) => {
                                let request_id = req.request_id.clone();

                                // Forward approval request to coordinator for decision.
                                // Decision will arrive via approval_rx and be written to stdin there.
                                let approval_req = ToolApprovalRequest {
                                    request_id: request_id.clone(),
                                    tool_name: req.tool_name.clone(),
                                    tool_input: req.tool_input.clone(),
                                    agent_name: agent_name.to_string(),
                                    room_id: String::new(), // coordinator fills from current_room_id
                                };

                                if approval_request_tx.send(approval_req).await.is_err() {
                                    warn!("[{}] approval_request_tx closed, auto-denying {}", agent_name, request_id);
                                    let deny = json!({
                                        "type": "permission_response",
                                        "request_id": request_id,
                                        "allowed": false
                                    });
                                    let line = format!("{}\n", deny);
                                    if let Err(e) = stdin.write_all(line.as_bytes()).await {
                                        return SessionEnd::Error(e.into());
                                    }
                                }
                            }

                            ClaudeResponse::Unknown => {
                                debug!("[{}] Unknown Claude response type", agent_name);
                            }
                        }
                    }
                }
            }
        }
    }
}

// ============================================================================
// Spawn Claude subprocess
// ============================================================================

async fn spawn_claude(
    agent_name: &str,
    provider: &LLMProviderConfig,
    system_prompt: Option<&str>,
    working_dir: &str,
    resume_id: Option<&str>,
) -> Result<(Child, ChildStdin, ChildStdout)> {
    let mut args = vec![
        "--input-format".to_string(),
        "stream-json".to_string(),
        "--output-format".to_string(),
        "stream-json".to_string(),
        "--permission-mode".to_string(),
        "delegate".to_string(),
        "--verbose".to_string(),
        "--model".to_string(),
        provider.model.clone(),
    ];

    // Resume an existing Claude session if an ID was saved from a previous run.
    // On failure (quick exit without init), agent_task will retry without --resume.
    if let Some(id) = resume_id {
        args.push("--resume".to_string());
        args.push(id.to_string());
    }

    if let Some(prompt) = system_prompt {
        args.push("--append-system-prompt".to_string());
        args.push(prompt.to_string());
    }

    let mut cmd = Command::new(&provider.cli);
    cmd.args(&args)
        .current_dir(working_dir)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(false);

    // Provider-specific env overrides (e.g. ANTHROPIC_BASE_URL for greybox)
    for (k, v) in &provider.env {
        cmd.env(k, v);
    }

    let mut child = cmd.spawn().context(format!(
        "Failed to spawn Claude ({}) for agent {}",
        provider.cli, agent_name
    ))?;

    let stdin = child.stdin.take().context("No stdin")?;
    let stdout = child.stdout.take().context("No stdout")?;

    // Spawn stderr logger
    if let Some(stderr) = child.stderr.take() {
        let name = agent_name.to_string();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                if !line.trim().is_empty() {
                    debug!("[{}] Claude stderr: {}", name, &line[..line.len().min(200)]);
                }
            }
        });
    }

    Ok((child, stdin, stdout))
}

// ============================================================================
// Send a message to an agent and wait for the result
// ============================================================================

pub async fn send_to_agent(
    session: &AgentSession,
    content: String,
    content_blocks: Option<serde_json::Value>,
    room_id: String,
    event_id: String,
    timeout_ms: u64,
) -> Result<SessionResult> {
    let (result_tx, result_rx) = oneshot::channel();
    let msg = UserMessage {
        role: "user".to_string(),
        content,
        content_blocks,
        room_id,
        event_id,
    };

    session
        .message_tx
        .send((msg, result_tx))
        .await
        .context("Failed to send message to agent (channel closed)")?;

    match tokio::time::timeout(Duration::from_millis(timeout_ms), result_rx).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => bail!("Agent result channel closed unexpectedly"),
        Err(_) => bail!("Agent response timed out after {}ms", timeout_ms),
    }
}

// ============================================================================
// Identity / system prompt construction
// ============================================================================

/// Build the system prompt from identity files (soul + principles + agents).
///
/// When a loop is active for the agent, callers should append the output of
/// [`build_loop_context`] to the returned string before passing it to
/// `--append-system-prompt`. This injects loop constraints (frozen/mutable
/// surfaces, budget, metric state) into the agent's context.
pub fn build_system_prompt(
    _agent_name: &str,
    config: &AgentConfig,
    base_dir: &std::path::Path,
) -> String {
    if let Some(ref files) = config.identity_files {
        let soul = crate::config::read_identity(base_dir, &files.soul).unwrap_or_default();
        let principles =
            crate::config::read_identity(base_dir, &files.principles).unwrap_or_default();
        let agents = crate::config::read_identity(base_dir, &files.agents).unwrap_or_default();
        format!("{}\n\n{}\n\n{}", soul, principles, agents)
    } else if let Some(ref prompt) = config.system_prompt {
        prompt.clone()
    } else {
        String::new()
    }
}

/// Build the loop constraint block for --append-system-prompt injection.
/// Returns None if no active loop exists for the agent.
pub fn build_loop_context(loop_info: Option<&crate::loop_engine::ActiveLoop>) -> Option<String> {
    let active = loop_info?;
    let spec = &active.spec;
    let best_str = match active.best_metric {
        Some(v) => format!("{:.4}", v),
        None => "none yet".to_string(),
    };
    let frozen_list = spec
        .frozen_harness
        .iter()
        .map(|p| format!("  - {}", p))
        .collect::<Vec<_>>()
        .join("\n");
    let mutable_list = spec
        .mutable_surface
        .iter()
        .map(|p| format!("  - {}", p))
        .collect::<Vec<_>>()
        .join("\n");

    Some(format!(
        "\n## LOOP CONSTRAINTS (enforced by coordinator)\n\
        Loop: {} | Iteration: {}/{}\n\
        Objective: {}\n\
        Metric: {} (baseline: {:.4}, best so far: {})\n\n\
        FROZEN — do NOT modify:\n{}\n\n\
        MUTABLE — you may ONLY modify:\n{}\n\n\
        Budget: {} per iteration\n",
        active.loop_id,
        active.current_iteration,
        spec.budget.max_iterations,
        spec.objective,
        spec.metric.name,
        spec.metric.baseline,
        best_str,
        frozen_list,
        mutable_list,
        spec.budget.per_iteration,
    ))
}

/// Resolve the working directory for an agent from room config.
pub fn resolve_working_dir(agent_name: &str, config: &Config) -> String {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
    for room in config.rooms.values() {
        let is_agent_room = room.default_agent.as_deref() == Some(agent_name)
            || room.agents.iter().any(|a| a == agent_name);
        if is_agent_room {
            if let Some(ref cwd) = room.worker_cwd {
                // Expand ~ to $HOME (tilde is a shell feature, not handled by Command::current_dir)
                let expanded = if cwd.starts_with("~/") {
                    format!("{}/{}", home, &cwd[2..])
                } else if cwd == "~" {
                    home.clone()
                } else {
                    cwd.clone()
                };
                // Only use if directory actually exists on this machine
                if std::path::Path::new(&expanded).is_dir() {
                    return expanded;
                }
            }
        }
    }
    // Agent default_cwd fallback (before $HOME)
    if let Some(agent_cfg) = config.agents.get(agent_name) {
        if let Some(ref dcwd) = agent_cfg.default_cwd {
            if std::path::Path::new(dcwd.as_str()).is_dir() {
                return dcwd.clone();
            }
        }
    }
    home
}
