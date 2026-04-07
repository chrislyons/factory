// Matrix Coordinator - Multi-Agent Router for IG-88
// Routes messages to appropriate workers based on room/agent configuration
// Supports local (RP5), remote (cloudkicker/mac), and cloud (OpenRouter) workers
// Features: Hybrid tmux mode, agent-to-agent delegation, worker overrides

import { spawn, exec } from 'child_process';
import { readFileSync, existsSync, watchFile } from 'fs';
import { promisify } from 'util';
import * as yaml from 'yaml';

const execAsync = promisify(exec);

// ============================================================================
// Types
// ============================================================================

interface Settings {
  dm_policy: 'pairing' | 'allowlist' | 'disabled';
  group_policy: 'mention' | 'allowlist';
  fallback_device: string;
  graphiti_url: string;
  graphiti_token_env: string;
  claude_timeout_ms: number;
  ssh_timeout_ms: number;
  hybrid_mode?: boolean;
  attach_hint_template?: string;
}

interface Device {
  type: 'local' | 'remote' | 'cloud';
  tailscale_ip?: string;
  ssh_alias?: string;
  tmux_socket?: string;
  api_base?: string;
  models?: string[];
}

interface Agent {
  matrix_user: string;
  token_file: string;
  description: string;
  sandbox_profile: 'personal' | 'work' | 'restricted';
  default_device: string;
  can_delegate_to?: string[];
}

interface Room {
  name: string;
  prefix: string | null;
  default_agent: string | null;
  graphiti_group: string;
  sandbox_profile: 'personal' | 'work' | 'restricted';
  worker_cwd?: string;
  tmux_session?: string;
  target_device?: string;
  require_mention?: boolean;
}

interface Config {
  settings: Settings;
  allowlist: string[];
  devices: Record<string, Device>;
  agents: Record<string, Agent>;
  rooms: Record<string, Room>;
}

interface SyncResponse {
  next_batch: string;
  rooms?: {
    join?: Record<string, {
      timeline?: {
        events?: MatrixEvent[];
      };
    }>;
  };
}

interface MatrixEvent {
  type: string;
  sender: string;
  content: {
    msgtype?: string;
    body?: string;
  };
  event_id: string;
  room_id?: string;
}

interface WorkerResult {
  success: boolean;
  response: string;
  device: string;
  tmuxSession?: string;
}

interface ParsedMessage {
  originalBody: string;
  cleanBody: string;
  deviceOverride?: string;
  delegateToAgent?: string;
}

// ============================================================================
// Configuration
// ============================================================================

const CONFIG_PATH = process.env.CONFIG_PATH || `${process.env.HOME}/projects/ig88/config/agent-config.yaml`;
const MAX_RESPONSE_LENGTH = 4000;
const POLL_INTERVAL_MS = 3000;

let config: Config;
let syncTokens: Map<string, string> = new Map();
let agentUserIds: Map<string, string> = new Map();
let deviceHealth: Map<string, boolean> = new Map();

// ============================================================================
// Logging
// ============================================================================

function log(message: string): void {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

function logError(message: string, err?: unknown): void {
  console.error(`[${new Date().toISOString()}] ERROR: ${message}`, err || '');
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ============================================================================
// Configuration Loading
// ============================================================================

function loadConfig(): Config {
  if (!existsSync(CONFIG_PATH)) {
    throw new Error(`Config file not found: ${CONFIG_PATH}`);
  }

  const content = readFileSync(CONFIG_PATH, 'utf-8');
  const parsed = yaml.parse(content) as Config;

  // Expand environment variables in token_file paths
  for (const agent of Object.values(parsed.agents)) {
    agent.token_file = agent.token_file.replace('${HOME}', process.env.HOME || '');
  }

  // Expand ~ in worker_cwd paths
  for (const room of Object.values(parsed.rooms)) {
    if (room.worker_cwd) {
      room.worker_cwd = room.worker_cwd.replace('~', process.env.HOME || '');
    }
  }

  log(`Loaded config: ${Object.keys(parsed.agents).length} agents, ${Object.keys(parsed.rooms).length} rooms`);
  return parsed;
}

function reloadConfig(): void {
  try {
    config = loadConfig();
    log('Configuration reloaded');
  } catch (err) {
    logError('Failed to reload config', err);
  }
}

// ============================================================================
// Matrix API
// ============================================================================

function getToken(tokenFile: string): string {
  if (!existsSync(tokenFile)) {
    throw new Error(`Token file not found: ${tokenFile}`);
  }
  return readFileSync(tokenFile, 'utf-8').trim();
}

async function getMatrixUserId(token: string): Promise<string> {
  const response = await fetch('https://matrix.org/_matrix/client/r0/account/whoami', {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Failed to get user ID: ${response.status}`);
  }

  const data = await response.json() as { user_id: string };
  return data.user_id;
}

async function matrixSync(token: string, sinceToken?: string): Promise<SyncResponse> {
  const params = new URLSearchParams({ timeout: '30000' });
  if (sinceToken) {
    params.set('since', sinceToken);
  }

  const response = await fetch(`https://matrix.org/_matrix/client/r0/sync?${params}`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Sync failed: ${response.status}`);
  }

  return response.json() as Promise<SyncResponse>;
}

async function sendMessage(token: string, roomId: string, body: string): Promise<boolean> {
  const txnId = `coord_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const url = `https://matrix.org/_matrix/client/r0/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}`;

  try {
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

    return response.ok;
  } catch (err) {
    logError('Failed to send message', err);
    return false;
  }
}

async function sendTyping(token: string, roomId: string, userId: string, typing: boolean): Promise<void> {
  const url = `https://matrix.org/_matrix/client/r0/rooms/${encodeURIComponent(roomId)}/typing/${encodeURIComponent(userId)}`;

  try {
    await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ typing, timeout: typing ? 30000 : undefined }),
    });
  } catch {
    // Ignore typing indicator failures
  }
}

// ============================================================================
// Message Parsing
// ============================================================================

function parseMessage(body: string, agentName: string): ParsedMessage {
  let cleanBody = body;
  let deviceOverride: string | undefined;
  let delegateToAgent: string | undefined;

  // Parse worker override: "@agent use device: message"
  // Examples: "@boot use mac: check the tests" or "use cloudkicker: run build"
  const deviceOverrideMatch = body.match(/^(?:@\w+\s+)?use\s+(\w+):\s*(.+)$/is);
  if (deviceOverrideMatch) {
    deviceOverride = deviceOverrideMatch[1].toLowerCase();
    cleanBody = deviceOverrideMatch[2].trim();
    log(`Device override detected: ${deviceOverride}`);
  }

  // Parse delegation: "@kelk ask boot: message" or "ask boot about: message"
  const delegateMatch = body.match(/^(?:@\w+\s+)?ask\s+(\w+)(?:\s+about)?:\s*(.+)$/is);
  if (delegateMatch) {
    delegateToAgent = delegateMatch[1].toLowerCase();
    cleanBody = delegateMatch[2].trim();
    log(`Delegation detected: -> ${delegateToAgent}`);
  }

  return {
    originalBody: body,
    cleanBody,
    deviceOverride,
    delegateToAgent,
  };
}

// ============================================================================
// Attach Hint Generation
// ============================================================================

function generateAttachHint(deviceName: string, tmuxSession?: string): string {
  if (!config.settings.hybrid_mode || !tmuxSession) {
    return '';
  }

  const template = config.settings.attach_hint_template || '📺 mosh {device} && tmux attach -t {session}';
  const device = config.devices[deviceName];
  const sshAlias = device?.ssh_alias || deviceName;

  return '\n\n' + template
    .replace('{device}', sshAlias)
    .replace('{session}', tmuxSession);
}

// ============================================================================
// Authorization
// ============================================================================

function isAuthorized(sender: string, roomId: string): boolean {
  if (!config.allowlist.includes(sender)) {
    log(`Unauthorized sender: ${sender}`);
    return false;
  }
  return true;
}

function requiresMention(roomId: string, body: string, agentUserId: string): boolean {
  const room = config.rooms[roomId];

  if (room?.require_mention || config.settings.group_policy === 'mention') {
    const mentionPattern = new RegExp(`@${agentUserId.split(':')[0].slice(1)}`, 'i');
    return !mentionPattern.test(body);
  }

  return false;
}

// ============================================================================
// Device Health Checking
// ============================================================================

async function checkDeviceHealth(deviceName: string): Promise<boolean> {
  const device = config.devices[deviceName];
  if (!device) return false;

  if (device.type === 'local') {
    return true;
  }

  if (device.type === 'cloud') {
    return true;
  }

  if (device.type === 'remote' && device.ssh_alias) {
    try {
      const { stdout } = await execAsync(
        `ssh -o ConnectTimeout=5 -o BatchMode=yes ${device.ssh_alias} "echo ok"`,
        { timeout: config.settings.ssh_timeout_ms }
      );
      return stdout.trim() === 'ok';
    } catch {
      return false;
    }
  }

  return false;
}

async function updateDeviceHealth(): Promise<void> {
  for (const [name, device] of Object.entries(config.devices)) {
    const healthy = await checkDeviceHealth(name);
    const wasHealthy = deviceHealth.get(name);

    if (wasHealthy !== healthy) {
      log(`Device ${name}: ${healthy ? '🟢 online' : '🔴 offline'}`);
    }

    deviceHealth.set(name, healthy);
  }
}

// ============================================================================
// Worker Invocation
// ============================================================================

async function invokeLocalWorker(
  message: string,
  cwd: string,
  sandboxProfile: string
): Promise<WorkerResult> {
  return new Promise((resolve) => {
    const args = ['-p', message, '--output-format', 'text'];

    if (sandboxProfile === 'work') {
      args.push('--sandbox');
    } else if (sandboxProfile === 'restricted') {
      args.push('--sandbox', '--no-write');
    }

    const proc = spawn('claude', args, {
      cwd,
      timeout: config.settings.claude_timeout_ms,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data: Buffer) => {
      stdout += data.toString();
    });

    proc.stderr.on('data', (data: Buffer) => {
      stderr += data.toString();
    });

    proc.on('close', (code) => {
      if (code === 0) {
        resolve({ success: true, response: stdout.trim(), device: 'rp5' });
      } else {
        resolve({ success: false, response: stderr || `Exit code ${code}`, device: 'rp5' });
      }
    });

    proc.on('error', (err) => {
      resolve({ success: false, response: err.message, device: 'rp5' });
    });
  });
}

async function invokeRemoteWorker(
  message: string,
  deviceName: string,
  device: Device,
  cwd: string,
  tmuxSession?: string
): Promise<WorkerResult> {
  const sshAlias = device.ssh_alias;
  if (!sshAlias) {
    return { success: false, response: 'No SSH alias configured', device: deviceName };
  }

  try {
    const escapedMessage = message.replace(/'/g, "'\\''");

    let command: string;
    let resultTmuxSession: string | undefined;

    if (tmuxSession) {
      // Send to existing tmux session and capture output
      // First, send the command
      const sendCmd = `ssh ${sshAlias} "tmux send-keys -t ${tmuxSession} 'claude -p '\\''${escapedMessage}'\\'' --output-format text 2>&1 | tee /tmp/claude-output-${tmuxSession}.txt' Enter"`;
      await execAsync(sendCmd, { timeout: 5000 });

      // Wait for command to complete (poll for output file)
      await sleep(2000);

      // Get the output
      const getOutput = `ssh ${sshAlias} "cat /tmp/claude-output-${tmuxSession}.txt 2>/dev/null || echo 'Command sent to tmux session ${tmuxSession}'"`;
      const { stdout } = await execAsync(getOutput, { timeout: config.settings.claude_timeout_ms });

      resultTmuxSession = tmuxSession;
      return {
        success: true,
        response: stdout.trim(),
        device: deviceName,
        tmuxSession: resultTmuxSession,
      };
    } else {
      // Direct execution
      command = `ssh ${sshAlias} "cd ${cwd} && claude -p '${escapedMessage}' --output-format text"`;
      const { stdout, stderr } = await execAsync(command, {
        timeout: config.settings.claude_timeout_ms,
      });

      if (stderr && !stdout) {
        return { success: false, response: stderr, device: deviceName };
      }

      return { success: true, response: stdout.trim(), device: deviceName };
    }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    return { success: false, response: errorMsg, device: deviceName };
  }
}

async function invokeCloudWorker(
  message: string,
  device: Device
): Promise<WorkerResult> {
  if (!device.api_base || !device.models?.length) {
    return { success: false, response: 'Cloud worker not configured', device: 'cloud' };
  }

  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    return { success: false, response: 'OPENROUTER_API_KEY not set', device: 'cloud' };
  }

  try {
    const response = await fetch(`${device.api_base}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: device.models[0],
        messages: [{ role: 'user', content: message }],
        max_tokens: 2000,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      return { success: false, response: `API error: ${error}`, device: 'cloud' };
    }

    const data = await response.json() as { choices: Array<{ message: { content: string } }> };
    return {
      success: true,
      response: data.choices[0]?.message?.content || 'No response',
      device: 'cloud',
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    return { success: false, response: errorMsg, device: 'cloud' };
  }
}

async function routeToWorker(
  message: string,
  room: Room,
  agent: Agent,
  deviceOverride?: string
): Promise<WorkerResult> {
  // Determine target device: override > room.target_device > agent.default_device
  const targetDevice = deviceOverride || room.target_device || agent.default_device;
  const fallbackDevice = config.settings.fallback_device;
  const cwd = room.worker_cwd || process.env.HOME || '/';
  const sandbox = room.sandbox_profile || agent.sandbox_profile;

  // Try target device
  if (deviceHealth.get(targetDevice)) {
    const device = config.devices[targetDevice];

    if (device.type === 'local') {
      return invokeLocalWorker(message, cwd, sandbox);
    } else if (device.type === 'remote') {
      return invokeRemoteWorker(message, targetDevice, device, cwd, room.tmux_session);
    } else if (device.type === 'cloud') {
      return invokeCloudWorker(message, device);
    }
  }

  log(`Target device ${targetDevice} unavailable, trying fallback ${fallbackDevice}`);

  // Try fallback device
  if (deviceHealth.get(fallbackDevice)) {
    const device = config.devices[fallbackDevice];

    if (device.type === 'local') {
      return invokeLocalWorker(message, cwd, sandbox);
    }
  }

  return {
    success: false,
    response: `No available workers (target: ${targetDevice}, fallback: ${fallbackDevice})`,
    device: 'none',
  };
}

// ============================================================================
// Agent-to-Agent Delegation
// ============================================================================

async function delegateToAgent(
  delegateAgentName: string,
  message: string,
  sourceAgent: Agent,
  sourceRoom: Room,
  sourceToken: string,
  sourceRoomId: string
): Promise<WorkerResult | null> {
  // Check if delegation is allowed
  if (!sourceAgent.can_delegate_to?.includes(delegateAgentName)) {
    log(`Delegation from ${sourceAgent.matrix_user} to ${delegateAgentName} not allowed`);
    return null;
  }

  const targetAgent = config.agents[delegateAgentName];
  if (!targetAgent) {
    log(`Delegation target agent ${delegateAgentName} not found`);
    return null;
  }

  log(`Delegating to ${delegateAgentName}: ${message.slice(0, 50)}...`);

  // Find a room that belongs to the target agent
  const targetRoom = Object.values(config.rooms).find(r => r.default_agent === delegateAgentName);

  if (!targetRoom) {
    // Use source room config but target agent's device
    return routeToWorker(message, sourceRoom, targetAgent);
  }

  return routeToWorker(message, targetRoom, targetAgent);
}

// ============================================================================
// Message Handling
// ============================================================================

function truncateResponse(response: string): string {
  if (response.length <= MAX_RESPONSE_LENGTH) {
    return response;
  }
  return response.slice(0, MAX_RESPONSE_LENGTH - 50) + '\n\n[...truncated]';
}

async function handleMessage(
  event: MatrixEvent,
  roomId: string,
  agentName: string,
  token: string
): Promise<void> {
  const body = event.content.body;
  if (!body) return;

  const agent = config.agents[agentName];
  const room = config.rooms[roomId];
  const userId = agentUserIds.get(agentName);

  if (!agent || !room || !userId) {
    logError(`Missing config for agent ${agentName} or room ${roomId}`);
    return;
  }

  if (!isAuthorized(event.sender, roomId)) {
    return;
  }

  if (requiresMention(roomId, body, userId)) {
    return;
  }

  log(`[${room.name}] ${event.sender}: ${body.slice(0, 60)}${body.length > 60 ? '...' : ''}`);

  // Parse message for overrides and delegation
  const parsed = parseMessage(body, agentName);

  try {
    await sendTyping(token, roomId, userId, true);

    let result: WorkerResult;

    // Check for agent delegation
    if (parsed.delegateToAgent) {
      const delegateResult = await delegateToAgent(
        parsed.delegateToAgent,
        parsed.cleanBody,
        agent,
        room,
        token,
        roomId
      );

      if (delegateResult) {
        result = delegateResult;
      } else {
        result = {
          success: false,
          response: `Cannot delegate to ${parsed.delegateToAgent}`,
          device: 'none',
        };
      }
    } else {
      // Route to worker with optional device override
      result = await routeToWorker(parsed.cleanBody, room, agent, parsed.deviceOverride);
    }

    let response: string;
    if (result.success) {
      response = truncateResponse(result.response);

      // Add attach hint for hybrid mode
      if (result.tmuxSession || room.tmux_session) {
        const targetDevice = parsed.deviceOverride || room.target_device || agent.default_device;
        const attachHint = generateAttachHint(targetDevice, result.tmuxSession || room.tmux_session);
        response += attachHint;
      }
    } else {
      response = `Error (${result.device}): ${result.response.slice(0, 200)}`;
    }

    await sendMessage(token, roomId, response);
    log(`[${room.name}] Responded via ${result.device}: ${response.slice(0, 60)}${response.length > 60 ? '...' : ''}`);

  } catch (err) {
    logError('Message handling failed', err);
    const errorMsg = err instanceof Error ? err.message : String(err);
    await sendMessage(token, roomId, `Error: ${errorMsg.slice(0, 200)}`);
  } finally {
    await sendTyping(token, roomId, userId, false);
  }
}

// ============================================================================
// Agent Polling
// ============================================================================

async function pollAgent(agentName: string): Promise<void> {
  const agent = config.agents[agentName];
  if (!agent) return;

  let token: string;
  try {
    token = getToken(agent.token_file);
  } catch (err) {
    // Token file not found - agent not yet configured
    return;
  }

  const syncToken = syncTokens.get(agentName);

  try {
    const sync = await matrixSync(token, syncToken);
    syncTokens.set(agentName, sync.next_batch);

    if (sync.rooms?.join) {
      for (const [roomId, roomData] of Object.entries(sync.rooms.join)) {
        if (!config.rooms[roomId]) continue;

        const room = config.rooms[roomId];

        if (room.default_agent !== agentName && room.default_agent !== null) {
          continue;
        }

        const events = roomData.timeline?.events || [];
        const userId = agentUserIds.get(agentName);

        for (const event of events) {
          if (
            event.type === 'm.room.message' &&
            event.content.msgtype === 'm.text' &&
            event.sender !== userId
          ) {
            await handleMessage(event, roomId, agentName, token);
          }
        }
      }
    }
  } catch (err) {
    // Only log if it's not a token issue (expected during setup)
    if (!(err instanceof Error && err.message.includes('Token file not found'))) {
      logError(`Sync failed for ${agentName}`, err);
    }
  }
}

// ============================================================================
// Main
// ============================================================================

async function initializeAgents(): Promise<void> {
  for (const [name, agent] of Object.entries(config.agents)) {
    try {
      if (!existsSync(agent.token_file)) {
        log(`Skipping agent ${name} - token file not found: ${agent.token_file}`);
        continue;
      }

      const token = getToken(agent.token_file);
      const userId = await getMatrixUserId(token);
      agentUserIds.set(name, userId);
      log(`✓ Initialized agent ${name} as ${userId}`);

      const sync = await matrixSync(token);
      syncTokens.set(name, sync.next_batch);
    } catch (err) {
      logError(`Failed to initialize agent ${name}`, err);
    }
  }
}

async function main(): Promise<void> {
  console.log('');
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║       IG-88 Matrix Multi-Agent Coordinator       ║');
  console.log('╠══════════════════════════════════════════════════╣');
  console.log('║  Agents: kelk, boot, ig88                        ║');
  console.log('║  Devices: rp5, cloudkicker, mac, openrouter      ║');
  console.log('╚══════════════════════════════════════════════════╝');
  console.log('');

  config = loadConfig();

  process.on('SIGHUP', reloadConfig);
  log('Send SIGHUP to reload configuration');

  watchFile(CONFIG_PATH, { interval: 5000 }, () => {
    log('Config file changed, reloading...');
    reloadConfig();
  });

  log('Initializing agents...');
  await initializeAgents();

  log('Checking device health...');
  await updateDeviceHealth();

  console.log('');
  log('Coordinator online. Listening for messages...');
  log('Hybrid mode: ' + (config.settings.hybrid_mode ? 'enabled' : 'disabled'));
  console.log('');

  // Main polling loop
  while (true) {
    await Promise.all(
      Object.keys(config.agents).map(name => pollAgent(name))
    );

    // Periodic health check (every 10 polls)
    if (Math.random() < 0.1) {
      await updateDeviceHealth();
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

main().catch((err) => {
  logError('Fatal error', err);
  process.exit(1);
});
