/// Pantalaimon HTTP client — Matrix Client-Server API over local proxy.
///
/// The coordinator speaks plain HTTP to Pantalaimon at http://127.0.0.1:8009.
/// Pantalaimon handles Olm/Megolm E2EE transparently. From this module's perspective
/// all messages are plaintext. See BKX084 for the architectural rationale.
use anyhow::{bail, Context, Result};
use pulldown_cmark::{html, Options, Parser};
use reqwest::{Client, StatusCode};
use serde_json::json;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tracing::{debug, warn};

fn markdown_to_html(text: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TABLES);
    let parser = Parser::new_ext(text, options);
    let mut html_output = String::new();
    html::push_html(&mut html_output, parser);
    html_output
}

use crate::config::SyncResponse;

// ============================================================================
// Constants
// ============================================================================

const DEFAULT_PANTALAIMON_URL: &str = "http://127.0.0.1:8009";
const SYNC_TIMEOUT_SECS: u64 = 30;
const REQUEST_TIMEOUT_SECS: u64 = 30;
const MAX_RESPONSE_LENGTH: usize = 30_000;
const SEND_RETRY_COUNT: usize = 3;
const SEND_RETRY_BASE_MS: u64 = 200;

/// Per-agent transaction ID counter (avoids txnId collisions across threads).
static TXN_COUNTER: AtomicU64 = AtomicU64::new(0);

// ============================================================================
// MatrixClient
// ============================================================================

#[derive(Clone)]
pub struct MatrixClient {
    client: Client,
    base_url: String,
    token: String,
    /// Matrix user ID (e.g. "@ig88bot:matrix.org") — used to filter own messages.
    pub user_id: String,
}

impl MatrixClient {
    pub fn new(base_url: Option<&str>, token: String, user_id: String) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS))
            .pool_max_idle_per_host(5)
            .build()
            .context("Failed to build reqwest client")?;

        Ok(Self {
            client,
            base_url: base_url.unwrap_or(DEFAULT_PANTALAIMON_URL).to_string(),
            token,
            user_id,
        })
    }

    fn auth_header(&self) -> String {
        format!("Bearer {}", self.token)
    }

    fn txn_id(&self) -> String {
        let n = TXN_COUNTER.fetch_add(1, Ordering::Relaxed);
        format!("coordinator-rs-{}-{}", std::process::id(), n)
    }

    // ============================================================================
    // Whoami — resolve user_id from token (used at startup to verify token)
    // ============================================================================

    pub async fn whoami(&self) -> Result<String> {
        let url = format!("{}/_matrix/client/v3/account/whoami", self.base_url);
        let resp = self
            .client
            .get(&url)
            .header("Authorization", self.auth_header())
            .send()
            .await
            .context("whoami request failed")?;

        let status = resp.status();
        let body: serde_json::Value = resp
            .json()
            .await
            .context("whoami response not valid JSON")?;

        if !status.is_success() {
            bail!("whoami failed {}: {}", status, body);
        }

        body["user_id"]
            .as_str()
            .map(|s| s.to_string())
            .context("whoami response missing user_id")
    }

    // ============================================================================
    // Sync filter creation (BKX064 — reduces bandwidth ~20-30%)
    // ============================================================================

    pub async fn create_sync_filter(&self) -> Result<String> {
        let url = format!(
            "{}/_matrix/client/v3/user/{}/filter",
            self.base_url,
            urlencoding::encode(&self.user_id)
        );

        let filter = json!({
            "room": {
                "timeline": {
                    "types": ["m.room.message", "m.reaction"],
                    "limit": 50
                },
                "state": {
                    "types": ["m.room.name", "m.room.encryption", "m.room.member"]
                },
                "ephemeral": {
                    "not_types": ["*"]
                }
            },
            "presence": {
                "not_types": ["*"]
            },
            "account_data": {
                "not_types": ["*"]
            }
        });

        let resp = self
            .client
            .post(&url)
            .header("Authorization", self.auth_header())
            .json(&filter)
            .send()
            .await
            .context("create_sync_filter request failed")?;

        let status = resp.status();
        let body: serde_json::Value = resp.json().await.context("filter response not JSON")?;
        if !status.is_success() {
            bail!("create_sync_filter failed {}: {}", status, body);
        }

        body["filter_id"]
            .as_str()
            .map(|s| s.to_string())
            .context("filter response missing filter_id")
    }

    // ============================================================================
    // Sync
    // ============================================================================

    /// Poll the sync endpoint. Returns the full SyncResponse.
    /// `since` is the sync token from the previous poll (None for initial sync).
    /// `filter_id` is from `create_sync_filter()` (None if not yet created).
    /// `timeout_ms` overrides the long-poll timeout. Pass `Some(0)` for non-blocking
    /// poll-and-return; `None` uses the default SYNC_TIMEOUT_SECS long-poll.
    pub async fn sync(
        &self,
        since: Option<&str>,
        filter_id: Option<&str>,
        timeout_ms: Option<u64>,
    ) -> Result<SyncResponse> {
        let timeout = timeout_ms.unwrap_or(SYNC_TIMEOUT_SECS * 1000);
        let mut url = format!(
            "{}/_matrix/client/v3/sync?timeout={}",
            self.base_url,
            timeout
        );

        if let Some(token) = since {
            url.push_str(&format!("&since={}", urlencoding::encode(token)));
        }
        if let Some(fid) = filter_id {
            url.push_str(&format!("&filter={}", urlencoding::encode(fid)));
        }

        // Allow enough headroom beyond the Matrix long-poll timeout.
        // For timeout=0 (non-blocking coord sync), still use a reasonable ceiling.
        let http_timeout = Duration::from_millis(timeout.saturating_add(10_000));
        let resp = self
            .client
            .get(&url)
            .header("Authorization", self.auth_header())
            .timeout(http_timeout)
            .send()
            .await
            .context("sync request failed")?;

        let status = resp.status();
        if status == StatusCode::UNAUTHORIZED {
            bail!("Sync unauthorized — token may be expired");
        }

        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            bail!("sync failed {}: {}", status, &text[..text.len().min(200)]);
        }

        resp.json::<SyncResponse>()
            .await
            .context("sync response JSON parse failed")
    }

    // ============================================================================
    // Send message
    // ============================================================================

    /// Send a plain-text (or HTML) message to a room. Returns the event_id.
    /// Retries up to SEND_RETRY_COUNT times with exponential backoff.
    pub async fn send_message(
        &self,
        room_id: &str,
        body: &str,
        formatted_body: Option<&str>,
    ) -> Result<String> {
        // Truncate responses that exceed Matrix event size limits.
        // Apply markdown even when truncating so formatting is preserved.
        let (body, formatted_body) = if body.len() > MAX_RESPONSE_LENGTH {
            let truncated = format!(
                "{}… [truncated, {} chars]",
                &body[..MAX_RESPONSE_LENGTH],
                body.len()
            );
            let html = markdown_to_html(&truncated);
            (truncated, Some(html))
        } else {
            // Auto-convert body to HTML when no explicit formatted_body is provided.
            // This restores parity with the TS coordinator's formatMarkdown() behavior:
            // Element only renders bold/italic/code when format + formatted_body are set.
            let html = formatted_body
                .map(|s| s.to_string())
                .unwrap_or_else(|| markdown_to_html(body));
            (body.to_string(), Some(html))
        };

        let mut content = json!({
            "msgtype": "m.text",
            "body": body,
            "dev.ig88.coordinator_generated": true
        });

        if let Some(html) = formatted_body {
            content["format"] = json!("org.matrix.custom.html");
            content["formatted_body"] = json!(html);
        }

        self.send_event_with_retry(room_id, "m.room.message", &content).await
    }

    // ============================================================================
    // Edit message (m.replace)
    // ============================================================================

    /// Edit an existing message (used for live HUD status updates).
    pub async fn edit_message(
        &self,
        room_id: &str,
        event_id: &str,
        new_body: &str,
    ) -> Result<String> {
        let html = markdown_to_html(new_body);
        let content = json!({
            "msgtype": "m.text",
            "body": format!("* {}", new_body),
            "format": "org.matrix.custom.html",
            "formatted_body": format!("* {}", html),
            "dev.ig88.coordinator_generated": true,
            "m.new_content": {
                "msgtype": "m.text",
                "body": new_body,
                "format": "org.matrix.custom.html",
                "formatted_body": html
            },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": event_id
            }
        });

        self.send_event_with_retry(room_id, "m.room.message", &content).await
    }

    // ============================================================================
    // Retry wrapper for all send operations
    // ============================================================================

    /// Send a Matrix event with exponential backoff retry (200ms → 400ms → 800ms).
    /// Prevents cascade failures when Pantalaimon is momentarily unresponsive.
    async fn send_event_with_retry(
        &self,
        room_id: &str,
        event_type: &str,
        content: &serde_json::Value,
    ) -> Result<String> {
        let mut backoff = Duration::from_millis(SEND_RETRY_BASE_MS);

        for attempt in 0..SEND_RETRY_COUNT {
            let txn_id = self.txn_id();
            let url = format!(
                "{}/_matrix/client/v3/rooms/{}/send/{}/{}",
                self.base_url,
                urlencoding::encode(room_id),
                urlencoding::encode(event_type),
                txn_id
            );

            let result = self
                .client
                .put(&url)
                .header("Authorization", self.auth_header())
                .json(content)
                .send()
                .await;

            match result {
                Ok(resp) => {
                    let status = resp.status();
                    let body: serde_json::Value = resp
                        .json()
                        .await
                        .context("send response not JSON")?;

                    if status.is_success() {
                        return body["event_id"]
                            .as_str()
                            .map(|s| s.to_string())
                            .context("send response missing event_id");
                    }

                    // Don't retry auth failures
                    if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
                        bail!("send {} failed {} (not retryable): {}", event_type, status, body);
                    }

                    if attempt < SEND_RETRY_COUNT - 1 {
                        warn!(
                            "Matrix send failed (attempt {}/{}), retrying in {:?}: {} {}",
                            attempt + 1, SEND_RETRY_COUNT, backoff, status, body
                        );
                        tokio::time::sleep(backoff).await;
                        backoff *= 2;
                    } else {
                        bail!("send {} failed after {} attempts: {} {}", event_type, SEND_RETRY_COUNT, status, body);
                    }
                }
                Err(e) => {
                    if attempt < SEND_RETRY_COUNT - 1 {
                        warn!(
                            "Matrix send failed (attempt {}/{}), retrying in {:?}: {}",
                            attempt + 1, SEND_RETRY_COUNT, backoff, e
                        );
                        tokio::time::sleep(backoff).await;
                        backoff *= 2;
                    } else {
                        bail!("send {} failed after {} attempts: {}", event_type, SEND_RETRY_COUNT, e);
                    }
                }
            }
        }

        unreachable!()
    }

    // ============================================================================
    // Download media (for image support)
    // ============================================================================

    /// Download media from an mxc:// URL via Pantalaimon.
    /// Returns (bytes, content_type). 10MB size guard for RP5 memory safety.
    pub async fn download_media(&self, mxc_url: &str) -> Result<(Vec<u8>, String)> {
        // Parse mxc://server/media_id
        let stripped = mxc_url
            .strip_prefix("mxc://")
            .context("Invalid mxc:// URL")?;
        let (server, media_id) = stripped
            .split_once('/')
            .context("Invalid mxc:// URL format")?;

        let url = format!(
            "{}/_matrix/media/v3/download/{}/{}",
            self.base_url,
            urlencoding::encode(server),
            urlencoding::encode(media_id)
        );

        let resp = self
            .client
            .get(&url)
            .header("Authorization", self.auth_header())
            .send()
            .await
            .context("download_media request failed")?;

        let status = resp.status();
        if !status.is_success() {
            bail!("download_media failed: {}", status);
        }

        let content_type = resp
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("application/octet-stream")
            .to_string();

        let bytes = resp.bytes().await.context("download_media read failed")?;

        // 10MB guard — base64 encoding doubles memory usage
        const MAX_MEDIA_BYTES: usize = 10 * 1024 * 1024;
        if bytes.len() > MAX_MEDIA_BYTES {
            bail!(
                "Media too large: {} bytes (max {})",
                bytes.len(),
                MAX_MEDIA_BYTES
            );
        }

        Ok((bytes.to_vec(), content_type))
    }

    // ============================================================================
    // Send thread message (verbose tool activity)
    // ============================================================================

    /// Send a message as a thread reply (for verbose tool activity posts).
    pub async fn send_thread_message(
        &self,
        room_id: &str,
        body: &str,
        thread_root_event_id: &str,
    ) -> Result<String> {
        // Use m.notice so Element suppresses push notifications for thread activity.
        // Main timeline responses use m.text and notify normally.
        let html = format!("<em>{}</em>", markdown_to_html(body));
        let content = json!({
            "msgtype": "m.notice",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
            "dev.ig88.coordinator_generated": true,
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": thread_root_event_id,
                "is_falling_back": true,
                "m.in_reply_to": { "event_id": thread_root_event_id }
            }
        });

        match self.send_event_with_retry(room_id, "m.room.message", &content).await {
            Ok(id) => Ok(id),
            Err(e) => {
                // Matrix rejects thread posts when the root event itself has a relation
                // (e.g. it's a reply). Fall back to a plain notice in the room instead
                // of silently dropping the message.
                let msg = e.to_string();
                if msg.contains("Cannot start threads from an event with a relation")
                    || msg.contains("M_UNKNOWN")
                {
                    let plain = json!({
                        "msgtype": "m.notice",
                        "body": body,
                        "format": "org.matrix.custom.html",
                        "formatted_body": html,
                        "dev.ig88.coordinator_generated": true,
                    });
                    self.send_event_with_retry(room_id, "m.room.message", &plain).await
                } else {
                    Err(e)
                }
            }
        }
    }

    // ============================================================================
    // Send thread reply (final agent response as m.text thread reply)
    // ============================================================================

    /// Send the agent's final response as an m.text thread reply on the user's message.
    /// Unlike send_thread_message (m.notice for verbose activity), this uses m.text
    /// so it pings the user, and is_falling_back: false since it's a true thread reply.
    pub async fn send_thread_reply(
        &self,
        room_id: &str,
        thread_root_id: &str,
        body: &str,
    ) -> Result<String> {
        let (body, html) = if body.len() > MAX_RESPONSE_LENGTH {
            let truncated = format!(
                "{}… [truncated, {} chars]",
                &body[..MAX_RESPONSE_LENGTH],
                body.len()
            );
            let html = markdown_to_html(&truncated);
            (truncated, html)
        } else {
            (body.to_string(), markdown_to_html(body))
        };

        let content = json!({
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
            "dev.ig88.coordinator_generated": true,
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": thread_root_id,
                "is_falling_back": false,
                "m.in_reply_to": { "event_id": thread_root_id }
            }
        });

        match self.send_event_with_retry(room_id, "m.room.message", &content).await {
            Ok(id) => Ok(id),
            Err(e) => {
                let msg = e.to_string();
                if msg.contains("Cannot start threads from an event with a relation")
                    || msg.contains("M_UNKNOWN")
                {
                    let plain = json!({
                        "msgtype": "m.text",
                        "body": body,
                        "format": "org.matrix.custom.html",
                        "formatted_body": html,
                        "dev.ig88.coordinator_generated": true,
                    });
                    self.send_event_with_retry(room_id, "m.room.message", &plain).await
                } else {
                    Err(e)
                }
            }
        }
    }

    // ============================================================================
    // DM room detection
    // ============================================================================

    // ============================================================================
    // Read receipt (m.read)
    // ============================================================================

    /// Send a read receipt for an event, marking it as read.
    pub async fn send_read_receipt(&self, room_id: &str, event_id: &str) -> Result<()> {
        let url = format!(
            "{}/_matrix/client/v3/rooms/{}/receipt/m.read/{}",
            self.base_url,
            urlencoding::encode(room_id),
            urlencoding::encode(event_id)
        );

        let resp = self
            .client
            .post(&url)
            .header("Authorization", self.auth_header())
            .json(&json!({}))
            .send()
            .await
            .context("send_read_receipt request failed")?;

        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            warn!("send_read_receipt failed: {}", &text[..text.len().min(200)]);
        }
        Ok(())
    }

    // ============================================================================
    // Typing indicator
    // ============================================================================

    /// Set typing indicator for a user in a room.
    pub async fn send_typing(
        &self,
        room_id: &str,
        typing: bool,
        timeout_ms: u64,
    ) -> Result<()> {
        let url = format!(
            "{}/_matrix/client/v3/rooms/{}/typing/{}",
            self.base_url,
            urlencoding::encode(room_id),
            urlencoding::encode(&self.user_id)
        );

        let body = if typing {
            json!({ "typing": true, "timeout": timeout_ms })
        } else {
            json!({ "typing": false })
        };

        let resp = self
            .client
            .put(&url)
            .header("Authorization", self.auth_header())
            .json(&body)
            .send()
            .await
            .context("send_typing request failed")?;

        if !resp.status().is_success() {
            let text = resp.text().await.unwrap_or_default();
            debug!("send_typing failed: {}", &text[..text.len().min(200)]);
        }
        Ok(())
    }

    // ============================================================================
    // DM room detection
    // ============================================================================

    /// Check joined members count to determine if a room is a DM (2 members = DM).
    pub async fn get_joined_member_count(&self, room_id: &str) -> Result<usize> {
        let url = format!(
            "{}/_matrix/client/v3/rooms/{}/joined_members",
            self.base_url,
            urlencoding::encode(room_id)
        );

        let resp = self
            .client
            .get(&url)
            .header("Authorization", self.auth_header())
            .send()
            .await
            .context("get_joined_members request failed")?;

        if !resp.status().is_success() {
            return Ok(0);
        }

        let body: serde_json::Value = resp.json().await.context("joined_members response not JSON")?;
        let count = body["joined"]
            .as_object()
            .map(|m| m.len())
            .unwrap_or(0);

        Ok(count)
    }
}

// ============================================================================
// URL encoding helper (avoid pulling in the `url` crate just for this)
// ============================================================================

mod urlencoding {
    pub fn encode(s: &str) -> String {
        let mut out = String::with_capacity(s.len());
        for c in s.chars() {
            match c {
                'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => out.push(c),
                _ => {
                    for byte in c.to_string().as_bytes() {
                        out.push_str(&format!("%{:02X}", byte));
                    }
                }
            }
        }
        out
    }
}

// ============================================================================
// Sync token persistence
// ============================================================================

const SYNC_TOKENS_FILE: &str = ".config/ig88/sync-tokens.json";
const SYNC_TOKEN_SAVE_INTERVAL: u32 = 10; // save every N polls

pub struct SyncTokenStore {
    path: std::path::PathBuf,
    tokens: HashMap<String, String>,
    poll_counter: u32,
}

impl SyncTokenStore {
    pub fn load() -> Self {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
        let path = std::path::PathBuf::from(home).join(SYNC_TOKENS_FILE);

        let tokens: HashMap<String, String> = if path.exists() {
            std::fs::read_to_string(&path)
                .ok()
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_default()
        } else {
            HashMap::new()
        };

        Self { path, tokens, poll_counter: 0 }
    }

    pub fn get(&self, agent_name: &str) -> Option<&str> {
        self.tokens.get(agent_name).map(|s| s.as_str())
    }

    pub fn set(&mut self, agent_name: &str, token: String) {
        self.tokens.insert(agent_name.to_string(), token);
    }

    /// Save tokens to disk (rate-limited to every SYNC_TOKEN_SAVE_INTERVAL calls).
    pub fn maybe_save(&mut self) {
        self.poll_counter += 1;
        if self.poll_counter >= SYNC_TOKEN_SAVE_INTERVAL {
            self.poll_counter = 0;
            self.save();
        }
    }

    /// Force-save (called on graceful shutdown).
    pub fn save(&self) {
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(json) = serde_json::to_string(&self.tokens) {
            let _ = std::fs::write(&self.path, &json);
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(
                    &self.path,
                    std::fs::Permissions::from_mode(0o600),
                );
            }
        }
    }
}
