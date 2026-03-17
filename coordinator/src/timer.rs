/// Agent self-scheduling via JSON timer files.
/// Phase 3D: Reads *.json from timer_dir, fires when due_at <= now.
/// Timer JSON: { "agent": "ig88", "room_id": "!...", "due_at": "2026-03-08T12:00:00Z", "message": "..." }
use chrono::{DateTime, Utc};
use serde::Deserialize;
use std::fs;
use std::path::Path;
use tracing::{debug, info, warn};

#[derive(Debug, Deserialize)]
struct TimerFile {
    agent: String,
    room_id: String,
    due_at: String,
    message: String,
}

/// Fired timer result — agent name, room_id, and message to inject.
#[derive(Debug)]
pub struct FiredTimer {
    pub agent: String,
    pub room_id: String,
    pub message: String,
}

/// Check for pending timer files and return any that are ready to fire.
/// Renames fired timers to *.fired for audit trail.
pub async fn check_timers(timer_dir: &str) -> Vec<FiredTimer> {
    let dir = Path::new(timer_dir);
    if !dir.exists() {
        return Vec::new();
    }

    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            debug!("Failed to read timer dir {}: {}", timer_dir, e);
            return Vec::new();
        }
    };

    let now = Utc::now();
    let mut fired = Vec::new();

    for entry in entries.flatten() {
        let path = entry.path();

        // Only process .json files
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }

        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => {
                warn!("Failed to read timer file {:?}: {}", path, e);
                continue;
            }
        };

        let timer: TimerFile = match serde_json::from_str(&content) {
            Ok(t) => t,
            Err(e) => {
                warn!("Invalid timer JSON in {:?}: {}", path, e);
                continue;
            }
        };

        let due_at: DateTime<Utc> = match timer.due_at.parse() {
            Ok(d) => d,
            Err(e) => {
                warn!("Invalid due_at in {:?}: {}", path, e);
                continue;
            }
        };

        if due_at <= now {
            info!(
                "Timer fired: agent={} message={}",
                timer.agent,
                &timer.message[..timer.message.len().min(60)]
            );

            fired.push(FiredTimer {
                agent: timer.agent,
                room_id: timer.room_id,
                message: timer.message,
            });

            // Rename to .fired for audit trail
            let fired_path = path.with_extension("fired");
            if let Err(e) = fs::rename(&path, &fired_path) {
                warn!("Failed to rename fired timer {:?}: {}", path, e);
                // Fall back to deletion
                let _ = fs::remove_file(&path);
            }
        }
    }

    fired
}
