use anyhow::{Context, Result};
use matrix_sdk::Client;
use std::collections::HashMap;
use tracing::{info, warn};

pub struct IdentityStore {
    clients: HashMap<String, Client>,
    state_dir: String,
}

impl IdentityStore {
    pub fn new(state_dir: &str) -> Self {
        Self {
            clients: HashMap::new(),
            state_dir: state_dir.to_string(),
        }
    }

    pub async fn register(
        &mut self,
        user_id: &str,
        homeserver: &str,
        password: &str,
        recovery_key: Option<&str>,
    ) -> Result<()> {
        let sanitized = user_id.replace([':', '@', '.'], "_");
        let store_path = format!("{}/e2ee-state/{}", self.state_dir, sanitized);
        std::fs::create_dir_all(&store_path)
            .with_context(|| format!("Failed to create E2EE state dir: {}", store_path))?;

        let homeserver_url = url::Url::parse(homeserver)
            .with_context(|| format!("Invalid homeserver URL: {}", homeserver))?;

        let client = Client::builder()
            .homeserver_url(homeserver_url)
            .sqlite_store(&store_path, None)
            .build()
            .await
            .context("Failed to build matrix-sdk Client")?;

        let local_part = user_id
            .strip_prefix('@')
            .and_then(|s| s.split(':').next())
            .unwrap_or(user_id);

        client
            .matrix_auth()
            .login_username(local_part, password)
            .initial_device_display_name("coordinator-rs")
            .await
            .with_context(|| format!("Failed to login as {}", user_id))?;

        info!("E2EE identity registered: {}", user_id);

        if let Some(key) = recovery_key {
            match client.encryption().recovery().recover(key).await {
                Ok(_) => info!("Recovery key applied for {}", user_id),
                Err(e) => warn!("Recovery key failed for {}: {} — continuing without cross-signing", user_id, e),
            }
        }

        // Run initial sync to populate crypto store
        let settings = matrix_sdk::config::SyncSettings::default()
            .timeout(std::time::Duration::from_secs(5));

        if let Err(e) = client.sync_once(settings).await {
            warn!("Initial E2EE sync failed for {}: {} — crypto store may be incomplete", user_id, e);
        }

        self.clients.insert(user_id.to_string(), client);
        Ok(())
    }

    pub fn get(&self, user_id: &str) -> Option<&Client> {
        self.clients.get(user_id)
    }

    pub async fn shutdown_all(&mut self) {
        for (user_id, _client) in self.clients.drain() {
            info!("E2EE identity shut down: {}", user_id);
        }
    }
}
