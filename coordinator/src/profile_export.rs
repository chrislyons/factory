/// Agent profile export — serializes a full agent snapshot as a portable YAML bundle.
/// Used for debugging, onboarding, and cross-system profile transfer.
use serde::Serialize;
use std::collections::HashMap;

use crate::config::{Config, ContextMode, ProviderType, SandboxProfile};
use crate::runtime_state::AgentRuntimeState;

// ============================================================================
// Export structs (public, serialization-only)
// ============================================================================

#[derive(Debug, Serialize)]
pub struct ProfileExport {
    pub generated_at: String,
    pub agent_name: String,
    pub agent_config: AgentConfigExport,
    pub provider_chain: Vec<ProviderExport>,
    pub rooms: Vec<RoomExport>,
    /// Identity file paths only — content is NOT included.
    pub identity_files: Vec<String>,
    pub runtime_stats: Option<RuntimeStatsExport>,
}

#[derive(Debug, Serialize)]
pub struct AgentConfigExport {
    pub matrix_user: String,
    pub description: String,
    pub trust_level: Option<u8>,
    pub trust_domains: Vec<String>,
    pub context_mode: String,
    pub sandbox_profile: String,
    pub default_device: String,
    pub default_cwd: Option<String>,
    pub mention_aliases: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct ProviderExport {
    pub name: String,
    pub model: String,
    pub fallback_model: String,
    pub health_url: String,
    pub provider_type: String,
    pub timeout_ms: Option<u64>,
    pub retry_count: u32,
}

#[derive(Debug, Serialize)]
pub struct RoomExport {
    pub name: String,
    pub room_id: String,
    pub worker_cwd: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct RuntimeStatsExport {
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub total_cost_cents: f64,
    pub last_run_status: String,
    pub last_error: Option<String>,
    pub updated_at: String,
    pub provider_stats: HashMap<String, ProviderStatsExport>,
}

#[derive(Debug, Serialize)]
pub struct ProviderStatsExport {
    pub total_requests: u64,
    pub total_failures: u64,
    pub total_tokens: u64,
    pub total_cost_cents: f64,
    pub avg_latency_ms: f64,
}

// ============================================================================
// Helpers — enum-to-string conversions
// ============================================================================

fn context_mode_str(mode: &ContextMode) -> &'static str {
    match mode {
        ContextMode::Fat => "fat",
        ContextMode::Thin => "thin",
    }
}

fn sandbox_profile_str(profile: &SandboxProfile) -> &'static str {
    match profile {
        SandboxProfile::Personal => "personal",
        SandboxProfile::Work => "work",
        SandboxProfile::Restricted => "restricted",
    }
}

fn provider_type_str(pt: &ProviderType) -> &'static str {
    match pt {
        ProviderType::Local => "local",
        ProviderType::Cloud => "cloud",
        ProviderType::Fallback => "fallback",
    }
}

// ============================================================================
// Export function
// ============================================================================

/// Build a YAML-serialized profile snapshot for the named agent.
///
/// Collects agent config, room assignments, provider chain, identity file paths,
/// and optional runtime stats into a single portable document.
pub fn export_agent_profile(
    agent_name: &str,
    config: &Config,
    runtime_state: Option<&AgentRuntimeState>,
) -> anyhow::Result<String> {
    // Look up the agent
    let agent = config
        .agents
        .get(agent_name)
        .ok_or_else(|| anyhow::anyhow!("agent '{}' not found in config", agent_name))?;

    // Build AgentConfigExport
    let agent_config = AgentConfigExport {
        matrix_user: agent.matrix_user.clone(),
        description: agent.description.clone(),
        trust_level: agent.trust_level,
        trust_domains: agent.trust_domains.clone(),
        context_mode: context_mode_str(&agent.context_mode).to_string(),
        sandbox_profile: sandbox_profile_str(&agent.sandbox_profile).to_string(),
        default_device: agent.default_device.clone(),
        default_cwd: agent.default_cwd.clone(),
        mention_aliases: agent.mention_aliases.clone(),
    };

    // Collect rooms where this agent is assigned
    let rooms: Vec<RoomExport> = config
        .rooms
        .iter()
        .filter(|(_, room)| {
            room.agents.contains(&agent_name.to_string())
                || room.default_agent.as_deref() == Some(agent_name)
                || room.all_agents_listen
        })
        .map(|(room_id, room)| RoomExport {
            name: room.name.clone(),
            room_id: room_id.clone(),
            worker_cwd: room.worker_cwd.clone(),
        })
        .collect();

    // Identity file paths
    let identity_files: Vec<String> = match &agent.identity_files {
        Some(ids) => vec![ids.soul.clone(), ids.principles.clone(), ids.agents.clone()],
        None => vec![],
    };

    // Provider chain
    let provider_chain: Vec<ProviderExport> = config
        .settings
        .llm_providers
        .iter()
        .map(|p| ProviderExport {
            name: p.name.clone(),
            model: p.model.clone(),
            fallback_model: p.fallback_model.clone(),
            health_url: p.health_url.clone(),
            provider_type: provider_type_str(&p.provider_type).to_string(),
            timeout_ms: p.timeout_ms,
            retry_count: p.retry_count,
        })
        .collect();

    // Runtime stats (optional)
    let runtime_stats = runtime_state.map(|rs| RuntimeStatsExport {
        total_input_tokens: rs.total_input_tokens,
        total_output_tokens: rs.total_output_tokens,
        total_cost_cents: rs.total_cost_cents,
        last_run_status: rs.last_run_status.clone(),
        last_error: rs.last_error.clone(),
        updated_at: rs.updated_at.clone(),
        provider_stats: rs
            .provider_stats
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    ProviderStatsExport {
                        total_requests: v.total_requests,
                        total_failures: v.total_failures,
                        total_tokens: v.total_tokens,
                        total_cost_cents: v.total_cost_cents,
                        avg_latency_ms: v.avg_latency_ms,
                    },
                )
            })
            .collect(),
    });

    let export = ProfileExport {
        generated_at: chrono::Utc::now().to_rfc3339(),
        agent_name: agent_name.to_string(),
        agent_config,
        provider_chain,
        rooms,
        identity_files,
        runtime_stats,
    };

    serde_yaml::to_string(&export)
        .map_err(|e| anyhow::anyhow!("YAML serialization failed: {}", e))
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::*;
    use crate::runtime_state::{AgentRuntimeState, ProviderStats};
    use std::collections::HashMap;

    /// Build a minimal Config with one agent and one room for testing.
    fn test_config() -> Config {
        let mut agents = HashMap::new();
        agents.insert(
            "boot".to_string(),
            AgentConfig {
                matrix_user: "@boot:matrix.org".to_string(),
                token_env: "MATRIX_TOKEN_BOOT".to_string(),
                description: "Dev agent".to_string(),
                sandbox_profile: SandboxProfile::Personal,
                default_device: "whitebox".to_string(),
                trust_level: Some(3),
                trust_domains: vec!["dev".to_string(), "ops".to_string()],
                ssh_dispatch: vec![],
                system_prompt: None,
                identity_files: Some(IdentityFiles {
                    soul: "soul.md".to_string(),
                    principles: "principles.md".to_string(),
                    agents: "agents.md".to_string(),
                }),
                mention_aliases: vec!["@boot".to_string()],
                default_cwd: Some("/home/boot/work".to_string()),
                context_mode: ContextMode::Fat,
                password_env: None,
                recovery_key_env: None,
            },
        );

        let mut rooms = HashMap::new();
        rooms.insert(
            "!abc123:matrix.org".to_string(),
            Room {
                name: "boot-ops".to_string(),
                prefix: Some("OPS".to_string()),
                default_agent: Some("boot".to_string()),
                agents: vec!["boot".to_string()],
                all_agents_listen: false,
                graphiti_group: None,
                sandbox_profile: SandboxProfile::Work,
                worker_cwd: Some("/home/boot/ops".to_string()),
                tmux_session: None,
                require_mention: false,
                approval_delegate: None,
            },
        );

        let providers = vec![LLMProviderConfig {
            name: "anthropic".to_string(),
            cli: "claude".to_string(),
            model: "opus-4".to_string(),
            fallback_model: "sonnet-4".to_string(),
            health_url: "https://api.anthropic.com/health".to_string(),
            env: HashMap::new(),
            timeout_ms: Some(30000),
            retry_count: 2,
            backoff_ms: 1000,
            provider_type: ProviderType::Cloud,
        }];

        Config {
            settings: Settings {
                dm_policy: DmPolicy::Respond,
                group_policy: GroupPolicy::Mention,
                fallback_device: "whitebox".to_string(),
                pantalaimon_url: None,
                graphiti_url: None,
                graphiti_token_env: None,
                credential_source: None,
                credential_path: None,
                claude_timeout_ms: 120000,
                ssh_timeout_ms: 30000,
                approval_timeout_ms: 600000,
                approval_owner: "@chris:matrix.org".to_string(),
                approval_dir: None,
                max_claude_sessions: 4,
                auto_approve_patterns: vec![],
                always_require_approval: vec![],
                trusted_ssh_hosts: vec![],
                multi_agent_stagger_ms: 500,
                multi_agent_max_wait_ms: 5000,
                multi_agent_post_signal_delay_ms: 200,
                multi_agent_context_char_limit: 8000,
                llm_providers: providers,
                llm_health_check_interval_ms: None,
                llm_health_check_timeout_ms: None,
                failover_strategy: None,
                health_score_window_ms: None,
                breaker_consecutive_timeout_threshold: None,
                breaker_pause_duration_ms: None,
                degradation_warning_ms: None,
                degradation_tool_rejection_threshold: None,
                degradation_timeout_threshold: None,
                delegate_timeout_ms: 60000,
                delegate_device: "whitebox".to_string(),
                delegate_auto_approve_tools: vec![],
                delegate_auto_approve_bash: vec![],
                delegate_require_approval_bash: vec![],
                timer_dir: None,
                timer_check_interval_ms: None,
                loop_specs_dir: None,
                loop_state_file: None,
                loop_max_concurrent: None,
                e2ee: None,
                infra_docker_containers: None,
                infra_systemd_services: None,
                infra_launchd_services: None,
                infra_tailscale_peers: None,
            },
            allowlist: vec![],
            devices: HashMap::new(),
            agents,
            rooms,
            budget: None,
        }
    }

    #[test]
    fn export_produces_valid_yaml() {
        let config = test_config();
        let yaml = export_agent_profile("boot", &config, None).unwrap();

        assert!(yaml.contains("agent_name: boot"));
        assert!(yaml.contains("matrix_user: '@boot:matrix.org'"));
        assert!(yaml.contains("context_mode: fat"));
        assert!(yaml.contains("sandbox_profile: personal"));
        assert!(yaml.contains("model: opus-4"));
        assert!(yaml.contains("name: boot-ops"));
        assert!(yaml.contains("soul.md"));
    }

    #[test]
    fn export_includes_runtime_stats() {
        let config = test_config();

        let mut provider_stats = HashMap::new();
        provider_stats.insert(
            "anthropic".to_string(),
            ProviderStats {
                total_requests: 42,
                total_failures: 1,
                total_tokens: 50000,
                total_cost_cents: 125.5,
                avg_latency_ms: 1200.0,
            },
        );

        let runtime = AgentRuntimeState {
            agent_id: "boot".to_string(),
            session_id: Some("sess-abc".to_string()),
            total_input_tokens: 30000,
            total_output_tokens: 20000,
            total_cost_cents: 125.5,
            last_run_status: "success".to_string(),
            last_error: None,
            updated_at: "2026-04-02T10:00:00Z".to_string(),
            provider_stats,
        };

        let yaml = export_agent_profile("boot", &config, Some(&runtime)).unwrap();

        assert!(yaml.contains("total_input_tokens: 30000"));
        assert!(yaml.contains("total_output_tokens: 20000"));
        assert!(yaml.contains("total_cost_cents: 125.5"));
        assert!(yaml.contains("last_run_status: success"));
        assert!(yaml.contains("total_requests: 42"));
    }

    #[test]
    fn export_unknown_agent_returns_error() {
        let config = test_config();
        let result = export_agent_profile("nonexistent", &config, None);

        assert!(result.is_err());
        assert!(
            result
                .unwrap_err()
                .to_string()
                .contains("agent 'nonexistent' not found")
        );
    }
}
