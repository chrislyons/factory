// Token Manager - Automatic Matrix token refresh for IG-88
// Handles token health monitoring, validation, and automatic refresh via Pantalaimon

import { readFileSync, writeFileSync, existsSync } from 'fs';

// ============================================================================
// Types
// ============================================================================

export interface TokenHealth {
  agent: string;
  tokenFile: string;
  lastValidated: number;
  consecutiveFailures: number;
  needsRefresh: boolean;
}

export interface AgentCredentials {
  username: string;
  password: string;
}

export interface TokenManagerConfig {
  pantalaimonUrl: string;
  credentialSource: 'systemd' | 'gpg' | 'env';
  credentialPath?: string;
}

// ============================================================================
// Token Manager
// ============================================================================

export class TokenManager {
  private healthMap: Map<string, TokenHealth>;
  private config: TokenManagerConfig;
  private refreshInProgress: Set<string>;

  constructor(config: TokenManagerConfig) {
    this.healthMap = new Map();
    this.config = config;
    this.refreshInProgress = new Set();
  }

  /**
   * Initialize token health tracking for an agent
   */
  initializeAgent(agentName: string, tokenFile: string): void {
    this.healthMap.set(agentName, {
      agent: agentName,
      tokenFile,
      lastValidated: Date.now(),
      consecutiveFailures: 0,
      needsRefresh: false,
    });
  }

  /**
   * Get token health status for an agent
   */
  getHealth(agentName: string): TokenHealth | undefined {
    return this.healthMap.get(agentName);
  }

  /**
   * Validate token by calling /account/whoami endpoint
   */
  async validateToken(token: string, baseUrl: string): Promise<boolean> {
    try {
      const response = await fetch(`${baseUrl}/_matrix/client/r0/account/whoami`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });

      return response.ok;
    } catch (err) {
      console.error('[TokenManager] Token validation failed', err);
      return false;
    }
  }

  /**
   * Record a 401 authentication failure
   */
  recordFailure(agentName: string): void {
    const health = this.healthMap.get(agentName);
    if (!health) return;

    health.consecutiveFailures++;
    health.needsRefresh = health.consecutiveFailures >= 2; // Trigger refresh after 2 consecutive failures

    this.healthMap.set(agentName, health);
  }

  /**
   * Record a successful authentication
   */
  recordSuccess(agentName: string): void {
    const health = this.healthMap.get(agentName);
    if (!health) return;

    health.lastValidated = Date.now();
    health.consecutiveFailures = 0;
    health.needsRefresh = false;

    this.healthMap.set(agentName, health);
  }

  /**
   * Check if token needs validation (5 minutes since last check)
   */
  needsValidation(agentName: string): boolean {
    const health = this.healthMap.get(agentName);
    if (!health) return false;

    const age = Date.now() - health.lastValidated;
    return age > 5 * 60 * 1000; // 5 minutes
  }

  /**
   * Load agent credentials securely
   */
  private async loadCredentials(agentName: string): Promise<AgentCredentials> {
    switch (this.config.credentialSource) {
      case 'systemd':
        return this.loadSystemdCredentials(agentName);
      case 'gpg':
        throw new Error('GPG credential source not yet implemented');
      case 'env':
        return this.loadEnvCredentials(agentName);
      default:
        throw new Error(`Unknown credential source: ${this.config.credentialSource}`);
    }
  }

  /**
   * Load credentials from systemd LoadCredential
   */
  private async loadSystemdCredentials(agentName: string): Promise<AgentCredentials> {
    const credentialFile = `/run/credentials/matrix-coordinator.service/${agentName}_password`;

    if (!existsSync(credentialFile)) {
      throw new Error(`Systemd credential not found: ${credentialFile}`);
    }

    const password = readFileSync(credentialFile, 'utf-8').trim();

    // Map agent names to Matrix usernames
    const usernameMap: Record<string, string> = {
      boot: 'boot.industries',
      kelk: 'sir.kelk',
      ig88: 'ig88bot',
    };

    const username = usernameMap[agentName];
    if (!username) {
      throw new Error(`Unknown agent name: ${agentName}`);
    }

    return { username, password };
  }

  /**
   * Load credentials from environment variables
   */
  private async loadEnvCredentials(agentName: string): Promise<AgentCredentials> {
    const passwordEnvVar = `${agentName.toUpperCase()}_PASSWORD`;
    const password = process.env[passwordEnvVar];

    if (!password) {
      throw new Error(`Environment variable not set: ${passwordEnvVar}`);
    }

    // Map agent names to Matrix usernames
    const usernameMap: Record<string, string> = {
      boot: 'boot.industries',
      kelk: 'sir.kelk',
      ig88: 'ig88bot',
    };

    const username = usernameMap[agentName];
    if (!username) {
      throw new Error(`Unknown agent name: ${agentName}`);
    }

    return { username, password };
  }

  /**
   * Refresh token via Pantalaimon /login endpoint
   */
  async refreshToken(agentName: string, tokenFile: string): Promise<string> {
    // Prevent concurrent refreshes for the same agent
    if (this.refreshInProgress.has(agentName)) {
      throw new Error(`Token refresh already in progress for ${agentName}`);
    }

    this.refreshInProgress.add(agentName);

    try {
      console.log(`[TokenManager] Refreshing token for ${agentName}...`);

      // Load credentials securely
      const credentials = await this.loadCredentials(agentName);

      // Login via Pantalaimon proxy
      const response = await fetch(`${this.config.pantalaimonUrl}/_matrix/client/r0/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'm.login.password',
          user: credentials.username,
          password: credentials.password,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Login failed (${response.status}): ${errorText}`);
      }

      const data = await response.json() as { access_token: string };
      const newToken = data.access_token;

      if (!newToken) {
        throw new Error('No access token in login response');
      }

      // Write to token file with secure permissions
      writeFileSync(tokenFile, newToken, { mode: 0o600 });

      // Update health tracking
      this.recordSuccess(agentName);

      console.log(`[TokenManager] Token refreshed successfully for ${agentName}`);

      return newToken;
    } catch (err) {
      console.error(`[TokenManager] Token refresh failed for ${agentName}`, err);
      throw err;
    } finally {
      this.refreshInProgress.delete(agentName);
    }
  }

  /**
   * Check if refresh is currently in progress for an agent
   */
  isRefreshInProgress(agentName: string): boolean {
    return this.refreshInProgress.has(agentName);
  }
}
