use anyhow::{bail, Context, Result};
use matrix_sdk::{
    ruma::{OwnedEventId, RoomId},
    Client,
};
use pulldown_cmark::{html, Options, Parser};
use std::collections::HashMap;
use tracing::warn;

use crate::config::{
    JoinedRoom, MatrixEvent, MatrixStateEvent, StateEvents,
    SyncResponse as CoordSyncResponse, SyncRooms, Timeline as CoordTimeline,
};

const MAX_RESPONSE_LENGTH: usize = 30_000;
const MAX_MEDIA_BYTES: usize = 10 * 1024 * 1024;

fn markdown_to_html(text: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TABLES);
    let parser = Parser::new_ext(text, options);
    let mut html_output = String::new();
    html::push_html(&mut html_output, parser);
    html_output
}

#[derive(Clone)]
pub struct NativeMatrixClient {
    client: Client,
    pub user_id: String,
}

impl NativeMatrixClient {
    pub fn new(client: Client, user_id: String) -> Self {
        Self { client, user_id }
    }

    pub async fn whoami(&self) -> Result<String> {
        let resp = self.client.whoami().await.context("whoami failed")?;
        Ok(resp.user_id.to_string())
    }

    pub async fn send_message(
        &self,
        room_id: &str,
        body: &str,
        formatted_body: Option<&str>,
    ) -> Result<String> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;

        let (body, html) = if body.len() > MAX_RESPONSE_LENGTH {
            let truncated = format!(
                "{}... [truncated, {} chars]",
                &body[..MAX_RESPONSE_LENGTH],
                body.len()
            );
            let html = markdown_to_html(&truncated);
            (truncated, html)
        } else {
            let html = formatted_body
                .map(|s| s.to_string())
                .unwrap_or_else(|| markdown_to_html(body));
            (body.to_string(), html)
        };

        let content = serde_json::json!({
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
            "dev.ig88.coordinator_generated": true
        });

        let resp = room
            .send_raw("m.room.message", content)
            .await
            .context("send_message failed")?;

        Ok(resp.event_id.to_string())
    }

    pub async fn send_thread_message(
        &self,
        room_id: &str,
        body: &str,
        thread_root_event_id: &str,
    ) -> Result<String> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;

        let html = format!("<em>{}</em>", markdown_to_html(body));
        let content = serde_json::json!({
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

        match room.send_raw("m.room.message", content.clone()).await {
            Ok(resp) => Ok(resp.event_id.to_string()),
            Err(e) => {
                let msg = e.to_string();
                if msg.contains("Cannot start threads") || msg.contains("M_UNKNOWN") {
                    let mut plain = content;
                    plain.as_object_mut().unwrap().remove("m.relates_to");
                    let resp = room
                        .send_raw("m.room.message", plain)
                        .await
                        .context("thread fallback send failed")?;
                    Ok(resp.event_id.to_string())
                } else {
                    Err(e.into())
                }
            }
        }
    }

    pub async fn send_thread_reply(
        &self,
        room_id: &str,
        thread_root_id: &str,
        body: &str,
    ) -> Result<String> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;

        let (body, html) = if body.len() > MAX_RESPONSE_LENGTH {
            let truncated = format!(
                "{}... [truncated, {} chars]",
                &body[..MAX_RESPONSE_LENGTH],
                body.len()
            );
            (truncated.clone(), markdown_to_html(&truncated))
        } else {
            (body.to_string(), markdown_to_html(body))
        };

        let content = serde_json::json!({
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

        match room.send_raw("m.room.message", content.clone()).await {
            Ok(resp) => Ok(resp.event_id.to_string()),
            Err(e) => {
                let msg = e.to_string();
                if msg.contains("Cannot start threads") || msg.contains("M_UNKNOWN") {
                    let mut plain = content;
                    plain.as_object_mut().unwrap().remove("m.relates_to");
                    let resp = room
                        .send_raw("m.room.message", plain)
                        .await
                        .context("thread reply fallback failed")?;
                    Ok(resp.event_id.to_string())
                } else {
                    Err(e.into())
                }
            }
        }
    }

    pub async fn edit_message(
        &self,
        room_id: &str,
        event_id: &str,
        new_body: &str,
    ) -> Result<String> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;

        let html = markdown_to_html(new_body);
        let content = serde_json::json!({
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

        let resp = room
            .send_raw("m.room.message", content)
            .await
            .context("edit_message failed")?;

        Ok(resp.event_id.to_string())
    }

    pub async fn send_read_receipt(&self, room_id: &str, event_id: &str) -> Result<()> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;
        let event_id: OwnedEventId = event_id.try_into().context("Invalid event_id")?;

        if let Err(e) = room
            .send_single_receipt(
                matrix_sdk::ruma::api::client::receipt::create_receipt::v3::ReceiptType::Read,
                matrix_sdk::ruma::events::receipt::ReceiptThread::Unthreaded,
                event_id,
            )
            .await
        {
            warn!("send_read_receipt failed: {}", e);
        }
        Ok(())
    }

    pub async fn send_typing(
        &self,
        room_id: &str,
        typing: bool,
        _timeout_ms: u64,
    ) -> Result<()> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        let room = self.client.get_room(room_id).context("Room not found")?;

        let _ = room.typing_notice(typing).await;
        Ok(())
    }

    /// Sync using the SDK's sync_once. The SDK manages sync tokens internally,
    /// so `since` is only used on the first call; subsequent calls reuse the
    /// stored token automatically via SyncToken::ReusePrevious.
    pub async fn sync(
        &self,
        _since: Option<&str>,
        _filter_id: Option<&str>,
        timeout_ms: Option<u64>,
    ) -> Result<CoordSyncResponse> {
        let timeout = timeout_ms.unwrap_or(30_000);

        let settings = matrix_sdk::config::SyncSettings::default()
            .timeout(std::time::Duration::from_millis(timeout));

        let sdk_response = self
            .client
            .sync_once(settings)
            .await
            .context("sync_once failed")?;

        let next_batch = sdk_response.next_batch.clone();

        let mut join: HashMap<String, JoinedRoom> = HashMap::new();

        for (room_id, room_data) in sdk_response.rooms.joined {
            let timeline_events: Vec<MatrixEvent> = room_data
                .timeline
                .events
                .iter()
                .filter_map(|te| {
                    let raw = te.raw();
                    let val: serde_json::Value = serde_json::from_str(raw.json().get()).ok()?;
                    Some(MatrixEvent {
                        event_type: val.get("type")?.as_str()?.to_string(),
                        sender: val.get("sender")?.as_str()?.to_string(),
                        event_id: val.get("event_id")?.as_str()?.to_string(),
                        content: val.get("content")?.clone(),
                        origin_server_ts: val
                            .get("origin_server_ts")
                            .and_then(|v| v.as_u64()),
                        room_id: Some(room_id.to_string()),
                    })
                })
                .collect();

            let state_raw: &[matrix_sdk::ruma::serde::Raw<matrix_sdk::ruma::events::AnySyncStateEvent>] = match &room_data.state {
                matrix_sdk::sync::State::Before(events) => events,
                matrix_sdk::sync::State::After(events) => events,
            };

            let state_events: Vec<MatrixStateEvent> = state_raw
                .iter()
                .filter_map(|raw| {
                    let val: serde_json::Value = serde_json::from_str(raw.json().get()).ok()?;
                    Some(MatrixStateEvent {
                        event_type: val.get("type")?.as_str()?.to_string(),
                        state_key: val
                            .get("state_key")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        content: val.get("content")?.clone(),
                        sender: val.get("sender")?.as_str()?.to_string(),
                        event_id: val.get("event_id")?.as_str()?.to_string(),
                        origin_server_ts: val
                            .get("origin_server_ts")
                            .and_then(|v| v.as_u64()),
                    })
                })
                .collect();

            join.insert(
                room_id.to_string(),
                JoinedRoom {
                    timeline: if timeline_events.is_empty() {
                        None
                    } else {
                        Some(CoordTimeline {
                            events: timeline_events,
                        })
                    },
                    state: if state_events.is_empty() {
                        None
                    } else {
                        Some(StateEvents {
                            events: state_events,
                        })
                    },
                },
            );
        }

        Ok(CoordSyncResponse {
            next_batch,
            rooms: SyncRooms {
                join,
                leave: HashMap::new(),
            },
        })
    }

    pub async fn create_sync_filter(&self) -> Result<String> {
        // matrix-sdk handles filters internally via SyncSettings
        Ok("native-sdk-filter".to_string())
    }

    pub async fn download_media(&self, mxc_url: &str) -> Result<(Vec<u8>, String)> {
        let media_id: matrix_sdk::ruma::OwnedMxcUri = mxc_url.into();
        let request = matrix_sdk::media::MediaRequestParameters {
            source: matrix_sdk::ruma::events::room::MediaSource::Plain(media_id),
            format: matrix_sdk::media::MediaFormat::File,
        };

        let bytes = self
            .client
            .media()
            .get_media_content(&request, true)
            .await
            .context("download_media failed")?;

        if bytes.len() > MAX_MEDIA_BYTES {
            bail!(
                "Media too large: {} bytes (max {})",
                bytes.len(),
                MAX_MEDIA_BYTES
            );
        }

        Ok((bytes, "application/octet-stream".to_string()))
    }

    pub async fn get_joined_member_count(&self, room_id: &str) -> Result<usize> {
        let room_id = <&RoomId>::try_from(room_id).context("Invalid room_id")?;
        match self.client.get_room(room_id) {
            Some(room) => Ok(room.joined_members_count() as usize),
            None => Ok(0),
        }
    }
}
