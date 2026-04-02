//! Provider failover chain for LLM inference routing.
//!
//! Manages an ordered list of LLM providers with health tracking and
//! automatic failover. When the active provider fails beyond its retry
//! threshold, the chain advances to the next provider.

use crate::config::LLMProviderConfig;
use std::time::Instant;

/// Events emitted by the provider chain on state transitions.
#[derive(Debug, Clone)]
pub enum ProviderEvent {
    /// Active provider changed due to failures.
    Failover {
        from: String,
        to: String,
        reason: String,
    },
    /// All providers in the chain have been exhausted.
    Exhausted {
        tried: Vec<String>,
    },
    /// A previously failed provider has recovered (health check passed).
    Recovered {
        provider: String,
    },
}

/// Per-provider health tracking.
#[derive(Debug, Clone)]
pub struct ProviderHealth {
    pub consecutive_failures: u32,
    pub last_success: Option<Instant>,
    pub last_failure: Option<Instant>,
    pub total_successes: u64,
    pub total_failures: u64,
    pub total_latency_ms: u64,
    pub request_count: u64,
}

impl ProviderHealth {
    fn new() -> Self {
        Self {
            consecutive_failures: 0,
            last_success: None,
            last_failure: None,
            total_successes: 0,
            total_failures: 0,
            total_latency_ms: 0,
            request_count: 0,
        }
    }

    pub fn avg_latency_ms(&self) -> f64 {
        if self.request_count == 0 {
            0.0
        } else {
            self.total_latency_ms as f64 / self.request_count as f64
        }
    }
}

/// Metrics snapshot for a single provider (for HUD/portal display).
#[derive(Debug, Clone)]
pub struct ProviderMetrics {
    pub name: String,
    pub is_active: bool,
    pub consecutive_failures: u32,
    pub total_successes: u64,
    pub total_failures: u64,
    pub avg_latency_ms: f64,
}

/// Ordered provider failover chain.
pub struct ProviderChain {
    providers: Vec<LLMProviderConfig>,
    health: Vec<ProviderHealth>,
    active_index: usize,
}

impl ProviderChain {
    /// Create a new chain from config. Panics if providers is empty.
    pub fn new(providers: Vec<LLMProviderConfig>) -> Self {
        assert!(!providers.is_empty(), "ProviderChain requires at least one provider");
        let health = providers.iter().map(|_| ProviderHealth::new()).collect();
        Self {
            providers,
            health,
            active_index: 0,
        }
    }

    /// Get the currently active provider.
    pub fn current(&self) -> &LLMProviderConfig {
        &self.providers[self.active_index]
    }

    /// Get the current active index.
    pub fn active_index(&self) -> usize {
        self.active_index
    }

    /// Record a successful inference or health check.
    pub fn record_success(&mut self, provider_name: &str, latency_ms: u64) {
        if let Some(idx) = self.find_provider(provider_name) {
            let h = &mut self.health[idx];
            h.consecutive_failures = 0;
            h.last_success = Some(Instant::now());
            h.total_successes += 1;
            h.total_latency_ms += latency_ms;
            h.request_count += 1;
        }
    }

    /// Record a failure. Returns a ProviderEvent if the failure triggers
    /// a state transition (failover or exhaustion).
    pub fn record_failure(&mut self, provider_name: &str, error: &str) -> Option<ProviderEvent> {
        let idx = match self.find_provider(provider_name) {
            Some(i) => i,
            None => return None,
        };

        let retry_count = self.providers[idx].retry_count;
        let h = &mut self.health[idx];
        h.consecutive_failures += 1;
        h.last_failure = Some(Instant::now());
        h.total_failures += 1;

        // Only trigger failover for the active provider
        if idx != self.active_index {
            return None;
        }

        // Check if we've exceeded retry count
        if h.consecutive_failures > retry_count {
            self.advance_with_reason(error)
        } else {
            None
        }
    }

    /// Record a health check result. Returns Recovered event if a previously
    /// failed primary provider is now healthy.
    pub fn record_health_check(&mut self, provider_name: &str, healthy: bool) -> Option<ProviderEvent> {
        if healthy {
            self.record_success(provider_name, 0);
            // If the primary provider recovered and we're on a fallback, signal recovery
            if self.active_index > 0 {
                if let Some(idx) = self.find_provider(provider_name) {
                    if idx == 0 && self.health[0].consecutive_failures == 0 {
                        return Some(ProviderEvent::Recovered {
                            provider: provider_name.to_string(),
                        });
                    }
                }
            }
            None
        } else {
            self.record_failure(provider_name, "health check failed")
        }
    }

    /// Reset to the primary (first) provider. Used when primary recovers.
    pub fn reset_to_primary(&mut self) -> Option<ProviderEvent> {
        if self.active_index == 0 {
            return None;
        }
        let from = self.providers[self.active_index].name.clone();
        let to = self.providers[0].name.clone();
        self.active_index = 0;
        Some(ProviderEvent::Failover {
            from,
            to,
            reason: "primary provider recovered".to_string(),
        })
    }

    /// Get metrics for all providers (for HUD display).
    pub fn get_metrics(&self) -> Vec<ProviderMetrics> {
        self.providers
            .iter()
            .enumerate()
            .map(|(i, p)| {
                let h = &self.health[i];
                ProviderMetrics {
                    name: p.name.clone(),
                    is_active: i == self.active_index,
                    consecutive_failures: h.consecutive_failures,
                    total_successes: h.total_successes,
                    total_failures: h.total_failures,
                    avg_latency_ms: h.avg_latency_ms(),
                }
            })
            .collect()
    }

    /// Number of providers in the chain.
    pub fn len(&self) -> usize {
        self.providers.len()
    }

    /// Advance to the next provider with the given failure reason.
    fn advance_with_reason(&mut self, reason: &str) -> Option<ProviderEvent> {
        let from = self.providers[self.active_index].name.clone();
        let next_index = self.active_index + 1;

        if next_index >= self.providers.len() {
            // All providers exhausted
            let tried: Vec<String> = self.providers.iter().map(|p| p.name.clone()).collect();
            Some(ProviderEvent::Exhausted { tried })
        } else {
            self.active_index = next_index;
            let to = self.providers[self.active_index].name.clone();
            Some(ProviderEvent::Failover {
                from,
                to,
                reason: reason.to_string(),
            })
        }
    }

    fn find_provider(&self, name: &str) -> Option<usize> {
        self.providers.iter().position(|p| p.name == name)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::LLMProviderConfig;
    use std::collections::HashMap;

    fn make_provider(name: &str) -> LLMProviderConfig {
        LLMProviderConfig {
            name: name.to_string(),
            cli: "claude".to_string(),
            model: "test-model".to_string(),
            fallback_model: "test-fallback".to_string(),
            health_url: format!("http://localhost/{}", name),
            env: HashMap::new(),
            timeout_ms: None,
            retry_count: 1, // fail after 1 retry (2 total failures)
            backoff_ms: 1000,
            provider_type: crate::config::ProviderType::Cloud,
        }
    }

    #[test]
    fn new_chain_starts_at_first_provider() {
        let chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        assert_eq!(chain.current().name, "primary");
        assert_eq!(chain.active_index(), 0);
    }

    #[test]
    #[should_panic(expected = "at least one provider")]
    fn empty_chain_panics() {
        ProviderChain::new(vec![]);
    }

    #[test]
    fn single_failure_does_not_failover() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        let event = chain.record_failure("primary", "timeout");
        assert!(event.is_none());
        assert_eq!(chain.current().name, "primary");
    }

    #[test]
    fn consecutive_failures_trigger_failover() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        chain.record_failure("primary", "timeout"); // failure 1
        let event = chain.record_failure("primary", "timeout"); // failure 2 > retry_count(1)
        assert!(matches!(event, Some(ProviderEvent::Failover { .. })));
        assert_eq!(chain.current().name, "secondary");
    }

    #[test]
    fn success_resets_failure_counter() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        chain.record_failure("primary", "timeout");
        chain.record_success("primary", 100);
        // After reset, need 2 more failures to failover
        let event = chain.record_failure("primary", "timeout");
        assert!(event.is_none());
        assert_eq!(chain.current().name, "primary");
    }

    #[test]
    fn chain_exhaustion() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        // Exhaust primary
        chain.record_failure("primary", "timeout");
        chain.record_failure("primary", "timeout");
        assert_eq!(chain.current().name, "secondary");
        // Exhaust secondary
        chain.record_failure("secondary", "timeout");
        let event = chain.record_failure("secondary", "timeout");
        assert!(matches!(event, Some(ProviderEvent::Exhausted { .. })));
    }

    #[test]
    fn reset_to_primary() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        chain.record_failure("primary", "timeout");
        chain.record_failure("primary", "timeout");
        assert_eq!(chain.current().name, "secondary");
        let event = chain.reset_to_primary();
        assert!(matches!(event, Some(ProviderEvent::Failover { .. })));
        assert_eq!(chain.current().name, "primary");
    }

    #[test]
    fn reset_when_already_primary_is_noop() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        let event = chain.reset_to_primary();
        assert!(event.is_none());
    }

    #[test]
    fn health_check_recovery_signals_event() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        // Failover to secondary
        chain.record_failure("primary", "down");
        chain.record_failure("primary", "down");
        assert_eq!(chain.current().name, "secondary");
        // Primary recovers via health check
        let event = chain.record_health_check("primary", true);
        assert!(matches!(event, Some(ProviderEvent::Recovered { .. })));
    }

    #[test]
    fn metrics_reflect_state() {
        let mut chain = ProviderChain::new(vec![make_provider("a"), make_provider("b")]);
        chain.record_success("a", 100);
        chain.record_success("a", 200);
        chain.record_failure("b", "err");
        let metrics = chain.get_metrics();
        assert_eq!(metrics.len(), 2);
        assert!(metrics[0].is_active);
        assert_eq!(metrics[0].total_successes, 2);
        assert_eq!(metrics[0].avg_latency_ms, 150.0);
        assert!(!metrics[1].is_active);
        assert_eq!(metrics[1].total_failures, 1);
    }

    #[test]
    fn failure_on_non_active_provider_does_not_trigger_failover() {
        let mut chain = ProviderChain::new(vec![make_provider("primary"), make_provider("secondary")]);
        // Fail the secondary (not active)
        let event = chain.record_failure("secondary", "err");
        assert!(event.is_none());
        assert_eq!(chain.current().name, "primary");
    }
}
