/// Per-agent filesystem memory layers.
/// Phase 3G: scratchpad.md, episodic/, fact/{domain}.md
/// See memory-manager.ts for the TypeScript reference implementation.
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;
use tracing::{debug, warn};

// ============================================================================
// Constants
// ============================================================================

const SCRATCHPAD_MAX_CHARS: usize = 500;
const EPISODIC_MAX_FILES: usize = 3;
const FACT_MAX_CHARS: usize = 1000;
const MAX_WRITES_PER_MINUTE: u32 = 10;

// ============================================================================
// Write rate limiter
// ============================================================================

pub struct MemoryRateLimiter {
    counts: HashMap<String, (u32, Instant)>,
}

impl MemoryRateLimiter {
    pub fn new() -> Self {
        Self {
            counts: HashMap::new(),
        }
    }

    /// Returns true if the write should be allowed.
    pub fn check(&mut self, agent_name: &str) -> bool {
        let now = Instant::now();
        let entry = self.counts.entry(agent_name.to_string()).or_insert((0, now));

        if now.duration_since(entry.1).as_secs() >= 60 {
            // Window expired, reset
            *entry = (1, now);
            true
        } else if entry.0 < MAX_WRITES_PER_MINUTE {
            entry.0 += 1;
            true
        } else {
            warn!(
                "[{}] Memory write rate limit exceeded ({}/min)",
                agent_name, MAX_WRITES_PER_MINUTE
            );
            false
        }
    }

}

// ============================================================================
// Path helpers
// ============================================================================

fn memory_base() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home).join("projects/ig88/memory")
}

fn agent_memory_dir(agent_name: &str) -> PathBuf {
    memory_base().join(agent_name)
}

/// Ensure per-agent memory directories exist.
pub fn ensure_memory_dirs(agent_name: &str) {
    let base = agent_memory_dir(agent_name);
    let _ = fs::create_dir_all(base.join("episodic"));
    let _ = fs::create_dir_all(base.join("fact"));

    let index = base.join("index.md");
    if !index.exists() {
        let content = format!(
            "# {} Memory Index\n\n- scratchpad.md — working notes\n- episodic/ — session summaries\n- fact/ — durable knowledge\n",
            agent_name
        );
        let _ = fs::write(index, content);
    }
}

// ============================================================================
// Context injection — build memory block for Claude prompt
// ============================================================================

/// Build memory context injection string for a Claude prompt.
/// Reads scratchpad + recent episodic + fact files, respecting size caps.
pub fn build_memory_context_injection(agent_name: &str) -> String {
    let base = agent_memory_dir(agent_name);
    let mut sections = Vec::new();

    // 1. Scratchpad
    let scratchpad_path = base.join("scratchpad.md");
    if let Ok(content) = fs::read_to_string(&scratchpad_path) {
        if !content.trim().is_empty() {
            let truncated = if content.len() > SCRATCHPAD_MAX_CHARS {
                format!("{}…", &content[..SCRATCHPAD_MAX_CHARS])
            } else {
                content.clone()
            };
            sections.push(format!("**Scratchpad:**\n{}", truncated.trim()));
        }
    }

    // 2. Recent episodic files (last 3 by mtime)
    let episodic_dir = base.join("episodic");
    if let Ok(mut entries) = read_dir_sorted_by_mtime(&episodic_dir) {
        entries.truncate(EPISODIC_MAX_FILES);
        let mut episodic_text = Vec::new();
        for (path, _) in &entries {
            if let Ok(content) = fs::read_to_string(path) {
                let filename = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("unknown");
                // Take first 200 chars of each episodic file
                let preview = if content.len() > 200 {
                    format!("{}…", &content[..200])
                } else {
                    content.clone()
                };
                episodic_text.push(format!("_{}_: {}", filename, preview.trim()));
            }
        }
        if !episodic_text.is_empty() {
            sections.push(format!("**Recent Sessions:**\n{}", episodic_text.join("\n")));
        }
    }

    // 3. Fact files (all *.md in fact/, capped at FACT_MAX_CHARS total)
    let fact_dir = base.join("fact");
    if let Ok(entries) = fs::read_dir(&fact_dir) {
        let mut fact_text = String::new();
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("md") {
                continue;
            }
            if let Ok(content) = fs::read_to_string(&path) {
                if fact_text.len() + content.len() > FACT_MAX_CHARS {
                    break;
                }
                let filename = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("unknown");
                fact_text.push_str(&format!("_{}_: {}\n", filename, content.trim()));
            }
        }
        if !fact_text.is_empty() {
            sections.push(format!("**Facts:**\n{}", fact_text.trim()));
        }
    }

    // 4. Shared facts (shared/fact/*.md accessible to all agents)
    let shared_fact_dir = memory_base().join("shared/fact");
    if let Ok(entries) = fs::read_dir(&shared_fact_dir) {
        let mut shared_text = String::new();
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("md") {
                continue;
            }
            if let Ok(content) = fs::read_to_string(&path) {
                if shared_text.len() + content.len() > FACT_MAX_CHARS {
                    break;
                }
                let filename = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("unknown");
                shared_text.push_str(&format!("_{}_: {}\n", filename, content.trim()));
            }
        }
        if !shared_text.is_empty() {
            sections.push(format!("**Shared Facts:**\n{}", shared_text.trim()));
        }
    }

    if sections.is_empty() {
        return String::new();
    }

    format!("[Memory Context]\n{}", sections.join("\n\n"))
}

// ============================================================================
// Observation extraction — scan Claude output for [REMEMBER] markers
// ============================================================================

/// Extract observations from Claude session output.
/// Scans for lines containing `[REMEMBER]` and appends them to scratchpad.md.
pub fn extract_observations(
    agent_name: &str,
    output: &str,
    rate_limiter: &mut MemoryRateLimiter,
) {
    let observations: Vec<&str> = output
        .lines()
        .filter(|line| line.contains("[REMEMBER]"))
        .collect();

    if observations.is_empty() {
        return;
    }

    if !rate_limiter.check(agent_name) {
        return;
    }

    let base = agent_memory_dir(agent_name);
    let scratchpad_path = base.join("scratchpad.md");

    let mut content = fs::read_to_string(&scratchpad_path).unwrap_or_default();

    for obs in &observations {
        let cleaned = obs.replace("[REMEMBER]", "").trim().to_string();
        if !cleaned.is_empty() {
            let timestamp = chrono::Utc::now().format("%Y-%m-%d %H:%M");
            content.push_str(&format!("\n- [{}] {}", timestamp, cleaned));
            debug!("[{}] Extracted observation: {}", agent_name, &cleaned[..cleaned.len().min(80)]);
        }
    }

    if let Err(e) = fs::write(&scratchpad_path, content) {
        warn!("[{}] Failed to write scratchpad: {}", agent_name, e);
    }
}

// ============================================================================
// Helpers
// ============================================================================

/// Read directory entries sorted by modification time (newest first).
fn read_dir_sorted_by_mtime(dir: &PathBuf) -> Result<Vec<(PathBuf, u64)>, std::io::Error> {
    let mut entries: Vec<(PathBuf, u64)> = fs::read_dir(dir)?
        .flatten()
        .filter_map(|entry| {
            let path = entry.path();
            if path.is_file() {
                let mtime = entry
                    .metadata()
                    .ok()?
                    .modified()
                    .ok()?
                    .duration_since(std::time::UNIX_EPOCH)
                    .ok()?
                    .as_secs();
                Some((path, mtime))
            } else {
                None
            }
        })
        .collect();

    entries.sort_by(|a, b| b.1.cmp(&a.1)); // newest first
    Ok(entries)
}
