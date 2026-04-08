/// Hermes agent runtime adapter.
///
/// Phase 3: Subprocess mode — parses plain-text Hermes output into SessionResult.
/// Phase 4: HTTP mode — talks to `hermes serve` via OpenAI-compatible API.
use anyhow::{Context, Result};
use serde::Deserialize;
use tracing::warn;

use crate::agent::SessionResult;

// ============================================================================
// Phase 3: Subprocess output parsing
// ============================================================================

/// Parse Hermes non-interactive stdout into a SessionResult.
/// In subprocess mode, Hermes writes markdown text to stdout — no structured
/// JSON protocol like Claude CLI's stream-json.
///
/// When Hermes `-Q` mode emits a trailing `session_id: <value>` line, we
/// extract it for resume-chain dispatch and strip it from the response body.
pub fn parse_hermes_output(raw: &str) -> SessionResult {
    let trimmed = raw.trim();

    // Check for trailing `session_id: <value>` line
    let (body, session_id) = if let Some(last_line) = trimmed.lines().last() {
        let stripped = last_line.trim();
        if let Some(sid) = stripped.strip_prefix("session_id: ") {
            let sid = sid.trim();
            if !sid.is_empty() {
                // Strip the session_id line from the body
                let body = trimmed
                    .lines()
                    .take(trimmed.lines().count().saturating_sub(1))
                    .collect::<Vec<_>>()
                    .join("\n");
                (body.trim_end().to_string(), Some(sid.to_string()))
            } else {
                (trimmed.to_string(), None)
            }
        } else {
            (trimmed.to_string(), None)
        }
    } else {
        (trimmed.to_string(), None)
    };

    let subtype = if body.is_empty() { "error" } else { "success" };
    SessionResult {
        result: body,
        subtype: subtype.to_string(),
        cost_usd: None,
        session_id,
    }
}

// ============================================================================
// Phase 4: OpenAI-compatible usage parsing (stub)
// ============================================================================

/// Token usage from OpenAI-compatible `/v1/chat/completions` response.
#[derive(Debug, Deserialize)]
pub struct OpenAIUsage {
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub total_tokens: u64,
}

pub fn convert_usage(usage: &OpenAIUsage) -> (u64, u64) {
    (usage.prompt_tokens, usage.completion_tokens)
}

// ============================================================================
// Phase 4: OpenAI-compatible tool_calls parsing (Bug-C2)
// ============================================================================

/// A structured tool call extracted from a Hermes/OpenAI-compatible response.
///
/// Phase 3 of FCT055 only logs these rather than wiring them into the tool
/// approval pipeline. That wiring is tracked as a follow-up.
#[derive(Debug, Clone, PartialEq)]
pub struct HermesToolCall {
    pub id: String,
    pub name: String,
    /// Raw arguments string. OpenAI delivers this as a JSON-encoded string
    /// even though it represents a JSON object; we preserve verbatim.
    pub arguments: String,
}

/// Extract the `tool_calls` array from a parsed OpenAI-compatible
/// `/v1/chat/completions` response body. Returns an empty vec if the
/// field is absent, null, or malformed.
pub fn parse_tool_calls(parsed: &serde_json::Value) -> Vec<HermesToolCall> {
    let arr = match parsed["choices"][0]["message"]["tool_calls"].as_array() {
        Some(a) => a,
        None => return Vec::new(),
    };

    let mut out = Vec::with_capacity(arr.len());
    for tc in arr {
        let id = tc["id"].as_str().unwrap_or("").to_string();
        let name = tc["function"]["name"].as_str().unwrap_or("").to_string();
        // OpenAI spec: arguments is a stringified JSON. Some providers ship
        // a pre-parsed object; handle both defensively.
        let arguments = if let Some(s) = tc["function"]["arguments"].as_str() {
            s.to_string()
        } else if !tc["function"]["arguments"].is_null() {
            tc["function"]["arguments"].to_string()
        } else {
            String::new()
        };

        // Skip entries missing both id and name — nothing usable.
        if id.is_empty() && name.is_empty() {
            continue;
        }
        out.push(HermesToolCall { id, name, arguments });
    }
    out
}

// ============================================================================
// Phase 4: Hermes profile config resolution (Bug-C1)
// ============================================================================

/// Shape of the tiny subset of `~/.hermes/profiles/<profile>/config.yaml`
/// we care about. We only need the `model` field; everything else is ignored.
#[derive(Debug, Deserialize)]
struct HermesProfileConfig {
    #[serde(default)]
    model: Option<String>,
}

/// Parse a Hermes profile YAML string and return the `model` field.
/// Returns `Err` if the YAML is malformed or if `model` is missing/empty.
pub fn parse_profile_model(yaml_text: &str) -> Result<String> {
    let cfg: HermesProfileConfig = serde_yaml::from_str(yaml_text)
        .context("Failed to parse Hermes profile YAML")?;
    let model = cfg.model.unwrap_or_default();
    if model.trim().is_empty() {
        anyhow::bail!("Hermes profile YAML is missing `model` field");
    }
    Ok(model)
}

/// Resolve the `model` field from `~/.hermes/profiles/<profile>/config.yaml`.
/// On any IO/parse error, returns `Err` — callers decide fallback behavior.
pub fn resolve_profile_model(profile: &str) -> Result<String> {
    let home = std::env::var("HOME").context("HOME env var not set")?;
    let path = std::path::PathBuf::from(home)
        .join(".hermes")
        .join("profiles")
        .join(profile)
        .join("config.yaml");
    let text = std::fs::read_to_string(&path)
        .with_context(|| format!("Failed to read Hermes profile config at {}", path.display()))?;
    parse_profile_model(&text)
}

// ============================================================================
// Phase 4: HTTP client for `hermes serve` mode (stub)
// ============================================================================

/// HTTP client for a Hermes instance running in `hermes serve --port N` mode.
/// Phase 4 only — Phase 3 uses subprocess I/O via spawn_hermes().
pub struct HermesHttpClient {
    port: u16,
    client: reqwest::Client,
    /// Model ID to forward in the OpenAI `model` field. Resolved once at
    /// construction from the Hermes profile config, falling back to the
    /// profile name if the config is missing or malformed (Bug-C1).
    model: String,
}

impl HermesHttpClient {
    /// Construct a client bound to a Hermes daemon on `port`, resolving the
    /// model ID from `~/.hermes/profiles/<profile>/config.yaml`. On resolve
    /// failure, logs a warning and falls back to using the profile name as
    /// the model ID (preserving prior buggy behavior for safe rollout).
    pub fn new(port: u16, profile: &str) -> Self {
        let model = match resolve_profile_model(profile) {
            Ok(m) => m,
            Err(e) => {
                warn!(
                    "Hermes profile '{}' model resolution failed ({:#}); falling back to profile name as model ID. This is a degraded mode — please fix ~/.hermes/profiles/{}/config.yaml.",
                    profile, e, profile
                );
                profile.to_string()
            }
        };
        Self {
            port,
            model,
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .expect("Failed to build Hermes HTTP client"),
        }
    }

    /// Returns the model ID this client will forward to the Hermes daemon.
    pub fn model(&self) -> &str {
        &self.model
    }

    /// Check if the daemon is reachable. GET /health with 5s timeout.
    pub async fn health_check(&self) -> Result<()> {
        let url = format!("http://127.0.0.1:{}/health", self.port);
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()?;
        let resp = client.get(&url).send().await
            .context("Hermes daemon health check failed")?;
        if resp.status().is_success() {
            Ok(())
        } else {
            anyhow::bail!("Hermes daemon returned HTTP {}", resp.status())
        }
    }

    /// Send a chat message to Hermes serve endpoint.
    /// Returns (response_text, tool_calls, usage).
    ///
    /// The `model` field in the request body is sourced from the profile
    /// config (Bug-C1 fix) — no caller override.
    pub async fn chat(
        &self,
        message: &str,
        system_prompt: Option<&str>,
    ) -> Result<(String, Vec<HermesToolCall>, OpenAIUsage)> {
        let url = format!("http://127.0.0.1:{}/v1/chat/completions", self.port);
        let mut messages = Vec::new();
        if let Some(sp) = system_prompt {
            messages.push(serde_json::json!({"role": "system", "content": sp}));
        }
        messages.push(serde_json::json!({"role": "user", "content": message}));
        let body = serde_json::json!({
            "model": self.model,
            "messages": messages,
        });

        let resp = self
            .client
            .post(&url)
            .json(&body)
            .send()
            .await
            .context("Hermes HTTP request failed")?;

        let status = resp.status();
        let text = resp.text().await.context("Failed to read Hermes response body")?;

        if !status.is_success() {
            // Bug-C3: log the full body (not truncated) at error! level so
            // post-mortems don't require correlating against hermes-*.log by
            // hand. The bail message keeps a short preview for the warn!
            // fallback chain in agent.rs.
            tracing::error!(
                "Hermes HTTP {} response body (model={}): {}",
                status, self.model, text
            );
            anyhow::bail!(
                "Hermes returned HTTP {} (model={}): {}",
                status,
                self.model,
                &text[..text.len().min(500)]
            );
        }

        let parsed: serde_json::Value =
            serde_json::from_str(&text).context("Failed to parse Hermes JSON response")?;

        let content = parsed["choices"][0]["message"]["content"]
            .as_str()
            .unwrap_or("")
            .to_string();

        // Bug-C2: previously dropped. Now extracted and forwarded so the
        // coordinator can at least log them for diagnostics.
        let tool_calls = parse_tool_calls(&parsed);

        let usage: OpenAIUsage = serde_json::from_value(
            parsed["usage"].clone(),
        )
        .unwrap_or(OpenAIUsage {
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
        });

        Ok((content, tool_calls, usage))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_hermes_output_success() {
        let result = parse_hermes_output("Here is my response.\nWith multiple lines.");
        assert_eq!(result.subtype, "success");
        assert_eq!(result.result, "Here is my response.\nWith multiple lines.");
        assert!(result.session_id.is_none());
    }

    #[test]
    fn test_parse_hermes_output_with_session_id() {
        let raw = "Here is my response.\nWith details.\nsession_id: abc-123-def";
        let result = parse_hermes_output(raw);
        assert_eq!(result.subtype, "success");
        assert_eq!(result.result, "Here is my response.\nWith details.");
        assert_eq!(result.session_id.as_deref(), Some("abc-123-def"));
    }

    #[test]
    fn test_parse_hermes_output_session_id_only() {
        // Edge case: output is just the session_id line
        let raw = "session_id: xyz-789";
        let result = parse_hermes_output(raw);
        assert_eq!(result.subtype, "error"); // empty body
        assert_eq!(result.result, "");
        assert_eq!(result.session_id.as_deref(), Some("xyz-789"));
    }

    #[test]
    fn test_parse_hermes_output_empty() {
        let result = parse_hermes_output("  \n  ");
        assert_eq!(result.subtype, "error");
        assert!(result.result.is_empty());
    }

    #[test]
    fn test_convert_usage() {
        let usage = OpenAIUsage {
            prompt_tokens: 100,
            completion_tokens: 50,
            total_tokens: 150,
        };
        let (input, output) = convert_usage(&usage);
        assert_eq!(input, 100);
        assert_eq!(output, 50);
    }

    // ------------------------------------------------------------------
    // Bug-C1 — profile model resolution
    // ------------------------------------------------------------------

    #[test]
    fn test_parse_profile_model_ok() {
        let yaml = r#"
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
base_url: http://127.0.0.1:41961/v1
provider: custom
toolsets: [terminal, file, code_execution]
"#;
        let model = parse_profile_model(yaml).expect("should parse");
        assert_eq!(model, "/Users/nesbitt/models/gemma-4-e4b-it-6bit");
    }

    #[test]
    fn test_parse_profile_model_missing_field_errors() {
        let yaml = r#"
base_url: http://127.0.0.1:41961/v1
provider: custom
"#;
        let err = parse_profile_model(yaml).unwrap_err();
        let msg = format!("{:#}", err);
        assert!(
            msg.contains("missing `model`"),
            "expected missing-model error, got: {}",
            msg
        );
    }

    #[test]
    fn test_parse_profile_model_empty_model_errors() {
        let yaml = "model: \"\"\nprovider: custom\n";
        assert!(parse_profile_model(yaml).is_err());
    }

    #[test]
    fn test_parse_profile_model_malformed_yaml_errors() {
        let yaml = "model: [unterminated";
        assert!(parse_profile_model(yaml).is_err());
    }

    // ------------------------------------------------------------------
    // Bug-C2 — tool_calls extraction
    // ------------------------------------------------------------------

    #[test]
    fn test_parse_tool_calls_present() {
        // Shape matches OpenAI /v1/chat/completions when the model emits
        // native function calls. arguments is a JSON-encoded string.
        let body = serde_json::json!({
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "search_files",
                                "arguments": "{\"pattern\": \"FCT055\"}"
                            }
                        },
                        {
                            "id": "call_def456",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": "{\"path\": \"/tmp/x\"}"
                            }
                        }
                    ]
                }
            }]
        });
        let tcs = parse_tool_calls(&body);
        assert_eq!(tcs.len(), 2);
        assert_eq!(tcs[0].id, "call_abc123");
        assert_eq!(tcs[0].name, "search_files");
        assert_eq!(tcs[0].arguments, "{\"pattern\": \"FCT055\"}");
        assert_eq!(tcs[1].id, "call_def456");
        assert_eq!(tcs[1].name, "read_file");
    }

    #[test]
    fn test_parse_tool_calls_absent() {
        // Normal content-only response — no tool_calls field.
        let body = serde_json::json!({
            "choices": [{
                "message": {
                    "content": "Here is the answer."
                }
            }]
        });
        let tcs = parse_tool_calls(&body);
        assert!(tcs.is_empty());
    }

    #[test]
    fn test_parse_tool_calls_object_arguments() {
        // Some providers emit arguments as a pre-parsed object rather than
        // a stringified JSON. We preserve verbatim as serialized JSON.
        let body = serde_json::json!({
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_obj",
                        "type": "function",
                        "function": {
                            "name": "noop",
                            "arguments": {"k": "v"}
                        }
                    }]
                }
            }]
        });
        let tcs = parse_tool_calls(&body);
        assert_eq!(tcs.len(), 1);
        assert_eq!(tcs[0].arguments, "{\"k\":\"v\"}");
    }

    #[test]
    fn test_parse_tool_calls_null_field() {
        let body = serde_json::json!({
            "choices": [{
                "message": {
                    "content": "hello",
                    "tool_calls": null
                }
            }]
        });
        assert!(parse_tool_calls(&body).is_empty());
    }
}
