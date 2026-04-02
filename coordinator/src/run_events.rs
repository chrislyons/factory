/// Heartbeat event streaming — append-only JSONL logs per run for real-time observability.
/// Each run gets a file in `runs_dir/{run_id}.jsonl` with monotonically increasing sequence numbers.
use anyhow::{Context, Result};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::path::PathBuf;
use tokio::sync::Mutex;
use tracing::debug;

// ============================================================================
// Types
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunEventType {
    ToolCall,
    ToolResult,
    Checkpoint,
    Error,
    SessionStart,
    SessionEnd,
    LoopStart,
    IterationStart,
    IterationEnd,
    LoopComplete,
    LoopAborted,
    FrozenHarnessViolation,
    ProviderFailover,
    ProviderExhausted,
    ProviderRecovered,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventStream {
    System,
    Stdout,
    Stderr,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventLevel {
    Info,
    Warn,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunEvent {
    pub run_id: String,
    pub seq: u64,
    pub event_type: RunEventType,
    pub stream: EventStream,
    pub level: EventLevel,
    pub message: String,
    pub payload: Option<serde_json::Value>,
    pub timestamp: String, // ISO 8601
}

// ============================================================================
// RunEventLog
// ============================================================================

pub struct RunEventLog {
    runs_dir: PathBuf,
    seq_counters: Mutex<HashMap<String, u64>>,
}

impl RunEventLog {
    pub fn new(runs_dir: PathBuf) -> Self {
        Self {
            runs_dir,
            seq_counters: Mutex::new(HashMap::new()),
        }
    }

    /// Append an event to a run's JSONL log. Returns the sequence number.
    pub async fn append_event(
        &self,
        run_id: &str,
        event_type: RunEventType,
        stream: EventStream,
        level: EventLevel,
        message: &str,
        payload: Option<serde_json::Value>,
    ) -> Result<u64> {
        let mut counters = self.seq_counters.lock().await;
        let seq = counters.entry(run_id.to_string()).or_insert(0);
        *seq += 1;
        let current_seq = *seq;
        drop(counters);

        let event = RunEvent {
            run_id: run_id.to_string(),
            seq: current_seq,
            event_type,
            stream,
            level,
            message: message.to_string(),
            payload,
            timestamp: Utc::now().to_rfc3339(),
        };

        let line = serde_json::to_string(&event)?;

        std::fs::create_dir_all(&self.runs_dir)?;
        let path = self.runs_dir.join(format!("{}.jsonl", run_id));
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .with_context(|| format!("failed to open run log: {}", path.display()))?;

        writeln!(file, "{}", line)?;
        debug!("run_events: {}/{} seq={}", run_id, event.message, current_seq);

        Ok(current_seq)
    }

    /// Read all events for a run from its JSONL file.
    pub fn get_events(&self, run_id: &str) -> Result<Vec<RunEvent>> {
        let path = self.runs_dir.join(format!("{}.jsonl", run_id));
        if !path.exists() {
            return Ok(Vec::new());
        }

        let file = std::fs::File::open(&path)
            .with_context(|| format!("failed to open run log: {}", path.display()))?;
        let reader = std::io::BufReader::new(file);

        let mut events = Vec::new();
        for line in reader.lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let event: RunEvent = serde_json::from_str(&line)
                .with_context(|| format!("failed to parse run event: {}", &line[..line.len().min(100)]))?;
            events.push(event);
        }

        Ok(events)
    }

    /// Remove JSONL files older than `max_age_days`. Returns count of files removed.
    pub fn cleanup_old_runs(&self, max_age_days: u32) -> Result<usize> {
        if !self.runs_dir.exists() {
            return Ok(0);
        }

        let cutoff = std::time::SystemTime::now()
            - std::time::Duration::from_secs(max_age_days as u64 * 86400);

        let mut removed = 0;
        for entry in std::fs::read_dir(&self.runs_dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("jsonl") {
                continue;
            }
            if let Ok(metadata) = entry.metadata() {
                if let Ok(modified) = metadata.modified() {
                    if modified < cutoff {
                        std::fs::remove_file(&path)?;
                        removed += 1;
                    }
                }
            }
        }

        if removed > 0 {
            debug!("run_events: cleaned up {} old run logs", removed);
        }
        Ok(removed)
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_runs_dir(name: &str) -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("run-events-test-{}-{}", std::process::id(), name));
        p
    }

    #[tokio::test]
    async fn append_and_read_roundtrip() {
        let dir = temp_runs_dir("roundtrip");
        let log = RunEventLog::new(dir.clone());

        log.append_event(
            "run-1",
            RunEventType::SessionStart,
            EventStream::System,
            EventLevel::Info,
            "session started",
            None,
        )
        .await
        .unwrap();

        log.append_event(
            "run-1",
            RunEventType::ToolCall,
            EventStream::Stdout,
            EventLevel::Info,
            "calling Read",
            Some(serde_json::json!({"file": "main.rs"})),
        )
        .await
        .unwrap();

        let events = log.get_events("run-1").unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].message, "session started");
        assert_eq!(events[1].message, "calling Read");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn seq_monotonicity() {
        let dir = temp_runs_dir("seq");
        let log = RunEventLog::new(dir.clone());

        let s1 = log
            .append_event("run-1", RunEventType::Checkpoint, EventStream::System, EventLevel::Info, "a", None)
            .await
            .unwrap();
        let s2 = log
            .append_event("run-1", RunEventType::Checkpoint, EventStream::System, EventLevel::Info, "b", None)
            .await
            .unwrap();
        let s3 = log
            .append_event("run-1", RunEventType::Checkpoint, EventStream::System, EventLevel::Info, "c", None)
            .await
            .unwrap();

        assert_eq!(s1, 1);
        assert_eq!(s2, 2);
        assert_eq!(s3, 3);

        // Different run has its own counter
        let s1_other = log
            .append_event("run-2", RunEventType::SessionStart, EventStream::System, EventLevel::Info, "x", None)
            .await
            .unwrap();
        assert_eq!(s1_other, 1);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[tokio::test]
    async fn empty_run_returns_empty() {
        let dir = temp_runs_dir("empty");
        let log = RunEventLog::new(dir.clone());
        let events = log.get_events("nonexistent").unwrap();
        assert!(events.is_empty());
    }
}
