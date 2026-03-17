/// Loop engine — LoopSpec loading/validation, ActiveLoop state machine, LoopManager.
/// Implements the autoscope Loop Spec contract defined in ATR002/FCT009.
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

// ============================================================================
// Loop Spec types (YAML schema)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LoopType {
    Researcher,
    Narrative,
    InfraImprove,
    Coding,
    Swarm,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum MetricDirection {
    HigherIsBetter,
    LowerIsBetter,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoopMetric {
    pub name: String,
    pub formula: String,
    pub baseline: f64,
    pub direction: MetricDirection,
    pub machine_readable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoopBudget {
    pub per_iteration: String,
    pub max_iterations: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum RollbackMethod {
    GitReset,
    ConfigRevert,
    FileDelete,
    TimerCancel,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RollbackMechanism {
    pub method: RollbackMethod,
    pub command: String,
    pub scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LoopApprovalGate {
    None,
    ProposeThenExecute,
    HumanApprovalRequired,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoopSpec {
    pub loop_id: String,
    pub name: String,
    pub objective: String,
    pub loop_type: LoopType,
    pub agent_id: String,
    pub metric: LoopMetric,
    pub frozen_harness: Vec<String>,
    pub mutable_surface: Vec<String>,
    pub budget: LoopBudget,
    pub rollback: RollbackMechanism,
    pub approval_gate: LoopApprovalGate,
    pub worker_cwd: Option<String>,
}

impl LoopSpec {
    /// Load and validate a Loop Spec from a YAML file.
    /// Validation rules:
    ///   - metric.machine_readable must be true
    ///   - frozen_harness must be non-empty
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .with_context(|| format!("Failed to read loop spec: {}", path.display()))?;
        let spec: LoopSpec = serde_yaml::from_str(&content)
            .with_context(|| format!("Failed to parse loop spec YAML: {}", path.display()))?;
        if !spec.metric.machine_readable {
            bail!("Loop spec '{}': metric '{}' must be machine_readable: true", spec.loop_id, spec.metric.name);
        }
        if spec.frozen_harness.is_empty() {
            bail!("Loop spec '{}': frozen_harness must be non-empty", spec.loop_id);
        }
        Ok(spec)
    }
}

// ============================================================================
// Active loop state machine
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LoopStatus {
    Pending,
    Running,
    Paused,
    Completed,
    Aborted,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IterationRecord {
    pub iteration: u32,
    pub metric_value: f64,
    pub delta: f64,
    pub tokens_used: u64,
    pub kept: bool,
    pub started_at: String,
    pub ended_at: String,
}

#[derive(Debug, Clone)]
pub struct ActiveLoop {
    pub loop_id: String,
    pub spec: LoopSpec,
    pub status: LoopStatus,
    pub current_iteration: u32,
    pub iteration_tokens_used: u64,
    pub total_tokens_used: u64,
    pub best_metric: Option<f64>,
    pub iterations: Vec<IterationRecord>,
}

impl ActiveLoop {
    pub fn new(spec: LoopSpec) -> Self {
        let loop_id = spec.loop_id.clone();
        Self {
            loop_id,
            spec,
            status: LoopStatus::Pending,
            current_iteration: 0,
            iteration_tokens_used: 0,
            total_tokens_used: 0,
            best_metric: None,
            iterations: Vec::new(),
        }
    }

    /// Parse the per_iteration token budget from strings like "50000 tokens" or "50000".
    fn parse_per_iteration_tokens(&self) -> u64 {
        let s = self.spec.budget.per_iteration.trim();
        // Take the first whitespace-delimited token and parse as u64
        s.split_whitespace()
            .next()
            .and_then(|n| n.parse::<u64>().ok())
            .unwrap_or(u64::MAX)
    }

    /// Returns true if iteration_tokens_used has exceeded the per-iteration budget.
    pub fn is_budget_exceeded(&self) -> bool {
        self.iteration_tokens_used >= self.parse_per_iteration_tokens()
    }

    /// Returns true if current_iteration has reached max_iterations.
    pub fn is_max_iterations_reached(&self) -> bool {
        self.current_iteration >= self.spec.budget.max_iterations
    }

    /// Returns true if new_value is an improvement over best_metric, considering direction.
    /// If no best metric exists yet, always returns true.
    pub fn is_metric_improved(&self, new_value: f64) -> bool {
        match self.best_metric {
            None => true,
            Some(best) => match self.spec.metric.direction {
                MetricDirection::HigherIsBetter => new_value > best,
                MetricDirection::LowerIsBetter => new_value < best,
            },
        }
    }

    /// Record a completed iteration. Updates best_metric, total_tokens_used, resets iteration_tokens_used.
    pub fn record_iteration(&mut self, metric_value: f64, tokens: u64, kept: bool) {
        let prev_best = self.best_metric.unwrap_or(self.spec.metric.baseline);
        let delta = match self.spec.metric.direction {
            MetricDirection::HigherIsBetter => metric_value - prev_best,
            MetricDirection::LowerIsBetter => prev_best - metric_value,
        };

        if kept {
            if self.is_metric_improved(metric_value) {
                self.best_metric = Some(metric_value);
            }
        }

        let now = chrono::Utc::now().to_rfc3339();
        self.iterations.push(IterationRecord {
            iteration: self.current_iteration,
            metric_value,
            delta,
            tokens_used: tokens,
            kept,
            started_at: now.clone(),
            ended_at: now,
        });

        self.total_tokens_used += tokens;
        self.iteration_tokens_used = 0;
    }
}

// ============================================================================
// LoopManager
// ============================================================================

pub struct LoopManager {
    active_loops: HashMap<String, ActiveLoop>,
}

impl LoopManager {
    pub fn new() -> Self {
        Self {
            active_loops: HashMap::new(),
        }
    }

    /// Load a Loop Spec from path, register as a new ActiveLoop, return loop_id.
    pub fn load_and_register(&mut self, spec_path: &Path) -> Result<String> {
        let spec = LoopSpec::load(spec_path)?;
        let loop_id = spec.loop_id.clone();
        self.active_loops.insert(loop_id.clone(), ActiveLoop::new(spec));
        Ok(loop_id)
    }

    pub fn start_loop(&mut self, loop_id: &str) -> Result<()> {
        let lp = self.active_loops.get_mut(loop_id)
            .with_context(|| format!("Loop not found: {}", loop_id))?;
        lp.status = LoopStatus::Running;
        lp.current_iteration = 1;
        Ok(())
    }

    pub fn advance_iteration(&mut self, loop_id: &str) -> Result<()> {
        let lp = self.active_loops.get_mut(loop_id)
            .with_context(|| format!("Loop not found: {}", loop_id))?;
        lp.current_iteration += 1;
        Ok(())
    }

    pub fn abort_loop(&mut self, loop_id: &str) -> Result<()> {
        let lp = self.active_loops.get_mut(loop_id)
            .with_context(|| format!("Loop not found: {}", loop_id))?;
        lp.status = LoopStatus::Aborted;
        Ok(())
    }

    pub fn complete_loop(&mut self, loop_id: &str) -> Result<()> {
        let lp = self.active_loops.get_mut(loop_id)
            .with_context(|| format!("Loop not found: {}", loop_id))?;
        lp.status = LoopStatus::Completed;
        Ok(())
    }

    /// Returns true if the given path is in the frozen_harness of any Running loop for agent_id.
    pub fn is_frozen(&self, agent_id: &str, path: &str) -> bool {
        self.active_loops.values()
            .filter(|lp| lp.status == LoopStatus::Running && lp.spec.agent_id == agent_id)
            .any(|lp| {
                lp.spec.frozen_harness.iter().any(|frozen| {
                    let f = frozen.as_str();
                    path == f || path.starts_with(f) || path.starts_with(&format!("{}/", f.trim_end_matches('/')))
                })
            })
    }

    /// Add tokens to iteration_tokens_used for a loop. Returns true if budget now exceeded.
    pub fn deduct_iteration_tokens(&mut self, loop_id: &str, tokens: u64) -> Result<bool> {
        let lp = self.active_loops.get_mut(loop_id)
            .with_context(|| format!("Loop not found: {}", loop_id))?;
        lp.iteration_tokens_used += tokens;
        lp.total_tokens_used += tokens;
        Ok(lp.is_budget_exceeded())
    }

    /// Get all Running ActiveLoops for the given agent_id.
    pub fn get_active_loops_for_agent(&self, agent_id: &str) -> Vec<&ActiveLoop> {
        self.active_loops.values()
            .filter(|lp| lp.spec.agent_id == agent_id && lp.status == LoopStatus::Running)
            .collect()
    }

    /// Get a reference to an ActiveLoop by loop_id.
    pub fn get_loop(&self, loop_id: &str) -> Option<&ActiveLoop> {
        self.active_loops.get(loop_id)
    }

    /// List all active loops (any status).
    pub fn all_loops(&self) -> impl Iterator<Item = &ActiveLoop> {
        self.active_loops.values()
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_temp_spec(content: &str) -> tempfile::NamedTempFile {
        let mut f = tempfile::NamedTempFile::new().unwrap();
        f.write_all(content.as_bytes()).unwrap();
        f
    }

    fn valid_spec_yaml(loop_id: &str) -> String {
        format!(r#"
loop_id: "{loop_id}"
name: "Test Loop"
objective: "Improve recall@10"
loop_type: researcher
agent_id: "boot"
metric:
  name: "recall@10"
  formula: "correct / total"
  baseline: 0.5
  direction: higher_is_better
  machine_readable: true
frozen_harness:
  - "tests/"
  - "eval.sh"
mutable_surface:
  - "src/"
budget:
  per_iteration: "50000 tokens"
  max_iterations: 10
rollback:
  method: git_reset
  command: "git reset --hard HEAD~1"
  scope: "src/"
approval_gate: none
"#, loop_id = loop_id)
    }

    #[test]
    fn spec_load_rejects_non_machine_readable_metric() {
        let yaml = r#"
loop_id: "test"
name: "Test"
objective: "obj"
loop_type: researcher
agent_id: "boot"
metric:
  name: "recall"
  formula: "x"
  baseline: 0.5
  direction: higher_is_better
  machine_readable: false
frozen_harness: ["tests/"]
mutable_surface: ["src/"]
budget:
  per_iteration: "1000 tokens"
  max_iterations: 5
rollback:
  method: git_reset
  command: "git reset --hard HEAD"
  scope: "src/"
approval_gate: none
"#;
        let f = write_temp_spec(yaml);
        assert!(LoopSpec::load(f.path()).is_err());
    }

    #[test]
    fn spec_load_rejects_empty_frozen_harness() {
        let yaml = r#"
loop_id: "test"
name: "Test"
objective: "obj"
loop_type: researcher
agent_id: "boot"
metric:
  name: "recall"
  formula: "x"
  baseline: 0.5
  direction: higher_is_better
  machine_readable: true
frozen_harness: []
mutable_surface: ["src/"]
budget:
  per_iteration: "1000 tokens"
  max_iterations: 5
rollback:
  method: git_reset
  command: "git reset --hard HEAD"
  scope: "src/"
approval_gate: none
"#;
        let f = write_temp_spec(yaml);
        assert!(LoopSpec::load(f.path()).is_err());
    }

    #[test]
    fn spec_load_valid() {
        let f = write_temp_spec(&valid_spec_yaml("loop-001"));
        let spec = LoopSpec::load(f.path()).unwrap();
        assert_eq!(spec.loop_id, "loop-001");
        assert_eq!(spec.budget.max_iterations, 10);
        assert_eq!(spec.frozen_harness.len(), 2);
    }

    #[test]
    fn iteration_lifecycle() {
        let f = write_temp_spec(&valid_spec_yaml("loop-002"));
        let spec = LoopSpec::load(f.path()).unwrap();
        let mut active = ActiveLoop::new(spec);

        assert!(active.best_metric.is_none());

        active.record_iteration(0.6, 1000, true);
        assert_eq!(active.best_metric, Some(0.6));
        assert_eq!(active.iterations.len(), 1);
        assert_eq!(active.iteration_tokens_used, 0); // reset after record

        active.record_iteration(0.7, 2000, true);
        assert_eq!(active.best_metric, Some(0.7));
        assert_eq!(active.total_tokens_used, 3000);
    }

    #[test]
    fn frozen_path_matching() {
        let f = write_temp_spec(&valid_spec_yaml("loop-003"));
        let spec = LoopSpec::load(f.path()).unwrap();
        let mut mgr = LoopManager::new();
        // Manually insert a running loop
        let mut active = ActiveLoop::new(spec);
        active.status = LoopStatus::Running;
        mgr.active_loops.insert("loop-003".to_string(), active);

        // Exact match
        assert!(mgr.is_frozen("boot", "tests/"));
        // Prefix match
        assert!(mgr.is_frozen("boot", "tests/foo.py"));
        // Exact harness file
        assert!(mgr.is_frozen("boot", "eval.sh"));
        // Non-frozen
        assert!(!mgr.is_frozen("boot", "src/main.rs"));
        // Wrong agent
        assert!(!mgr.is_frozen("ig88", "tests/"));
    }

    #[test]
    fn budget_exceeded_detection() {
        let f = write_temp_spec(&valid_spec_yaml("loop-004"));
        let spec = LoopSpec::load(f.path()).unwrap();
        let mut mgr = LoopManager::new();
        mgr.active_loops.insert("loop-004".to_string(), ActiveLoop::new(spec));

        // per_iteration is "50000 tokens"
        let exceeded = mgr.deduct_iteration_tokens("loop-004", 30_000).unwrap();
        assert!(!exceeded);
        let exceeded = mgr.deduct_iteration_tokens("loop-004", 20_001).unwrap();
        assert!(exceeded);
    }

    #[test]
    fn metric_improvement_higher_is_better() {
        let f = write_temp_spec(&valid_spec_yaml("loop-005"));
        let spec = LoopSpec::load(f.path()).unwrap();
        let mut active = ActiveLoop::new(spec);
        active.best_metric = Some(0.6);
        assert!(active.is_metric_improved(0.7));
        assert!(!active.is_metric_improved(0.5));
    }

    #[test]
    fn metric_improvement_lower_is_better() {
        let yaml = valid_spec_yaml("loop-006").replace("higher_is_better", "lower_is_better");
        let f = write_temp_spec(&yaml);
        let spec = LoopSpec::load(f.path()).unwrap();
        let mut active = ActiveLoop::new(spec);
        active.best_metric = Some(0.4);
        assert!(active.is_metric_improved(0.3));
        assert!(!active.is_metric_improved(0.5));
    }
}
