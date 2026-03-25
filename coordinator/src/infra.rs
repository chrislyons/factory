/// Infrastructure health checks — Docker containers, platform services, Tailscale peers.
/// Phase 3F: Runs every 5 minutes, feeds data into Status HUD, alerts on state changes.
/// Platform-aware: uses launchd on macOS, systemd on Linux. Targets are config-driven
/// with hardcoded fallbacks for backward compatibility.
use crate::config::Settings;
use std::collections::HashMap;
use tokio::process::Command;
use tracing::{debug, warn};

// ============================================================================
// Fallback targets (used when config fields are None)
// ============================================================================

const DEFAULT_DOCKER_CONTAINERS: &[&str] = &["qdrant", "graphiti-mcp", "falkordb"];
const DEFAULT_SYSTEMD_SERVICES: &[&str] = &["ollama", "qdrant-mcp"];
const DEFAULT_TAILSCALE_PEERS: &[&str] = &["cloudkicker", "greybox"];

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
    Launchd,
    Tailscale,
}

impl std::fmt::Display for ServiceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Docker => write!(f, "docker"),
            Self::Systemd => write!(f, "systemd"),
            Self::Launchd => write!(f, "launchd"),
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
    docker_containers: Vec<String>,
    systemd_services: Vec<String>,
    launchd_services: Vec<String>,
    tailscale_peers: Vec<String>,
}

impl InfraChecker {
    pub fn new(settings: &Settings) -> Self {
        let docker_containers = settings.infra_docker_containers.clone()
            .unwrap_or_else(|| DEFAULT_DOCKER_CONTAINERS.iter().map(|s| s.to_string()).collect());
        let systemd_services = settings.infra_systemd_services.clone()
            .unwrap_or_else(|| DEFAULT_SYSTEMD_SERVICES.iter().map(|s| s.to_string()).collect());
        let launchd_services = settings.infra_launchd_services.clone()
            .unwrap_or_else(Vec::new);
        let tailscale_peers = settings.infra_tailscale_peers.clone()
            .unwrap_or_else(|| DEFAULT_TAILSCALE_PEERS.iter().map(|s| s.to_string()).collect());

        Self {
            last_state: HashMap::new(),
            docker_containers,
            systemd_services,
            launchd_services,
            tailscale_peers,
        }
    }

    /// Run all infrastructure health checks. Returns current health and any new alerts.
    pub async fn check(&mut self) -> (InfraHealth, Vec<String>) {
        let mut services = Vec::new();

        // Docker containers
        let docker_status = check_docker_containers(&self.docker_containers).await;
        services.extend(docker_status);

        // Platform services (launchd on macOS, systemd on Linux)
        let platform_status = check_platform_services(
            &self.systemd_services,
            &self.launchd_services,
        ).await;
        services.extend(platform_status);

        // Tailscale peers
        let tailscale_status = check_tailscale_peers(&self.tailscale_peers).await;
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
// Binary resolution
// ============================================================================

fn find_docker() -> &'static str {
    if std::path::Path::new("/opt/homebrew/bin/docker").exists() {
        "/opt/homebrew/bin/docker"
    } else if std::path::Path::new("/usr/local/bin/docker").exists() {
        "/usr/local/bin/docker"
    } else if std::path::Path::new("/usr/bin/docker").exists() {
        "/usr/bin/docker"
    } else {
        "docker"
    }
}

fn find_tailscale() -> &'static str {
    if std::path::Path::new("/opt/homebrew/bin/tailscale").exists() {
        "/opt/homebrew/bin/tailscale"
    } else if std::path::Path::new("/usr/local/bin/tailscale").exists() {
        "/usr/local/bin/tailscale"
    } else if std::path::Path::new("/usr/bin/tailscale").exists() {
        "/usr/bin/tailscale"
    } else {
        "tailscale"
    }
}

// ============================================================================
// Docker health check
// ============================================================================

async fn check_docker_containers(targets: &[String]) -> Vec<ServiceStatus> {
    if targets.is_empty() {
        return Vec::new();
    }

    let output = Command::new(find_docker())
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

    targets
        .iter()
        .map(|name| ServiceStatus {
            name: name.to_string(),
            healthy: running_containers.iter().any(|c| c.contains(name.as_str())),
            service_type: ServiceType::Docker,
        })
        .collect()
}

// ============================================================================
// Platform-aware service checks
// ============================================================================

async fn check_platform_services(
    systemd_targets: &[String],
    launchd_targets: &[String],
) -> Vec<ServiceStatus> {
    let mut results = Vec::new();

    // macOS: check launchd services
    if !launchd_targets.is_empty() {
        results.extend(check_launchd_services(launchd_targets).await);
    }

    // Linux: check systemd services (skip on macOS — systemctl doesn't exist)
    if !systemd_targets.is_empty() && std::path::Path::new("/usr/bin/systemctl").exists() {
        results.extend(check_systemd_services(systemd_targets).await);
    }

    results
}

async fn check_systemd_services(targets: &[String]) -> Vec<ServiceStatus> {
    let mut results = Vec::new();

    for name in targets {
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

async fn check_launchd_services(targets: &[String]) -> Vec<ServiceStatus> {
    let mut results = Vec::new();

    for name in targets {
        let output = Command::new("/bin/launchctl")
            .args(["list", name])
            .output()
            .await;

        let healthy = match output {
            Ok(out) => out.status.success(),
            Err(e) => {
                debug!("launchctl check failed for {}: {}", name, e);
                false
            }
        };

        results.push(ServiceStatus {
            name: name.to_string(),
            healthy,
            service_type: ServiceType::Launchd,
        });
    }

    results
}

// ============================================================================
// Tailscale peer check
// ============================================================================

async fn check_tailscale_peers(targets: &[String]) -> Vec<ServiceStatus> {
    if targets.is_empty() {
        return Vec::new();
    }

    let mut results = Vec::new();

    for name in targets {
        let output = Command::new(find_tailscale())
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
