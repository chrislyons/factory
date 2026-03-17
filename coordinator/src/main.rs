mod approval;
mod agent;
mod budget;
mod config;
mod coordinator;
mod delegate;
mod health;
mod infra;
mod lifecycle;
mod matrix;
mod memory;
mod run_events;
mod runtime_state;
mod task_lease;
mod timer;

use anyhow::Result;
use tracing::info;
use tracing_subscriber::{EnvFilter, fmt};

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing subscriber with RUST_LOG env filter.
    // Default: "coordinator_rs=info,warn" — set RUST_LOG=debug for verbose output.
    fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("coordinator_rs=info,warn")),
        )
        .with_target(false)
        .init();

    info!(
        "coordinator-rs v{} starting",
        env!("CARGO_PKG_VERSION")
    );

    coordinator::run().await
}
