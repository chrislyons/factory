/// Hermes agent runtime adapter.
///
/// Phase 3: Subprocess mode — parses plain-text Hermes output into SessionResult.
/// Phase 4: HTTP mode — talks to `hermes serve` via OpenAI-compatible API.
use anyhow::{Context, Result};
use serde::Deserialize;

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
#[allow(dead_code)]
#[derive(Debug, Deserialize)]
pub struct OpenAIUsage {
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub total_tokens: u64,
}

#[allow(dead_code)]
pub fn convert_usage(usage: &OpenAIUsage) -> (u64, u64) {
    (usage.prompt_tokens, usage.completion_tokens)
}

// ============================================================================
// Phase 4: HTTP client for `hermes serve` mode (stub)
// ============================================================================

/// HTTP client for a Hermes instance running in `hermes serve --port N` mode.
/// Phase 4 only — Phase 3 uses subprocess I/O via spawn_hermes().
#[allow(dead_code)]
pub struct HermesHttpClient {
    port: u16,
    client: reqwest::Client,
}

#[allow(dead_code)]
impl HermesHttpClient {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .expect("Failed to build Hermes HTTP client"),
        }
    }

    /// Send a chat message to Hermes serve endpoint.
    /// Returns (response_text, usage).
    pub async fn chat(&self, message: &str, model: &str) -> Result<(String, OpenAIUsage)> {
        let url = format!("http://127.0.0.1:{}/v1/chat/completions", self.port);
        let body = serde_json::json!({
            "model": model,
            "messages": [{"role": "user", "content": message}],
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
            anyhow::bail!("Hermes returned HTTP {}: {}", status, &text[..text.len().min(500)]);
        }

        let parsed: serde_json::Value =
            serde_json::from_str(&text).context("Failed to parse Hermes JSON response")?;

        let content = parsed["choices"][0]["message"]["content"]
            .as_str()
            .unwrap_or("")
            .to_string();

        let usage: OpenAIUsage = serde_json::from_value(
            parsed["usage"].clone(),
        )
        .unwrap_or(OpenAIUsage {
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
        });

        Ok((content, usage))
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
}
