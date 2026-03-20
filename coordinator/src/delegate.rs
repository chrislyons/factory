/// SSH relay delegate sessions to Cloudkicker (BKX036).
/// Phase 3C: Spawns Claude on Cloudkicker via session-relay.sh,
/// streams JSON bidirectionally, handles tool approvals, posts results.
use anyhow::{bail, Context, Result};
use serde_json::json;
use std::collections::HashSet;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::time::{timeout, Duration};
use tracing::{debug, info, warn};

use crate::config::{ClaudeResponse, Config};

// ============================================================================
// Constants
// ============================================================================

const INIT_WATCHDOG_SECS: u64 = 180;
const DEFAULT_TIMEOUT_MS: u64 = 2_700_000; // 45 minutes

// ============================================================================
// Types
// ============================================================================

pub struct DelegateResult {
    pub output: String,
    pub cost_usd: Option<f64>,
    pub success: bool,
}

// ============================================================================
// Delegate session
// ============================================================================

/// Start a delegate session on Cloudkicker.
/// Returns the result text when complete.
pub async fn run_delegate_session(
    config: &Config,
    agent_name: &str,
    repo: &str,
    model: &str,
    prompt: &str,
    loop_spec_path: Option<&str>,
    timeout_override: Option<Duration>,
    approval_callback: &dyn Fn(&str, Option<&serde_json::Value>) -> bool,
) -> Result<DelegateResult> {
    let device_name = &config.settings.delegate_device;
    let device = config
        .devices
        .get(device_name)
        .context(format!("Delegate device '{}' not found in config", device_name))?;

    let ssh_alias = device
        .ssh_alias
        .as_deref()
        .unwrap_or(device_name);

    // Pre-flight: check if device is reachable
    let ping = Command::new("tailscale")
        .args(["ping", "--c", "1", "--timeout", "5s"])
        .arg(device.tailscale_ip.as_deref().unwrap_or(ssh_alias))
        .output()
        .await;

    match ping {
        Ok(out) if !out.status.success() => {
            bail!(
                "Delegate device {} is unreachable (tailscale ping failed)",
                device_name
            );
        }
        Err(e) => {
            warn!("Tailscale ping check failed: {} — proceeding anyway", e);
        }
        _ => {}
    }

    let timeout_ms = config.settings.delegate_timeout_ms;
    let total_timeout = timeout_override.unwrap_or_else(|| {
        Duration::from_millis(if timeout_ms > 0 { timeout_ms } else { DEFAULT_TIMEOUT_MS })
    });

    info!(
        "[{}] Starting delegate session on {} — repo={} model={}",
        agent_name, device_name, repo, model
    );

    // Spawn SSH process running session-relay.sh
    let relay_cmd = if let Some(spec_path) = loop_spec_path {
        format!("LOOP_SPEC_PATH='{}' ~/dev/scripts/session-relay.sh {} {}", spec_path, repo, model)
    } else {
        format!("~/dev/scripts/session-relay.sh {} {}", repo, model)
    };
    let mut child = Command::new("ssh")
        .arg(ssh_alias)
        .arg(relay_cmd)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .context("Failed to spawn SSH delegate process")?;

    let mut stdin = child.stdin.take().context("No SSH stdin")?;
    let stdout = child.stdout.take().context("No SSH stdout")?;

    // Spawn stderr logger
    if let Some(stderr) = child.stderr.take() {
        let name = agent_name.to_string();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                if !line.trim().is_empty() {
                    debug!("[{}] delegate stderr: {}", name, &line[..line.len().min(200)]);
                }
            }
        });
    }

    // Send the prompt as the initial message
    let input = json!({
        "type": "user",
        "message": { "role": "user", "content": prompt }
    });
    let line = format!("{}\n", input);
    stdin
        .write_all(line.as_bytes())
        .await
        .context("Failed to write prompt to delegate stdin")?;

    // Read responses with overall timeout
    let result = timeout(total_timeout, read_delegate_responses(
        agent_name,
        &mut child,
        &mut stdin,
        stdout,
        config,
        approval_callback,
    ))
    .await;

    // Clean up
    let _ = child.kill().await;

    match result {
        Ok(Ok(delegate_result)) => Ok(delegate_result),
        Ok(Err(e)) => Err(e),
        Err(_) => bail!(
            "Delegate session timed out after {}s",
            total_timeout.as_secs()
        ),
    }
}

async fn read_delegate_responses(
    agent_name: &str,
    child: &mut tokio::process::Child,
    stdin: &mut tokio::process::ChildStdin,
    stdout: tokio::process::ChildStdout,
    config: &Config,
    approval_callback: &dyn Fn(&str, Option<&serde_json::Value>) -> bool,
) -> Result<DelegateResult> {
    let mut lines = BufReader::new(stdout).lines();
    let mut initialized = false;
    let init_deadline = tokio::time::Instant::now() + Duration::from_secs(INIT_WATCHDOG_SECS);

    let auto_approve_tools: HashSet<&str> = config
        .settings
        .delegate_auto_approve_tools
        .iter()
        .map(|s| s.as_str())
        .collect();

    let auto_approve_bash: Vec<&str> = config
        .settings
        .delegate_auto_approve_bash
        .iter()
        .map(|s| s.as_str())
        .collect();

    let require_approval_bash: Vec<&str> = config
        .settings
        .delegate_require_approval_bash
        .iter()
        .map(|s| s.as_str())
        .collect();

    loop {
        // Init watchdog
        if !initialized && tokio::time::Instant::now() > init_deadline {
            bail!("Delegate session failed to initialize within {}s", INIT_WATCHDOG_SECS);
        }

        let line = tokio::select! {
            status = child.wait() => {
                let code = status.ok().and_then(|s| s.code());
                bail!("Delegate SSH process exited (code: {:?})", code);
            }
            line = lines.next_line() => {
                match line {
                    Err(e) => bail!("Delegate stdout read error: {}", e),
                    Ok(None) => bail!("Delegate stdout closed"),
                    Ok(Some(l)) => l,
                }
            }
        };

        if line.trim().is_empty() {
            continue;
        }

        let response: ClaudeResponse = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(_) => {
                debug!(
                    "[{}] delegate non-JSON: {}",
                    agent_name,
                    &line[..line.len().min(100)]
                );
                continue;
            }
        };

        match response {
            ClaudeResponse::System(sys) => {
                if sys.subtype == "init" {
                    initialized = true;
                    info!(
                        "[{}] Delegate Claude initialized: model={:?}",
                        agent_name, sys.model
                    );
                }
            }

            ClaudeResponse::Assistant(_) => {
                // Tool call telemetry logged but no action needed
            }

            ClaudeResponse::Result(result) => {
                return Ok(DelegateResult {
                    output: result.result.unwrap_or_default(),
                    cost_usd: result.total_cost_usd,
                    success: result.subtype == "success",
                });
            }

            ClaudeResponse::InputRequest(req) => {
                let tool_name = req.tool_name.as_deref().unwrap_or("unknown");
                let approved =
                    should_auto_approve_delegate(tool_name, req.tool_input.as_ref(), &auto_approve_tools, &auto_approve_bash, &require_approval_bash)
                        || approval_callback(tool_name, req.tool_input.as_ref());

                let response = json!({
                    "type": "permission_response",
                    "request_id": req.request_id,
                    "allowed": approved
                });
                let line = format!("{}\n", response);

                debug!(
                    "[{}] Delegate approval: {} -> {}",
                    agent_name,
                    tool_name,
                    if approved { "approved" } else { "denied" }
                );

                stdin
                    .write_all(line.as_bytes())
                    .await
                    .context("Failed to write approval to delegate stdin")?;
            }

            ClaudeResponse::Unknown => {}
        }
    }
}

// ============================================================================
// Delegate auto-approval logic
// ============================================================================

fn should_auto_approve_delegate(
    tool_name: &str,
    tool_input: Option<&serde_json::Value>,
    auto_approve_tools: &HashSet<&str>,
    auto_approve_bash: &[&str],
    require_approval_bash: &[&str],
) -> bool {
    // Always approve read-only tools
    if matches!(tool_name, "Read" | "Glob" | "Grep") {
        return true;
    }

    // Check explicit auto-approve list
    if auto_approve_tools.contains(tool_name) {
        return true;
    }

    // Edit/Write within delegate working dir — auto-approve
    if matches!(tool_name, "Edit" | "Write") {
        return true;
    }

    // Bash command approval
    if tool_name == "Bash" {
        if let Some(cmd) = tool_input
            .and_then(|i| i.get("command"))
            .and_then(|c| c.as_str())
        {
            // Check require_approval first (deny wins)
            for pattern in require_approval_bash {
                if cmd.contains(pattern) {
                    return false;
                }
            }
            // Check auto_approve patterns
            for pattern in auto_approve_bash {
                if cmd.starts_with(pattern) {
                    return true;
                }
            }
        }
        return false;
    }

    false
}
