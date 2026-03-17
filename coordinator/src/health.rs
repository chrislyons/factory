// Health Scorer — Agent Health Metric Calculation
// BKX042: Agent health tracking with degradation detection
// Port of health-scorer.ts

use std::time::{Duration, Instant};

/// Types of health incidents that affect the agent score.
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IncidentType {
    Timeout,         // -10 per incident
    ToolFailure,     // -5 per incident
    ApprovalTimeout, // -3 per incident
    SlowResponse,    // -2 per incident
}

impl IncidentType {
    /// Point deduction for this incident type.
    fn deduction(&self) -> i32 {
        match self {
            IncidentType::Timeout => 10,
            IncidentType::ToolFailure => 5,
            IncidentType::ApprovalTimeout => 3,
            IncidentType::SlowResponse => 2,
        }
    }
}

/// A recorded health incident.
#[allow(dead_code)]
#[derive(Debug, Clone)]
pub struct HealthIncident {
    pub incident_type: IncidentType,
    pub timestamp: Instant,
    pub value: Option<u64>,
    pub details: Option<String>,
}

/// Calculates agent health score (0-100) based on incident history within a
/// rolling time window. Default window: 30 minutes.
pub struct HealthScorer {
    window: Duration,
    incidents: Vec<HealthIncident>,
}

impl HealthScorer {
    /// Create a new scorer with the given window in milliseconds.
    pub fn new(window_ms: u64) -> Self {
        Self {
            window: Duration::from_millis(window_ms),
            incidents: Vec::new(),
        }
    }

    /// Record a health incident.
    pub fn record_incident(
        &mut self,
        t: IncidentType,
        details: Option<&str>,
        value: Option<u64>,
    ) {
        self.incidents.push(HealthIncident {
            incident_type: t,
            timestamp: Instant::now(),
            value,
            details: details.map(String::from),
        });
        self.prune_old();
    }

    /// Calculate current health score (0..=100).
    /// Base 100 minus deductions for each incident in the window.
    pub fn get_score(&mut self) -> i32 {
        self.prune_old();
        let deduction: i32 = self
            .incidents
            .iter()
            .map(|i| i.incident_type.deduction())
            .sum();
        (100 - deduction).clamp(0, 100)
    }

    /// Status indicator emoji based on score.
    pub fn get_status_indicator(&mut self) -> &'static str {
        let score = self.get_score();
        if score >= 80 {
            "✅"
        } else if score >= 60 {
            "⚠️"
        } else if score >= 40 {
            "🔴"
        } else {
            "💥"
        }
    }

    /// True if health score warrants degradation warnings (score < 50).
    #[allow(dead_code)]
    pub fn should_warn_degradation(&mut self) -> bool {
        self.get_score() < 50
    }

    /// True if health score is critical (score < 40).
    #[allow(dead_code)]
    pub fn is_critical(&mut self) -> bool {
        self.get_score() < 40
    }

    /// Check if the count of a specific incident type meets or exceeds a threshold.
    #[allow(dead_code)]
    pub fn exceeds_threshold(&self, t: &IncidentType, count: usize) -> bool {
        self.incidents
            .iter()
            .filter(|i| i.incident_type == *t)
            .count()
            >= count
    }

    /// Clear all incidents (used on recovery).
    pub fn reset(&mut self) {
        self.incidents.clear();
    }

    /// Remove incidents older than the window.
    fn prune_old(&mut self) {
        let cutoff = Instant::now() - self.window;
        self.incidents.retain(|i| i.timestamp > cutoff);
    }
}

impl Default for HealthScorer {
    fn default() -> Self {
        Self::new(1_800_000) // 30 minutes
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fresh_score_is_100() {
        let mut scorer = HealthScorer::default();
        assert_eq!(scorer.get_score(), 100);
        assert_eq!(scorer.get_status_indicator(), "✅");
    }

    #[test]
    fn test_timeout_deduction() {
        let mut scorer = HealthScorer::default();
        scorer.record_incident(IncidentType::Timeout, None, None);
        assert_eq!(scorer.get_score(), 90);
    }

    #[test]
    fn test_multiple_incidents() {
        let mut scorer = HealthScorer::default();
        scorer.record_incident(IncidentType::Timeout, None, None);        // -10
        scorer.record_incident(IncidentType::ToolFailure, None, None);    // -5
        scorer.record_incident(IncidentType::ApprovalTimeout, None, None); // -3
        scorer.record_incident(IncidentType::SlowResponse, None, None);   // -2
        assert_eq!(scorer.get_score(), 80); // 100 - 20
        assert_eq!(scorer.get_status_indicator(), "✅"); // exactly 80
    }

    #[test]
    fn test_critical_threshold() {
        let mut scorer = HealthScorer::default();
        // 4 timeouts = -40 → score 60
        for _ in 0..4 {
            scorer.record_incident(IncidentType::Timeout, None, None);
        }
        assert_eq!(scorer.get_score(), 60);
        assert!(!scorer.is_critical());

        // 3 more = -70 → score 30
        for _ in 0..3 {
            scorer.record_incident(IncidentType::Timeout, None, None);
        }
        assert_eq!(scorer.get_score(), 30);
        assert!(scorer.is_critical());
        assert_eq!(scorer.get_status_indicator(), "💥");
    }

    #[test]
    fn test_exceeds_threshold() {
        let mut scorer = HealthScorer::default();
        scorer.record_incident(IncidentType::ToolFailure, Some("disk error"), None);
        scorer.record_incident(IncidentType::ToolFailure, None, None);
        assert!(scorer.exceeds_threshold(&IncidentType::ToolFailure, 2));
        assert!(!scorer.exceeds_threshold(&IncidentType::ToolFailure, 3));
    }

    #[test]
    fn test_reset() {
        let mut scorer = HealthScorer::default();
        for _ in 0..5 {
            scorer.record_incident(IncidentType::Timeout, None, None);
        }
        assert!(scorer.get_score() < 100);
        scorer.reset();
        assert_eq!(scorer.get_score(), 100);
    }

    #[test]
    fn test_score_clamps_at_zero() {
        let mut scorer = HealthScorer::default();
        for _ in 0..15 {
            scorer.record_incident(IncidentType::Timeout, None, None);
        }
        assert_eq!(scorer.get_score(), 0);
    }
}
