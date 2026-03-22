/// Infrastructure health checks — Docker containers, systemd services, Tailscale peers.
/// Phase 3F: Runs every 5 minutes, feeds data into Status HUD, alerts on state changes.
use std::collections::HashMap;
use tokio::process::Command;
use tracing::{debug, warn};

// ============================================================================
// Health check targets
// ============================================================================

const DOCKER_CONTAINERS: &[&str] = &["qdrant", "graphiti-mcp", "falkordb"];
const SYSTEMD_SERVICES: &[&str] = &["ollama", "qdrant-mcp"];
const TAILSCALE_PEERS: &[&str] = &["cloudkicker", "greybox"];

/// How many consecutive checks a state must persist before alerting.
const FLAP_SUPPRESSION_COUNT: u8 = 2;

// ============================================================================
// Types
// ============================================================================

#[derive(Debug, Clone)]
pub struct ServiceStatus {
    pub name: String,
    pub healthy: bool,
    pub service_type: ServiceType,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ServiceType {
    Docker,
    Systemd,
    Tailscale,
}

impl std::fmt::Display for ServiceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Docker => write!(f, "docker"),
            Self::Systemd => write!(f, "systemd"),
            Self::Tailscale => write!(f, "tailscale"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct InfraHealth {
    pub services: Vec<ServiceStatus>,
}

impl InfraHealth {
    pub fn summary_line(&self) -> String {
        let total = self.services.len();
        let healthy = self.services.iter().filter(|s| s.healthy).count();
        if healthy == total {
            format!("Infra: {}/{} healthy", healthy, total)
        } else {
            let unhealthy: Vec<String> = self
                .services
                .iter()
                .filter(|s| !s.healthy)
                .map(|s| format!("{} ({})", s.name, s.service_type))
                .collect();
            format!("Infra: {}/{} — down: {}", healthy, total, unhealthy.join(", "))
        }
    }
}

// ============================================================================
// Flap suppression state
// ============================================================================

#[derive(Debug, Clone)]
struct FlapEntry {
    healthy: bool,
    consecutive_count: u8,
    alerted: bool,
}

pub struct InfraChecker {
    last_state: HashMap<String, FlapEntry>,
}

impl InfraChecker {
    pub fn new() -> Self {
        Self {
            last_state: HashMap::new(),
        }
    }

    /// Run all infrastructure health checks. Returns current health and any new alerts.
    pub async fn check(&mut self) -> (InfraHealth, Vec<String>) {
        let mut services = Vec::new();

        // Docker containers
        let docker_status = check_docker_containers().await;
        services.extend(docker_status);

        // Systemd services
        let systemd_status = check_systemd_services().await;
        services.extend(systemd_status);

        // Tailscale peers
        let tailscale_status = check_tailscale_peers().await;
        services.extend(tailscale_status);

        // Flap suppression + alert generation
        let alerts = self.update_flap_state(&services);

        let health = InfraHealth {
            services,
        };

        (health, alerts)
    }

    fn update_flap_state(&mut self, services: &[ServiceStatus]) -> Vec<String> {
        let mut alerts = Vec::new();

        for svc in services {
            let key = format!("{}:{}", svc.service_type, svc.name);
            let entry = self.last_state.entry(key.clone()).or_insert(FlapEntry {
                healthy: svc.healthy,
                consecutive_count: 0,
                alerted: false,
            });

            if entry.healthy == svc.healthy {
                entry.consecutive_count = entry.consecutive_count.saturating_add(1);
            } else {
                // State changed — reset counter
                entry.healthy = svc.healthy;
                entry.consecutive_count = 1;
                entry.alerted = false;
            }

            // Only alert after FLAP_SUPPRESSION_COUNT consecutive checks in the same state
            if entry.consecutive_count >= FLAP_SUPPRESSION_COUNT && !entry.alerted {
                entry.alerted = true;
                if svc.healthy {
                    alerts.push(format!("✅ {} `{}` recovered", svc.service_type, svc.name));
                } else {
                    alerts.push(format!("🔴 {} `{}` is DOWN", svc.service_type, svc.name));
                }
            }
        }

        alerts
    }
}

// ============================================================================
// Docker health check
// ============================================================================

async fn check_docker_containers() -> Vec<ServiceStatus> {
    let output = Command::new("/usr/bin/docker")
        .args(["ps", "--format", "{{.Names}}\t{{.Status}}"])
        .output()
        .await;

    let running_containers: Vec<String> = match output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .filter_map(|line| {
                    let parts: Vec<&str> = line.split('\t').collect();
                    if parts.len() >= 2 && parts[1].starts_with("Up") {
                        Some(parts[0].to_string())
                    } else {
                        None
                    }
                })
                .collect()
        }
        Ok(out) => {
            debug!("docker ps failed: {}", String::from_utf8_lossy(&out.stderr));
            Vec::new()
        }
        Err(e) => {
            warn!("Failed to run docker ps: {}", e);
            Vec::new()
        }
    };

    DOCKER_CONTAINERS
        .iter()
        .map(|name| ServiceStatus {
            name: name.to_string(),
            healthy: running_containers.iter().any(|c| c.contains(name)),
            service_type: ServiceType::Docker,
        })
        .collect()
}

// ============================================================================
// Systemd health check
// ============================================================================

async fn check_systemd_services() -> Vec<ServiceStatus> {
    let mut results = Vec::new();

    for name in SYSTEMD_SERVICES {
        let output = Command::new("/usr/bin/systemctl")
            .args(["is-active", "--quiet", name])
            .output()
            .await;

        let healthy = match output {
            Ok(out) => out.status.success(),
            Err(e) => {
                debug!("systemctl check failed for {}: {}", name, e);
                false
            }
        };

        results.push(ServiceStatus {
            name: name.to_string(),
            healthy,
            service_type: ServiceType::Systemd,
        });
    }

    results
}

// ============================================================================
// Tailscale peer check
// ============================================================================

async fn check_tailscale_peers() -> Vec<ServiceStatus> {
    // Use `tailscale ping` instead of parsing `status --json`.
    // The `Online` field in the JSON reflects coordination-server presence, not data-plane
    // reachability — it can report false for a fully healthy peer with no recent keepalive.
    // `tailscale ping --c 1` actually traverses the data plane and is the correct check.
    let mut results = Vec::new();

    for name in TAILSCALE_PEERS {
        let output = Command::new("/usr/bin/tailscale")
            .args(["ping", "--c", "1", "--timeout", "5s", name])
            .output()
            .await;

        let healthy = match output {
            Ok(out) => String::from_utf8_lossy(&out.stdout).contains("pong from"),
            Err(e) => {
                debug!("tailscale ping failed for {}: {}", name, e);
                false
            }
        };

        results.push(ServiceStatus {
            name: name.to_string(),
            healthy,
            service_type: ServiceType::Tailscale,
        });
    }

    results
}
