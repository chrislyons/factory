// Blackbox Heartbeat Service
// Monitors all infrastructure services and reports status to Matrix
// Alerts on state changes (service down/up)

import { execSync } from 'child_process';
import { readFileSync, existsSync, writeFileSync } from 'fs';

// ============================================================================
// Configuration
// ============================================================================

const HEARTBEAT_INTERVAL_MS = 60000; // Check every 60 seconds
const MATRIX_ROOM_ID = process.env.MATRIX_ROOM_ID || '!MDVmYJtAiHZoBfaQdK:matrix.org'; // System Status
const MATRIX_TOKEN_FILE = process.env.MATRIX_TOKEN_FILE || `${process.env.HOME}/.config/ig88/matrix_token_boot`;
const MATRIX_HOMESERVER = process.env.MATRIX_HOMESERVER || 'https://matrix.org';
const STATE_FILE = '/tmp/blackbox-heartbeat-state.json';

// Services to monitor (name = check target, display = shown in reports)
const SERVICES = [
  { name: 'docker', display: 'docker', type: 'systemd', critical: true },
  { name: 'tailscaled', display: 'tailscale', type: 'systemd', critical: true },
  { name: 'ollama', display: 'ollama', type: 'systemd', critical: false },
  { name: 'qdrant', display: 'qdrant', type: 'docker', critical: false },
  { name: 'graphiti-mcp', display: 'graphiti', type: 'docker', critical: false },
];

// External APIs to monitor
const EXTERNAL_APIS = [
  { name: 'anthropic', url: 'https://api.anthropic.com/v1/messages', critical: true },
  { name: 'matrix', url: 'https://matrix.org/_matrix/client/versions', critical: false },
];

// Health check endpoints (HTTP)
const HEALTH_ENDPOINTS: Record<string, string> = {
  qdrant: 'http://localhost:41450/',
  ollama: 'http://localhost:11434/api/tags',
  'graphiti-mcp': 'http://localhost:41440/health',
};

interface ServiceState {
  name: string;
  healthy: boolean;
  lastChange: number;
  consecutiveFailures: number;
}

interface HeartbeatState {
  services: Record<string, ServiceState>;
  lastHeartbeat: number;
  startedAt: number;
}

// ============================================================================
// Logging
// ============================================================================

function log(message: string): void {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

function logError(message: string, err?: unknown): void {
  console.error(`[${new Date().toISOString()}] ERROR: ${message}`, err || '');
}

// ============================================================================
// Service Checks
// ============================================================================

function checkSystemdService(name: string): boolean {
  try {
    const result = execSync(`systemctl is-active ${name}.service`, {
      encoding: 'utf-8',
      timeout: 5000,
    }).trim();
    return result === 'active';
  } catch {
    return false;
  }
}

function checkDockerContainer(name: string): boolean {
  try {
    const result = execSync(`docker inspect -f '{{.State.Running}}' ${name}`, {
      encoding: 'utf-8',
      timeout: 5000,
    }).trim();
    return result === 'true';
  } catch {
    return false;
  }
}

async function checkHttpEndpoint(url: string): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeout);

    return response.ok;
  } catch {
    return false;
  }
}

async function checkService(service: { name: string; type: string }): Promise<boolean> {
  let baseHealthy = false;

  if (service.type === 'systemd') {
    baseHealthy = checkSystemdService(service.name);
  } else if (service.type === 'docker') {
    baseHealthy = checkDockerContainer(service.name);
  }

  if (!baseHealthy) {
    return false;
  }

  // If there's an HTTP endpoint, check that too
  const endpoint = HEALTH_ENDPOINTS[service.name];
  if (endpoint) {
    return checkHttpEndpoint(endpoint);
  }

  return true;
}

// ============================================================================
// External API Checks
// ============================================================================

async function checkAnthropicApi(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    // Send a minimal request - we expect 401 (no key) or 400 (bad request)
    // Either response means the API is up
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({}),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    // 401 = API up, no key; 400 = API up, bad request; 529 = overloaded
    return response.status === 401 || response.status === 400 || response.status === 200;
  } catch {
    return false;
  }
}

async function checkExternalApi(api: { name: string; url: string }): Promise<boolean> {
  if (api.name === 'anthropic') {
    return checkAnthropicApi();
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    const response = await fetch(api.url, { signal: controller.signal });
    clearTimeout(timeout);

    return response.ok;
  } catch {
    return false;
  }
}

// ============================================================================
// Tailscale Check
// ============================================================================

function checkTailscaleConnected(): boolean {
  try {
    const result = execSync('tailscale status --json', {
      encoding: 'utf-8',
      timeout: 5000,
    });
    const status = JSON.parse(result);
    return status.BackendState === 'Running' && status.Self?.Online === true;
  } catch {
    return false;
  }
}

// ============================================================================
// State Management
// ============================================================================

function loadState(): HeartbeatState {
  try {
    if (existsSync(STATE_FILE)) {
      const content = readFileSync(STATE_FILE, 'utf-8');
      return JSON.parse(content);
    }
  } catch {
    // Ignore errors, start fresh
  }

  return {
    services: {},
    lastHeartbeat: 0,
    startedAt: Date.now(),
  };
}

function saveState(state: HeartbeatState): void {
  try {
    writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (err) {
    logError('Failed to save state', err);
  }
}

// ============================================================================
// Matrix Notifications
// ============================================================================

function getToken(): string {
  if (!existsSync(MATRIX_TOKEN_FILE)) {
    throw new Error(`Token file not found: ${MATRIX_TOKEN_FILE}`);
  }
  return readFileSync(MATRIX_TOKEN_FILE, 'utf-8').trim();
}

async function sendMatrixMessage(body: string): Promise<boolean> {
  try {
    const token = getToken();
    const txnId = `hb_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const url = `${MATRIX_HOMESERVER}/_matrix/client/r0/rooms/${encodeURIComponent(MATRIX_ROOM_ID)}/send/m.room.message/${txnId}`;

    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        msgtype: 'm.text',
        body,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      logError(`Matrix send failed ${response.status}: ${text}`);
    }

    return response.ok;
  } catch (err) {
    logError('Failed to send Matrix message', err);
    return false;
  }
}

// ============================================================================
// Alert Formatting
// ============================================================================

function formatUptime(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${seconds}s`;
}

function formatServiceAlert(
  service: string,
  healthy: boolean,
  downtime?: number
): string {
  if (healthy) {
    // Recovery - show how long it was down
    const downtimeStr = downtime ? ` (was down ${formatUptime(downtime)})` : '';
    return `🟢 **${service}** recovered${downtimeStr}`;
  } else {
    // Down
    return `🔴 **${service}** is down`;
  }
}

function formatStatusReport(state: HeartbeatState): string {
  const healthy = Object.values(state.services).filter(s => s.healthy).length;
  const total = Object.keys(state.services).length;

  const lines: string[] = [`#status 📊 **Blackbox** ${healthy}/${total}`];

  // Services
  for (const service of SERVICES) {
    const svc = state.services[service.name];
    if (!svc) continue;
    lines.push(`${svc.healthy ? '✅' : '❌'} ${service.display}`);
  }

  // External APIs
  for (const api of EXTERNAL_APIS) {
    const svc = state.services[`api:${api.name}`];
    if (!svc) continue;
    lines.push(`${svc.healthy ? '✅' : '❌'} ${api.name}`);
  }

  lines.push('🫀 heartbeat active');

  return lines.join('\n');
}

// ============================================================================
// Main Loop
// ============================================================================

async function runHealthCheck(state: HeartbeatState): Promise<string[]> {
  const alerts: string[] = [];

  // Check local services
  for (const service of SERVICES) {
    const healthy = await checkService(service);
    const prev = state.services[service.name];

    // Initialize if new
    if (!prev) {
      state.services[service.name] = {
        name: service.display,
        healthy,
        lastChange: Date.now(),
        consecutiveFailures: healthy ? 0 : 1,
      };

      if (!healthy) {
        alerts.push(formatServiceAlert(service.display, false));
      }
      continue;
    }

    // Check for state change
    if (healthy !== prev.healthy) {
      const downtime = healthy ? Date.now() - prev.lastChange : undefined;
      alerts.push(formatServiceAlert(service.display, healthy, downtime));

      state.services[service.name] = {
        ...prev,
        healthy,
        lastChange: Date.now(),
        consecutiveFailures: healthy ? 0 : 1,
      };
    } else if (!healthy) {
      // Increment failure counter
      state.services[service.name].consecutiveFailures++;

      // Re-alert every 5 minutes if still down
      if (prev.consecutiveFailures > 0 && prev.consecutiveFailures % 5 === 0) {
        const downtime = Date.now() - prev.lastChange;
        alerts.push(formatServiceAlert(service.display, false, downtime));
      }
    }
  }

  // Check external APIs
  for (const api of EXTERNAL_APIS) {
    const healthy = await checkExternalApi(api);
    const key = `api:${api.name}`;
    const prev = state.services[key];

    if (!prev) {
      state.services[key] = {
        name: api.name,
        healthy,
        lastChange: Date.now(),
        consecutiveFailures: healthy ? 0 : 1,
      };

      if (!healthy) {
        alerts.push(formatServiceAlert(`${api.name} API`, false));
      }
      continue;
    }

    if (healthy !== prev.healthy) {
      const downtime = healthy ? Date.now() - prev.lastChange : undefined;
      alerts.push(formatServiceAlert(`${api.name} API`, healthy, downtime));

      state.services[key] = {
        ...prev,
        healthy,
        lastChange: Date.now(),
        consecutiveFailures: healthy ? 0 : 1,
      };
    } else if (!healthy) {
      state.services[key].consecutiveFailures++;

      // Re-alert every 5 minutes for external APIs too
      if (prev.consecutiveFailures > 0 && prev.consecutiveFailures % 5 === 0) {
        const downtime = Date.now() - prev.lastChange;
        alerts.push(formatServiceAlert(`${api.name} API`, false, downtime));
      }
    }
  }

  return alerts;
}

async function main(): Promise<void> {
  console.log('');
  console.log('='.repeat(50));
  console.log('  Blackbox Heartbeat Service');
  console.log('='.repeat(50));
  console.log('');

  log(`Monitoring ${SERVICES.length} services`);
  log(`Interval: ${HEARTBEAT_INTERVAL_MS / 1000}s`);
  log(`Matrix room: ${MATRIX_ROOM_ID}`);
  console.log('');

  let state = loadState();
  state.startedAt = Date.now();

  // Initial check - only alert if something is already down
  log('Running initial health check...');
  const initialAlerts = await runHealthCheck(state);
  log(`Initial check complete: ${initialAlerts.length} alerts`);

  // Send initial status report
  const initialReport = formatStatusReport(state);
  await sendMatrixMessage(initialReport);

  // Send any alerts from initial check
  if (initialAlerts.length > 0) {
    await sendMatrixMessage(initialAlerts.join('\n'));
  }
  saveState(state);

  // Track last hour we sent a report
  let lastReportHour = new Date().getHours();

  // Main loop
  while (true) {
    await new Promise(resolve => setTimeout(resolve, HEARTBEAT_INTERVAL_MS));

    const alerts = await runHealthCheck(state);

    // Send alerts if any
    if (alerts.length > 0) {
      log(`Sending ${alerts.length} alerts`);
      await sendMatrixMessage(alerts.join('\n'));
    }

    // Send hourly status report at top of each hour
    const currentHour = new Date().getHours();
    if (currentHour !== lastReportHour) {
      const report = formatStatusReport(state);
      await sendMatrixMessage(report);
      lastReportHour = currentHour;
      log('Sent hourly status report');
    }

    state.lastHeartbeat = Date.now();
    saveState(state);

    const totalMonitored = SERVICES.length + EXTERNAL_APIS.length;
    log(`Check complete: ${Object.values(state.services).filter(s => s.healthy).length}/${totalMonitored} healthy`);
  }
}

// Handle shutdown
process.on('SIGTERM', () => {
  log('Received SIGTERM, shutting down...');
  process.exit(0);
});

process.on('SIGINT', () => {
  log('Received SIGINT, shutting down...');
  process.exit(0);
});

// Entry point
main().catch((err) => {
  logError('Fatal error', err);
  process.exit(1);
});
