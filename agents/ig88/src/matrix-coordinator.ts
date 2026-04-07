// Matrix Coordinator - Multi-Agent Router for IG-88
// Unified architecture: persistent Claude sessions + approval passthrough + Pantalaimon E2EE
// Routes messages to appropriate agents based on room/agent configuration
// BKX014: Merger of matrix-bridge.ts persistent session architecture

import { spawn, ChildProcess } from 'child_process';
import { readFileSync, existsSync, watchFile, readdirSync, writeFileSync, unlinkSync, mkdirSync } from 'fs';
import { createInterface, Interface } from 'readline';
import * as yaml from 'yaml';
import type { PendingApproval, Sprint } from './types.js';
import { TokenManager, type TokenHealth } from './token-manager.js';

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
  max_claude_sessions: number;
  pantalaimon_url?: string;
  approval_timeout_ms: number;
  approval_owner: string;
  auto_approve_patterns: string[];
  always_require_approval: string[];
  credential_source?: 'systemd' | 'gpg' | 'env';
  credential_path?: string;
}

interface Device {
  type: 'local' | 'remote' | 'cloud';
  tailscale_ip?: string;
  ssh_alias?: string;
  tmux_socket?: string;
  api_base?: string;
  models?: string[];
}

interface AgentConfig {
  matrix_user: string;
  token_file: string;
  description: string;
  sandbox_profile: 'personal' | 'work' | 'restricted';
  default_device: string;
  ssh_dispatch?: string[];
  system_prompt?: string;
}

interface Room {
  name: string;
  prefix: string | null;
  default_agent: string | null;
  agents?: string[];  // Additional agents that monitor this room (for @mentions)
  graphiti_group: string;
  sandbox_profile: 'personal' | 'work' | 'restricted';
  worker_cwd?: string;
  tmux_session?: string;
  require_mention?: boolean;
}

interface Config {
  settings: Settings;
  allowlist: string[];
  devices: Record<string, Device>;
  agents: Record<string, AgentConfig>;
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
    formatted_body?: string;  // HTML body with Matrix mention links
    'm.relates_to'?: {
      rel_type?: string;
      event_id?: string;
      key?: string;
    };
  };
  event_id: string;
  room_id?: string;
}

interface MatrixReactionEvent {
  type: 'm.reaction';
  sender: string;
  event_id: string;
  content: {
    'm.relates_to': {
      rel_type: 'm.annotation';
      event_id: string;
      key: string;
    };
  };
}

// Claude stream-json response types
interface ClaudeInitResponse {
  type: 'system';
  subtype: 'init';
  session_id: string;
  tools: unknown[];
  model: string;
}

interface ClaudeAssistantResponse {
  type: 'assistant';
  message: {
    content: Array<{
      type: string;
      text?: string;
      name?: string;
      input?: unknown;
    }>;
    usage?: {
      input_tokens: number;
      output_tokens: number;
    };
  };
}

interface ClaudeResultResponse {
  type: 'result';
  subtype: 'success' | 'error';
  result?: string;
  error?: string;
  total_cost_usd?: number;
  usage?: {
    input_tokens: number;
    output_tokens: number;
  };
}

interface ClaudeInputRequest {
  type: 'input_request';
  request_id: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
}

type ClaudeResponse = ClaudeInitResponse | ClaudeAssistantResponse | ClaudeResultResponse | ClaudeInputRequest;

// AgentSession - encapsulates all per-agent state
interface AgentSession {
  name: string;
  config: AgentConfig;
  matrixToken: string;
  matrixUserId: string;
  syncToken: string;

  // Claude session (persistent)
  claudeProcess: ChildProcess | null;
  claudeStdin: NodeJS.WritableStream | null;
  claudeReader: Interface | null;
  claudeReady: boolean;
  claudeSessionId: string | null;

  // Request handling
  currentRequestResolver: ((response: ClaudeResultResponse) => void) | null;
  currentRequestRejecter: ((error: Error) => void) | null;
  currentAssistantMessage: ClaudeAssistantResponse | null;
  currentRoomId: string | null;

  // Room assignments
  rooms: Set<string>;

  // Approval state
  pendingApprovals: Map<string, PendingApproval>;

  // Last approved action context (for completion confirmation)
  lastApprovalContext: {
    threadRootId: string;
    roomId: string;
    tool: string;
    timestamp: number;
  } | null;

  // Pending conversational approval (waiting for user to reply yes/no)
  pendingConversationalApproval: {
    threadRootId: string;
    roomId: string;
    originalResponse: string;
    timestamp: number;
  } | null;

  // Sprint state
  activeSprints: Map<string, Sprint>;
  currentSprintName: string | null;

  // Verbose mode
  verboseMode: boolean;

  // Token health tracking
  tokenHealth: TokenHealth | null;

  // Recent message buffer for checkpointing
  recentMessages: Array<{
    role: 'user' | 'assistant';
    content: string;
    roomId: string;
    timestamp: number;
  }>;
}

// ============================================================================
// Configuration
// ============================================================================

const CONFIG_PATH = process.env.CONFIG_PATH || `${process.env.HOME}/projects/ig88/config/agent-config.yaml`;
const MAX_RESPONSE_LENGTH = 4000;
const POLL_INTERVAL_MS = 3000;
const CLAUDE_RESTART_DELAY_MS = 5000;
const CLAUDE_MODEL = 'haiku';
const CLAUDE_FALLBACK_MODEL = 'sonnet';
const APPROVAL_DIR = '/tmp/ig88-approvals';
const CHECKPOINT_DIR = `${process.env.HOME}/.config/ig88/checkpoints`;
const MAX_RECENT_MESSAGES = 20;
const OLLAMA_URL = 'http://localhost:11434';
const GRAPHITI_URL = 'http://100.88.222.111:41440';

let config: Config;
let shuttingDown = false;
const agents: Map<string, AgentSession> = new Map();
const deviceHealth: Map<string, boolean> = new Map();
let tokenManager: TokenManager | null = null;

// Track hook-based approvals: request_id -> { threadRootId, roomId, agentName }
const hookApprovals: Map<string, {
  threadRootId: string;
  roomId: string;
  agentName: string;
  toolName: string;
  timestamp: number;
}> = new Map();

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
// Session Checkpointing
// ============================================================================

function ensureCheckpointDir(): void {
  if (!existsSync(CHECKPOINT_DIR)) {
    mkdirSync(CHECKPOINT_DIR, { recursive: true });
  }
}

function saveCheckpoint(agent: AgentSession): void {
  try {
    ensureCheckpointDir();

    if (agent.recentMessages.length === 0) {
      log(`[${agent.name}] No messages to checkpoint`);
      return;
    }

    const checkpoint = {
      agent: agent.name,
      sessionId: agent.claudeSessionId,
      timestamp: new Date().toISOString(),
      currentRoomId: agent.currentRoomId,
      activeSprints: Array.from(agent.activeSprints.entries()).map(([name, sprint]) => ({
        name,
        messageCount: sprint.messageCount,
        startedAt: new Date(sprint.startedAt).toISOString(),
      })),
      messageCount: agent.recentMessages.length,
      messages: agent.recentMessages.map(m => ({
        role: m.role,
        content: m.content.slice(0, 2000),
        room: config.rooms[m.roomId]?.name || m.roomId,
        time: new Date(m.timestamp).toISOString(),
      })),
    };

    const filePath = `${CHECKPOINT_DIR}/${agent.name}.json`;
    writeFileSync(filePath, JSON.stringify(checkpoint, null, 2));
    log(`[${agent.name}] Checkpoint saved (${agent.recentMessages.length} messages)`);
  } catch (err) {
    logError(`[${agent.name}] Failed to save checkpoint`, err);
  }
}

function loadCheckpoint(agentName: string): string | null {
  try {
    const filePath = `${CHECKPOINT_DIR}/${agentName}.json`;
    if (!existsSync(filePath)) return null;

    const raw = readFileSync(filePath, 'utf-8');
    const checkpoint = JSON.parse(raw);

    // Build a context recovery prompt from the checkpoint
    const lines: string[] = [
      `[CONTEXT RECOVERY] Your previous session ended unexpectedly at ${checkpoint.timestamp}.`,
      `Here is a summary of recent conversation to restore context:`,
      '',
    ];

    if (checkpoint.activeSprints?.length > 0) {
      lines.push(`Active sprints: ${checkpoint.activeSprints.map((s: { name: string; messageCount: number }) => `${s.name} (${s.messageCount} msgs)`).join(', ')}`);
      lines.push('');
    }

    lines.push(`Last ${checkpoint.messageCount} messages:`);
    for (const msg of checkpoint.messages) {
      const prefix = msg.role === 'user' ? 'User' : 'You';
      const roomLabel = msg.room ? ` [${msg.room}]` : '';
      lines.push(`${prefix}${roomLabel}: ${msg.content}`);
    }

    lines.push('');
    lines.push('Resume from where you left off. Acknowledge the context recovery briefly and continue working.');

    return lines.join('\n');
  } catch (err) {
    logError(`Failed to load checkpoint for ${agentName}`, err);
    return null;
  }
}

function clearCheckpoint(agentName: string): void {
  try {
    const filePath = `${CHECKPOINT_DIR}/${agentName}.json`;
    if (existsSync(filePath)) {
      unlinkSync(filePath);
    }
  } catch { /* ignore */ }
}

// ============================================================================
// Observational Memory (Auto-Extract from Conversations)
// ============================================================================

type ObservationCategory = 'decision' | 'lesson' | 'preference' | 'milestone' | 'commitment' | 'context';

interface Observation {
  category: ObservationCategory;
  content: string;
}

const OBSERVATION_PROMPT = `You are an observation extractor. Given a conversation turn between a user and an AI assistant, extract any significant observations.

Classify each observation into exactly one category:
- decision: A choice made about architecture, tools, approach, or direction
- lesson: Something learned from experience, debugging, or investigation
- preference: A stated user preference or working style
- milestone: A significant accomplishment or completion
- commitment: A promise or planned future action
- context: Background knowledge useful for future sessions

Rules:
- Only extract genuinely significant observations (not routine Q&A)
- Each observation should be a complete, self-contained statement
- If there are no significant observations, return an empty array
- Return JSON only, no other text

Return format:
[{"category": "decision", "content": "Decided to use FTS5 for keyword search alongside Qdrant vectors"}]

User message:
{USER_MESSAGE}

Assistant response:
{ASSISTANT_RESPONSE}

Extract observations (JSON array):`;

async function extractObservations(
  agent: AgentSession,
  userMessage: string,
  assistantResponse: string,
  roomId: string
): Promise<void> {
  // Skip short or trivial exchanges
  if (userMessage.length < 20 && assistantResponse.length < 50) return;
  if (userMessage.startsWith('/')) return; // Skip slash commands

  const room = config.rooms[roomId];
  const groupId = room?.graphiti_group || 'system';

  try {
    // Call Ollama for observation extraction
    const prompt = OBSERVATION_PROMPT
      .replace('{USER_MESSAGE}', userMessage.slice(0, 2000))
      .replace('{ASSISTANT_RESPONSE}', assistantResponse.slice(0, 2000));

    const ollamaResponse = await fetch(`${OLLAMA_URL}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'qwen2.5:3b',
        prompt,
        stream: false,
        options: { temperature: 0.1, num_predict: 512 },
      }),
    });

    if (!ollamaResponse.ok) {
      log(`[${agent.name}] Ollama returned ${ollamaResponse.status}`);
      return;
    }

    const ollamaResult = await ollamaResponse.json() as { response: string };
    const responseText = ollamaResult.response.trim();

    // Parse observations from Ollama's JSON response
    let observations: Observation[];
    try {
      // Extract JSON array from response (may have surrounding text)
      const jsonMatch = responseText.match(/\[[\s\S]*\]/);
      if (!jsonMatch) return;
      observations = JSON.parse(jsonMatch[0]);
    } catch {
      log(`[${agent.name}] Failed to parse observations: ${responseText.slice(0, 100)}`);
      return;
    }

    if (!Array.isArray(observations) || observations.length === 0) return;

    // Store each observation to Graphiti
    for (const obs of observations) {
      if (!obs.category || !obs.content) continue;

      const validCategories: ObservationCategory[] = ['decision', 'lesson', 'preference', 'milestone', 'commitment', 'context'];
      if (!validCategories.includes(obs.category)) continue;

      try {
        await fetch(`${GRAPHITI_URL}/episodes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: `${obs.category}: ${obs.content.slice(0, 80)}`,
            episode_body: `[${obs.category}] ${obs.content}`,
            source_description: `Auto-extracted from ${agent.name} conversation in ${room?.name || roomId}`,
            group_id: groupId,
            source: 'message',
          }),
        });

        log(`[${agent.name}] Stored observation: [${obs.category}] ${obs.content.slice(0, 60)}`);
      } catch (err) {
        logError(`[${agent.name}] Failed to store observation to Graphiti`, err);
      }
    }
  } catch (err) {
    // Non-critical: log and move on
    logError(`[${agent.name}] Observation extraction error`, err);
  }
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

  // Set defaults for approval settings
  if (!parsed.settings.approval_timeout_ms) {
    parsed.settings.approval_timeout_ms = 600000;
  }
  if (!parsed.settings.auto_approve_patterns) {
    parsed.settings.auto_approve_patterns = [];
  }
  if (!parsed.settings.always_require_approval) {
    parsed.settings.always_require_approval = [];
  }
  if (!parsed.settings.max_claude_sessions) {
    parsed.settings.max_claude_sessions = 5;
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
// Matrix API - Pantalaimon Support
// ============================================================================

function getMatrixBaseUrl(): string {
  // Use Pantalaimon if configured, otherwise direct Matrix
  return config.settings.pantalaimon_url || 'https://matrix.org';
}

function getToken(tokenFile: string): string {
  if (!existsSync(tokenFile)) {
    throw new Error(`Token file not found: ${tokenFile}`);
  }
  return readFileSync(tokenFile, 'utf-8').trim();
}

async function getMatrixUserId(token: string): Promise<string> {
  const baseUrl = getMatrixBaseUrl();
  const response = await fetch(`${baseUrl}/_matrix/client/r0/account/whoami`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Failed to get user ID: ${response.status}`);
  }

  const data = await response.json() as { user_id: string };
  return data.user_id;
}

async function matrixSync(token: string, sinceToken?: string): Promise<SyncResponse> {
  const baseUrl = getMatrixBaseUrl();
  const params = new URLSearchParams({ timeout: '30000' });
  if (sinceToken) {
    params.set('since', sinceToken);
  }

  const response = await fetch(`${baseUrl}/_matrix/client/r0/sync?${params}`, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    const error = new Error(`Sync failed: ${response.status}`) as Error & { status: number };
    error.status = response.status;
    throw error;
  }

  return response.json() as Promise<SyncResponse>;
}

async function sendMessage(token: string, roomId: string, body: string): Promise<{ event_id: string } | null> {
  const baseUrl = getMatrixBaseUrl();
  const txnId = `coord_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const url = `${baseUrl}/_matrix/client/r0/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}`;

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

    if (!response.ok) {
      const error = new Error(`Matrix send failed: ${response.status}`) as Error & { status: number };
      error.status = response.status;
      throw error;
    }

    return response.json() as Promise<{ event_id: string }>;
  } catch (err) {
    logError('Failed to send message', err);
    return null;
  }
}

async function sendTyping(token: string, roomId: string, userId: string, typing: boolean): Promise<void> {
  const baseUrl = getMatrixBaseUrl();
  const url = `${baseUrl}/_matrix/client/r0/rooms/${encodeURIComponent(roomId)}/typing/${encodeURIComponent(userId)}`;

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

async function sendThreadMessage(
  token: string,
  roomId: string,
  threadRootId: string,
  body: string
): Promise<{ event_id: string } | null> {
  const baseUrl = getMatrixBaseUrl();
  const txnId = `coord_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const url = `${baseUrl}/_matrix/client/r0/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}`;

  const message = {
    msgtype: 'm.text',
    body,
    'm.relates_to': {
      rel_type: 'm.thread',
      event_id: threadRootId,
      is_falling_back: true,
      'm.in_reply_to': {
        event_id: threadRootId,
      },
    },
  };

  try {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(message),
    });

    if (!response.ok) {
      logError(`Matrix thread send failed: ${response.status}`);
      return null;
    }

    return response.json() as Promise<{ event_id: string }>;
  } catch (err) {
    logError('Failed to send thread message', err);
    return null;
  }
}

// ============================================================================
// Authorization
// ============================================================================

function isAuthorized(sender: string): boolean {
  if (!config.allowlist.includes(sender)) {
    log(`Unauthorized sender: ${sender}`);
    return false;
  }
  return true;
}

function requiresMention(roomId: string, body: string, formattedBody: string | undefined, agentUserId: string, agentName: string): boolean {
  const room = config.rooms[roomId];

  // Extract agent's local username for mention matching (e.g., "sir.kelk" from "@sir.kelk:matrix.org")
  const localPart = agentUserId.split(':')[0].slice(1); // Remove @ prefix

  // Check multiple mention patterns in plain text body:
  // 1. Full Matrix mention: @sir.kelk
  // 2. Agent config name: @kelk (from config key)
  // 3. First part before dot: @sir (for @sir.kelk)
  const patterns = [
    new RegExp(`@${localPart}`, 'i'),           // @sir.kelk
    new RegExp(`@${agentName}\\b`, 'i'),        // @kelk (word boundary to avoid partial matches)
  ];

  // For names with dots, also match the first segment (e.g., @boot for @boot.industries)
  if (localPart.includes('.')) {
    patterns.push(new RegExp(`@${localPart.split('.')[0]}\\b`, 'i'));
  }

  let isMentioned = patterns.some(pattern => pattern.test(body));

  // Also check formatted_body for Matrix mention links (Element's mention pills)
  // These appear as: <a href="https://matrix.to/#/@boot.industries:matrix.org">Boot</a>
  if (!isMentioned && formattedBody) {
    // Check for matrix.to link containing the agent's user ID
    const mentionLinkPattern = new RegExp(`matrix\\.to/#/${agentUserId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'i');
    isMentioned = mentionLinkPattern.test(formattedBody);
  }

  // If agent is in room's agents array but NOT the default_agent, require @mention
  if (room?.agents?.includes(agentName) && room.default_agent !== agentName) {
    return !isMentioned;
  }

  // If room explicitly disables mention requirement, allow through
  if (room?.require_mention === false) {
    return false;
  }

  // Standard require_mention or group_policy check
  if (room?.require_mention || config.settings.group_policy === 'mention') {
    return !isMentioned;
  }

  return false;
}

// ============================================================================
// Utilities
// ============================================================================

function formatAge(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

function formatToolInput(input: Record<string, unknown>): string {
  if (input.command && typeof input.command === 'string') {
    const cmd = input.command;
    if (cmd.length > 100) {
      return cmd.slice(0, 100) + '...';
    }
    return cmd;
  }

  if (input.file_path && typeof input.file_path === 'string') {
    return input.file_path;
  }

  const str = JSON.stringify(input);
  if (str.length > 100) {
    return str.slice(0, 100) + '...';
  }
  return str;
}

function truncateResponse(response: string): string {
  if (response.length <= MAX_RESPONSE_LENGTH) {
    return response;
  }
  return response.slice(0, MAX_RESPONSE_LENGTH - 50) + '\n\n[...truncated]';
}

// Detect if Claude's response is asking for permission conversationally
function isPermissionRequest(response: string): boolean {
  const patterns = [
    /\bneed your permission\b/i,
    /\bwould you like me to proceed\b/i,
    /\bcan you (approve|grant|confirm)\b/i,
    /\brequires? (your )?approval\b/i,
    /\bshould I (proceed|continue|go ahead)\b/i,
    /\bpermission to (write|edit|create|modify|delete)\b/i,
    /\bhaven't granted it yet\b/i,
  ];
  return patterns.some(pattern => pattern.test(response));
}

// Create a conversational approval thread
async function createConversationalApprovalThread(
  agent: AgentSession,
  roomId: string,
  originalResponse: string
): Promise<string | null> {
  // Extract relevant info from Claude's response for the thread
  const rootBody = `🔐 **Permission Request** (${agent.name})\n\n${originalResponse.slice(0, 500)}${originalResponse.length > 500 ? '...' : ''}`;
  const rootEvent = await sendMessage(agent.matrixToken, roomId, rootBody);

  if (!rootEvent) return null;

  // Send thread prompt
  const threadBody = `React with ✅ to approve or ❌ to deny\n(Or reply "yes" / "no" in this thread)`;
  await sendThreadMessage(agent.matrixToken, roomId, rootEvent.event_id, threadBody);

  return rootEvent.event_id;
}

function extractReactions(sync: SyncResponse, roomId: string): MatrixReactionEvent[] {
  const room = sync.rooms?.join?.[roomId];
  if (!room?.timeline?.events) return [];

  return room.timeline.events.filter(
    (e): e is MatrixReactionEvent =>
      e.type === 'm.reaction' &&
      e.content?.['m.relates_to']?.rel_type === 'm.annotation'
  ) as MatrixReactionEvent[];
}

// ============================================================================
// Claude Session Management (per Agent)
// ============================================================================

function countActiveClaudeSessions(): number {
  let count = 0;
  for (const agent of agents.values()) {
    if (agent.claudeProcess && agent.claudeReady) {
      count++;
    }
  }
  return count;
}

function startClaudeSession(agent: AgentSession): void {
  // Check session limit
  const activeCount = countActiveClaudeSessions();
  if (activeCount >= config.settings.max_claude_sessions) {
    log(`[${agent.name}] Cannot start Claude session: limit reached (${activeCount}/${config.settings.max_claude_sessions})`);
    return;
  }

  log(`Starting Claude session for ${agent.name}... (${activeCount + 1}/${config.settings.max_claude_sessions})`);

  const cwd = getAgentDefaultCwd(agent);

  const args = [
    '--input-format', 'stream-json',
    '--output-format', 'stream-json',
    '--permission-mode', 'delegate',
    '--verbose',
    '--model', CLAUDE_MODEL,
    '--fallback-model', CLAUDE_FALLBACK_MODEL,
  ];

  // Add personality scaffolding if configured
  if (agent.config.system_prompt) {
    args.push('--append-system-prompt', agent.config.system_prompt);
  }

  agent.claudeProcess = spawn('claude', args, {
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  agent.claudeStdin = agent.claudeProcess.stdin!;

  // Read streaming JSON responses line by line
  agent.claudeReader = createInterface({ input: agent.claudeProcess.stdout! });
  agent.claudeReader.on('line', (line) => {
    if (!line.trim()) return;

    try {
      const response = JSON.parse(line) as ClaudeResponse;
      handleClaudeResponse(agent, response);
    } catch {
      log(`[${agent.name}] Claude non-JSON: ${line.slice(0, 100)}`);
    }
  });

  // Log stderr for debugging
  agent.claudeProcess.stderr?.on('data', (data: Buffer) => {
    const text = data.toString().trim();
    if (text) {
      log(`[${agent.name}] Claude stderr: ${text.slice(0, 200)}`);
    }
  });

  agent.claudeProcess.on('exit', (code, signal) => {
    log(`[${agent.name}] Claude process exited with code ${code}, signal ${signal}`);
    agent.claudeReady = false;
    agent.claudeProcess = null;
    agent.claudeStdin = null;
    agent.claudeReader = null;

    // Reject any pending request
    if (agent.currentRequestRejecter) {
      agent.currentRequestRejecter(new Error(`Claude process exited unexpectedly (code ${code})`));
      agent.currentRequestResolver = null;
      agent.currentRequestRejecter = null;
    }

    // Save checkpoint before restart so context can be recovered
    if (code !== 0 && !shuttingDown) {
      saveCheckpoint(agent);
      log(`[${agent.name}] Restarting Claude session in ${CLAUDE_RESTART_DELAY_MS}ms...`);
      setTimeout(() => startClaudeSession(agent), CLAUDE_RESTART_DELAY_MS);
    }
  });

  agent.claudeProcess.on('error', (err) => {
    logError(`[${agent.name}] Claude process error`, err);
    agent.claudeReady = false;
  });

  agent.claudeReady = true;
  log(`[${agent.name}] Claude session started`);

  // Inject checkpoint from previous session if available
  const checkpointContent = loadCheckpoint(agent.name);
  if (checkpointContent) {
    log(`[${agent.name}] Injecting checkpoint from previous session`);
    // Small delay to let the Claude session fully initialize
    setTimeout(() => {
      if (agent.claudeStdin && agent.claudeReady) {
        const input = JSON.stringify({
          type: 'user',
          message: { role: 'user', content: checkpointContent },
        });
        agent.claudeStdin.write(input + '\n');
        clearCheckpoint(agent.name);
        log(`[${agent.name}] Checkpoint injected and cleared`);
      }
    }, 2000);
  }
}

function getAgentDefaultCwd(agent: AgentSession): string {
  // Find the first room assigned to this agent and use its worker_cwd
  for (const roomId of agent.rooms) {
    const room = config.rooms[roomId];
    if (room?.worker_cwd) {
      return room.worker_cwd;
    }
  }
  return process.env.HOME || '/';
}

function handleClaudeResponse(agent: AgentSession, response: ClaudeResponse): void {
  switch (response.type) {
    case 'system':
      if (response.subtype === 'init') {
        agent.claudeSessionId = response.session_id;
        log(`[${agent.name}] Claude session initialized: model=${response.model}, session_id=${response.session_id}`);
      }
      break;

    case 'assistant':
      agent.currentAssistantMessage = response;
      break;

    case 'result':
      // Send completion confirmation if there's a recent approval context
      if (agent.lastApprovalContext) {
        const age = Date.now() - agent.lastApprovalContext.timestamp;
        // Only confirm if approval was within last 60 seconds
        if (age < 60000) {
          const ctx = agent.lastApprovalContext;
          const status = response.subtype === 'success' ? '✅ Complete' : '⚠️ Error';
          const resultPreview = response.result?.slice(0, 200) || response.error?.slice(0, 200) || '';
          sendThreadMessage(
            agent.matrixToken,
            ctx.roomId,
            ctx.threadRootId,
            `${status}: ${ctx.tool}\n${resultPreview ? '```\n' + resultPreview + '\n```' : ''}`
          );
        }
        agent.lastApprovalContext = null;
      }

      if (agent.currentRequestResolver) {
        agent.currentRequestResolver(response);
        agent.currentRequestResolver = null;
        agent.currentRequestRejecter = null;
      }
      break;

    case 'input_request':
      handleInputRequest(agent, response);
      break;
  }
}

async function sendToClaudeSession(
  agent: AgentSession,
  message: string,
  roomId: string
): Promise<{ result: string; assistantMessage: ClaudeAssistantResponse | null; resultResponse: ClaudeResultResponse }> {
  if (!agent.claudeStdin || !agent.claudeReady) {
    throw new Error(`Claude session not ready for ${agent.name}`);
  }

  // Track current room for approval context
  agent.currentRoomId = roomId;
  agent.currentAssistantMessage = null;

  // Create the JSON input
  const input = JSON.stringify({
    type: 'user',
    message: { role: 'user', content: message },
  });

  // Write to stdin
  agent.claudeStdin.write(input + '\n');

  // Wait for result response
  return new Promise((resolve, reject) => {
    agent.currentRequestResolver = (resultResponse: ClaudeResultResponse) => {
      if (resultResponse.subtype === 'error') {
        reject(new Error(resultResponse.error || 'Claude returned an error'));
      } else {
        resolve({
          result: resultResponse.result || '',
          assistantMessage: agent.currentAssistantMessage,
          resultResponse,
        });
      }
    };
    agent.currentRequestRejecter = reject;

    // Timeout
    setTimeout(() => {
      if (agent.currentRequestRejecter === reject) {
        agent.currentRequestResolver = null;
        agent.currentRequestRejecter = null;
        reject(new Error('Claude response timeout'));
      }
    }, config.settings.claude_timeout_ms);
  });
}

// ============================================================================
// Approval System
// ============================================================================

async function handleInputRequest(agent: AgentSession, request: ClaudeInputRequest): Promise<void> {
  const { request_id, tool_name, tool_input } = request;

  if (!tool_name || !tool_input) {
    log(`[${agent.name}] Input request without tool info: ${request_id}`);
    return;
  }

  log(`[${agent.name}] Permission request: ${tool_name} (${request_id})`);

  // Check for auto-approve patterns
  if (shouldAutoApprove(tool_name, tool_input)) {
    log(`[${agent.name}] Auto-approving: ${tool_name}`);
    sendApprovalToClaudeSession(agent, request_id, 'allow');
    return;
  }

  // Create approval thread in Matrix
  const roomId = agent.currentRoomId || getAgentDefaultRoom(agent);
  if (!roomId) {
    log(`[${agent.name}] No room context for approval, denying`);
    sendApprovalToClaudeSession(agent, request_id, 'deny', 'No room context');
    return;
  }

  const approval = await createApprovalThread(agent, roomId, request_id, tool_name, tool_input);
  if (approval) {
    agent.pendingApprovals.set(request_id, approval);

    // Set timeout for re-prompting
    setTimeout(() => {
      checkApprovalTimeout(agent, request_id);
    }, config.settings.approval_timeout_ms);
  } else {
    log(`[${agent.name}] Failed to create approval thread, denying ${tool_name}`);
    sendApprovalToClaudeSession(agent, request_id, 'deny', 'Failed to create approval thread');
  }
}

function getAgentDefaultRoom(agent: AgentSession): string | null {
  const rooms = Array.from(agent.rooms);
  return rooms.length > 0 ? rooms[0] : null;
}

// Shell metacharacters that indicate command chaining, redirection, or subshells.
// Commands containing these should never be auto-approved. (BKX018)
const SHELL_METACHAR_PATTERN = /[|><;&`$()]/;

function shouldAutoApprove(toolName: string, input: Record<string, unknown>): boolean {
  if (toolName !== 'Bash') return false;

  const command = input.command as string | undefined;
  if (!command) return false;

  // Reject any command containing shell metacharacters (pipes, redirects, chaining, subshells)
  if (SHELL_METACHAR_PATTERN.test(command)) {
    return false;
  }

  // Check against always-require patterns first
  for (const pattern of config.settings.always_require_approval) {
    if (matchesPattern(command, pattern)) {
      return false;
    }
  }

  // Check auto-approve patterns
  for (const pattern of config.settings.auto_approve_patterns) {
    if (matchesPattern(command, pattern)) {
      return true;
    }
  }

  return false;
}

function matchesPattern(command: string, pattern: string): boolean {
  const regexStr = pattern
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\\\*/g, '.*');
  const regex = new RegExp(`^${regexStr}$`, 'i');
  return regex.test(command);
}

async function createApprovalThread(
  agent: AgentSession,
  roomId: string,
  requestId: string,
  toolName: string,
  toolInput: Record<string, unknown>
): Promise<PendingApproval | null> {
  const inputPreview = formatToolInput(toolInput);

  // Send root message
  const rootBody = `🔐 **Permission Request** (${agent.name})\nTool: \`${toolName}\`\n\`\`\`\n${inputPreview}\n\`\`\``;
  const rootEvent = await sendMessage(agent.matrixToken, roomId, rootBody);

  if (!rootEvent) return null;

  // Send thread prompt
  const threadBody = `React with ✅ to approve or ❌ to deny\nRequest ID: \`${requestId.slice(0, 8)}\``;
  const threadEvent = await sendThreadMessage(agent.matrixToken, roomId, rootEvent.event_id, threadBody);

  if (!threadEvent) return null;

  return {
    requestId,
    tool: toolName,
    input: toolInput,
    matrixEventId: threadEvent.event_id,
    threadRootId: rootEvent.event_id,
    sender: config.settings.approval_owner,
    timestamp: Date.now(),
  };
}

function checkApprovalTimeout(agent: AgentSession, requestId: string): void {
  const approval = agent.pendingApprovals.get(requestId);
  if (!approval) return;

  const age = Date.now() - approval.timestamp;
  if (age >= config.settings.approval_timeout_ms) {
    log(`[${agent.name}] Approval timeout for ${requestId}, re-prompting...`);

    const roomId = agent.currentRoomId || getAgentDefaultRoom(agent);
    if (roomId) {
      sendThreadMessage(
        agent.matrixToken,
        roomId,
        approval.threadRootId,
        `⏰ Approval still pending. React ✅ or ❌ to continue.`
      );
    }

    // Update timestamp and set another timeout
    approval.timestamp = Date.now();
    agent.pendingApprovals.set(requestId, approval);

    setTimeout(() => {
      checkApprovalTimeout(agent, requestId);
    }, config.settings.approval_timeout_ms);
  }
}

function sendApprovalToClaudeSession(
  agent: AgentSession,
  requestId: string,
  decision: 'allow' | 'deny',
  message?: string
): void {
  if (!agent.claudeStdin || !agent.claudeReady) {
    logError(`[${agent.name}] Cannot send approval - Claude session not ready`);
    return;
  }

  const response = JSON.stringify({
    type: 'user',
    message: {
      role: 'user',
      content: decision === 'allow' ? 'yes' : `no${message ? `: ${message}` : ''}`,
    },
  });

  agent.claudeStdin.write(response + '\n');
  log(`[${agent.name}] Sent ${decision} for request ${requestId.slice(0, 8)}`);
}

async function handleReactionEvent(agent: AgentSession, roomId: string, event: MatrixReactionEvent): Promise<void> {
  const relatesTo = event.content['m.relates_to'];
  const targetEventId = relatesTo.event_id;
  const key = relatesTo.key;

  // Only allow approval owner to react
  if (event.sender !== config.settings.approval_owner) {
    return;
  }

  // Find pending approval for this event
  for (const [requestId, approval] of agent.pendingApprovals) {
    if (approval.threadRootId === targetEventId || approval.matrixEventId === targetEventId) {
      if (key === '✅' || key === '👍') {
        log(`[${agent.name}] Approved: ${approval.tool} (${requestId.slice(0, 8)})`);
        sendApprovalToClaudeSession(agent, requestId, 'allow');
        agent.pendingApprovals.delete(requestId);

        // Store context for completion confirmation
        agent.lastApprovalContext = {
          threadRootId: approval.threadRootId,
          roomId,
          tool: approval.tool,
          timestamp: Date.now(),
        };

        sendThreadMessage(agent.matrixToken, roomId, approval.threadRootId, '✅ Approved - executing...');
      } else if (key === '❌' || key === '👎') {
        log(`[${agent.name}] Denied: ${approval.tool} (${requestId.slice(0, 8)})`);
        sendApprovalToClaudeSession(agent, requestId, 'deny', 'User denied');
        agent.pendingApprovals.delete(requestId);

        sendThreadMessage(agent.matrixToken, roomId, approval.threadRootId, '❌ Denied');
      }
      break;
    }
  }

  // Also check for conversational approval reactions
  const pending = agent.pendingConversationalApproval;
  if (pending && pending.threadRootId === targetEventId) {
    if (key === '✅' || key === '👍') {
      log(`[${agent.name}] Conversational approval: approved via reaction`);
      await handleConversationalApprovalResponse(agent, true);
    } else if (key === '❌' || key === '👎') {
      log(`[${agent.name}] Conversational approval: denied via reaction`);
      await handleConversationalApprovalResponse(agent, false);
    }
  }
}

// Handle user's approval/denial of a conversational permission request
async function handleConversationalApprovalResponse(agent: AgentSession, approved: boolean): Promise<void> {
  const pending = agent.pendingConversationalApproval;
  if (!pending) return;

  const { threadRootId, roomId } = pending;

  // Clear pending state first
  agent.pendingConversationalApproval = null;

  // Store context for completion confirmation
  agent.lastApprovalContext = {
    threadRootId,
    roomId,
    tool: 'conversational',
    timestamp: Date.now(),
  };

  // Send acknowledgment to thread
  await sendThreadMessage(
    agent.matrixToken,
    roomId,
    threadRootId,
    approved ? '✅ Approved - executing...' : '❌ Denied'
  );

  if (!approved) {
    // Send denial to Claude
    await sendToClaudeSession(agent, 'No, please do not proceed.', roomId);
    return;
  }

  // Send approval to Claude
  try {
    const { result, assistantMessage, resultResponse } = await sendToClaudeSession(agent, 'Yes, please proceed.', roomId);
    const response = formatResponse(agent, result, assistantMessage, resultResponse);
    const truncated = truncateResponse(response);

    // Send Claude's response in the thread
    await sendThreadMessage(agent.matrixToken, roomId, threadRootId, truncated);

    log(`[${agent.name}] Conversational approval completed`);
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    await sendThreadMessage(agent.matrixToken, roomId, threadRootId, `Error: ${errorMsg.slice(0, 200)}`);
    logError(`[${agent.name}] Conversational approval failed`, err);
  }
}

// ============================================================================
// Slash Commands
// ============================================================================

async function handleCommand(
  agent: AgentSession,
  roomId: string,
  command: string
): Promise<string | null> {
  const cmd = command.toLowerCase().trim();
  const args = command.trim().split(/\s+/).slice(1);

  if (cmd === '/status' || cmd === '/session') {
    const room = config.rooms[roomId];
    return `${agent.name} Agent Status
========================
Online: ${new Date().toISOString()}
Bot User: ${agent.matrixUserId}
Room: ${room?.name || roomId}
Claude Session: ${agent.claudeReady ? 'Active' : 'Inactive'}
Session ID: ${agent.claudeSessionId?.slice(0, 8) || 'None'}
Verbose Mode: ${agent.verboseMode ? 'On' : 'Off'}
Pending Approvals: ${agent.pendingApprovals.size}
Active Sprints: ${agent.activeSprints.size}
Current Sprint: ${agent.currentSprintName || 'None'}
========================`;
  }

  if (cmd === '/help') {
    return `${agent.name} Commands
========================
**Core:**
/status  - Show agent status
/verbose - Toggle verbose output
/agents  - List all agents

**Approvals:**
/pending           - Show pending approvals
/approve <id>      - Approve by request ID
/deny <id> [reason] - Deny by request ID

**Sprints:**
/sprint start <name> - Start a sprint thread
/sprint end          - End current sprint
/sprint list         - Show active sprints

**Memory:**
/checkpoint - Save session checkpoint now

/help    - Show this help
========================`;
  }

  if (cmd === '/agents') {
    const activeCount = countActiveClaudeSessions();
    let output = `**Active Agents:** (${activeCount}/${config.settings.max_claude_sessions} sessions)\n`;
    for (const [name, a] of agents) {
      const status = a.claudeReady ? '🟢' : '🔴';
      output += `- ${status} ${name}: ${a.config.description}\n`;
      output += `  Rooms: ${a.rooms.size}, Pending: ${a.pendingApprovals.size}\n`;
    }
    return output;
  }

  // Verbose mode
  if (cmd === '/verbose on') {
    agent.verboseMode = true;
    return 'Verbose mode enabled.';
  }

  if (cmd === '/verbose off') {
    agent.verboseMode = false;
    return 'Verbose mode disabled.';
  }

  if (cmd === '/verbose') {
    return `Verbose mode is currently ${agent.verboseMode ? 'ON' : 'OFF'}.`;
  }

  // Pending approvals
  if (cmd === '/pending') {
    if (agent.pendingApprovals.size === 0) {
      return 'No pending approvals.';
    }
    let output = '**Pending Approvals:**\n';
    for (const [id, approval] of agent.pendingApprovals) {
      output += `- \`${id.slice(0, 8)}\`: ${approval.tool} (${formatAge(approval.timestamp)})\n`;
    }
    return output;
  }

  // Approve command
  if (cmd.startsWith('/approve ')) {
    const id = args[0];
    if (!id) return 'Usage: /approve <request_id>';

    const approval = findApprovalByPrefix(agent, id);
    if (!approval) return `No pending approval matching: ${id}`;

    sendApprovalToClaudeSession(agent, approval.requestId, 'allow');
    agent.pendingApprovals.delete(approval.requestId);
    sendThreadMessage(agent.matrixToken, roomId, approval.threadRootId, '✅ Approved via /approve');

    return `✅ Approved: ${approval.tool}`;
  }

  // Deny command
  if (cmd.startsWith('/deny ')) {
    const id = args[0];
    if (!id) return 'Usage: /deny <request_id> [reason]';

    const approval = findApprovalByPrefix(agent, id);
    if (!approval) return `No pending approval matching: ${id}`;

    const reason = args.slice(1).join(' ') || 'User denied via command';
    sendApprovalToClaudeSession(agent, approval.requestId, 'deny', reason);
    agent.pendingApprovals.delete(approval.requestId);
    sendThreadMessage(agent.matrixToken, roomId, approval.threadRootId, `❌ Denied: ${reason}`);

    return `❌ Denied: ${approval.tool}`;
  }

  // Sprint commands
  if (cmd.startsWith('/sprint ')) {
    const subCmd = args[0]?.toLowerCase();

    if (subCmd === 'start') {
      const name = args.slice(1).join(' ');
      if (!name) return 'Usage: /sprint start <name>';

      const rootEvent = await sendMessage(agent.matrixToken, roomId, `🏃 **Sprint Started:** ${name}`);
      if (!rootEvent) return 'Failed to create sprint thread';

      const sprint: Sprint = {
        name,
        threadRootId: rootEvent.event_id,
        startedAt: Date.now(),
        messageCount: 0,
      };
      agent.activeSprints.set(name, sprint);
      agent.currentSprintName = name;

      return `Sprint "${name}" started.`;
    }

    if (subCmd === 'end') {
      if (!agent.currentSprintName) return 'No active sprint to end.';

      const sprint = agent.activeSprints.get(agent.currentSprintName);
      if (sprint) {
        const duration = formatAge(sprint.startedAt).replace(' ago', '');
        await sendThreadMessage(
          agent.matrixToken,
          roomId,
          sprint.threadRootId,
          `🏁 **Sprint Ended**\nDuration: ${duration}\nMessages: ${sprint.messageCount}`
        );
        agent.activeSprints.delete(agent.currentSprintName);
      }

      const endedName = agent.currentSprintName;
      agent.currentSprintName = null;
      return `Sprint "${endedName}" ended.`;
    }

    if (subCmd === 'list') {
      if (agent.activeSprints.size === 0) return 'No active sprints.';

      let output = '**Active Sprints:**\n';
      for (const [name, sprint] of agent.activeSprints) {
        const active = name === agent.currentSprintName ? ' (current)' : '';
        output += `- ${name}${active}: ${sprint.messageCount} msgs, started ${formatAge(sprint.startedAt)}\n`;
      }
      return output;
    }

    return 'Usage: /sprint start <name> | /sprint end | /sprint list';
  }

  // Checkpoint command
  if (cmd === '/checkpoint') {
    saveCheckpoint(agent);
    return `Checkpoint saved (${agent.recentMessages.length} messages buffered).`;
  }

  // Not a recognized command
  return null;
}

function findApprovalByPrefix(agent: AgentSession, prefix: string): PendingApproval | null {
  for (const [id, approval] of agent.pendingApprovals) {
    if (id.startsWith(prefix) || id.slice(0, 8) === prefix) {
      return approval;
    }
  }
  return null;
}

// ============================================================================
// Message Handling
// ============================================================================

function formatResponse(
  agent: AgentSession,
  result: string,
  assistantMessage: ClaudeAssistantResponse | null,
  resultResponse: ClaudeResultResponse
): string {
  if (!agent.verboseMode) {
    return result;
  }

  let output = result;

  // Add tool use summaries if present
  if (assistantMessage?.message.content) {
    const toolUses = assistantMessage.message.content.filter(c => c.type === 'tool_use');
    if (toolUses.length > 0) {
      output += '\n\n---\nTools used:';
      for (const tool of toolUses) {
        output += `\n- ${tool.name}`;
      }
    }
  }

  // Add token/cost footer
  if (resultResponse.usage || resultResponse.total_cost_usd !== undefined) {
    const tokens = resultResponse.usage?.output_tokens || 0;
    const cost = resultResponse.total_cost_usd?.toFixed(4) || '0.0000';
    output += `\n\n[${tokens} tokens | $${cost}]`;
  }

  return output;
}

async function handleMessage(
  agent: AgentSession,
  event: MatrixEvent,
  roomId: string
): Promise<void> {
  const body = event.content.body;
  if (!body) return;

  // Check authorization first
  if (!isAuthorized(event.sender)) {
    return;
  }

  // Check if this is a thread reply to a pending conversational approval
  const threadRootId = event.content['m.relates_to']?.event_id;
  if (event.content['m.relates_to']?.rel_type === 'm.thread' && threadRootId) {
    const pending = agent.pendingConversationalApproval;
    if (pending && pending.threadRootId === threadRootId) {
      // This is a reply to our pending approval thread
      const lowerBody = body.toLowerCase().trim();
      const isApproval = ['yes', 'y', 'approve', 'ok', 'go ahead', 'proceed'].some(w => lowerBody.includes(w));
      const isDenial = ['no', 'n', 'deny', 'cancel', 'stop', 'don\'t'].some(w => lowerBody.includes(w));

      if (isApproval || isDenial) {
        log(`[${agent.name}] Thread reply: ${isApproval ? 'approved' : 'denied'}`);
        await handleConversationalApprovalResponse(agent, isApproval);
        return;
      }
    }
    // Other thread messages - skip normal processing
    return;
  }

  const room = config.rooms[roomId];
  const formattedBody = event.content.formatted_body;

  // Check if @mention required (non-default agents in shared rooms need @mention)
  if (requiresMention(roomId, body, formattedBody, agent.matrixUserId, agent.name)) {
    return;
  }

  log(`[${room?.name || roomId}] ${event.sender}: ${body.slice(0, 60)}${body.length > 60 ? '...' : ''}`);

  // Track sprint message count
  if (agent.currentSprintName) {
    const sprint = agent.activeSprints.get(agent.currentSprintName);
    if (sprint) {
      sprint.messageCount++;
    }
  }

  try {
    // Send typing indicator
    await sendTyping(agent.matrixToken, roomId, agent.matrixUserId, true);

    let response: string;

    // Check for built-in commands
    if (body.startsWith('/')) {
      const cmdResponse = await handleCommand(agent, roomId, body);
      if (cmdResponse) {
        response = cmdResponse;
      } else {
        // Unknown command, pass to Claude
        const { result, assistantMessage, resultResponse } = await sendToClaudeSession(agent, body, roomId);
        response = formatResponse(agent, result, assistantMessage, resultResponse);
      }
    } else {
      // Regular message - pass to Claude
      const { result, assistantMessage, resultResponse } = await sendToClaudeSession(agent, body, roomId);
      response = formatResponse(agent, result, assistantMessage, resultResponse);
    }

    // Truncate if needed
    response = truncateResponse(response);

    // Check if Claude is asking for permission conversationally
    if (isPermissionRequest(response)) {
      log(`[${agent.name}] Detected permission request, creating approval thread`);
      const threadRootId = await createConversationalApprovalThread(agent, roomId, response);
      if (threadRootId) {
        agent.pendingConversationalApproval = {
          threadRootId,
          roomId,
          originalResponse: response,
          timestamp: Date.now(),
        };
        log(`[${room?.name || roomId}] Created approval thread: ${threadRootId}`);
        // Don't send the response as a regular message - it's already in the thread
        return;
      }
    }

    // Send response (in sprint thread if active)
    if (agent.currentSprintName) {
      const sprint = agent.activeSprints.get(agent.currentSprintName);
      if (sprint) {
        await sendThreadMessage(agent.matrixToken, roomId, sprint.threadRootId, response);
      } else {
        await sendMessage(agent.matrixToken, roomId, response);
      }
    } else {
      await sendMessage(agent.matrixToken, roomId, response);
    }

    log(`[${room?.name || roomId}] Responded: ${response.slice(0, 60)}${response.length > 60 ? '...' : ''}`);

    // Track messages for checkpointing
    const now = Date.now();
    agent.recentMessages.push(
      { role: 'user', content: body, roomId, timestamp: now },
      { role: 'assistant', content: response, roomId, timestamp: now },
    );
    // Keep buffer bounded
    if (agent.recentMessages.length > MAX_RECENT_MESSAGES) {
      agent.recentMessages = agent.recentMessages.slice(-MAX_RECENT_MESSAGES);
    }

    // Extract observations asynchronously (fire-and-forget)
    extractObservations(agent, body, response, roomId).catch(err => {
      logError(`[${agent.name}] Observation extraction failed`, err);
    });

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    const response = `Error: ${errorMsg.slice(0, 200)}`;
    await sendMessage(agent.matrixToken, roomId, response);
    logError(`[${agent.name}] Message handling failed`, err);
  } finally {
    await sendTyping(agent.matrixToken, roomId, agent.matrixUserId, false);
  }
}

// ============================================================================
// Hook-Based Approval Polling
// ============================================================================

interface HookRequest {
  request_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  session_id: string;
  timestamp: string;
}

// Poll the approval directory for new .request files from the PermissionRequest hook
async function pollHookApprovals(): Promise<void> {
  try {
    if (!existsSync(APPROVAL_DIR)) return;

    const files = readdirSync(APPROVAL_DIR).filter(f => f.endsWith('.request'));
    for (const file of files) {
      const requestId = file.replace('.request', '');

      // Skip if we've already created a thread for this request
      if (hookApprovals.has(requestId)) continue;

      try {
        const content = readFileSync(`${APPROVAL_DIR}/${file}`, 'utf-8');
        const request = JSON.parse(content) as HookRequest;

        log(`Hook approval request: ${request.tool_name} (${requestId.slice(0, 16)}...)`);

        // Find the agent by matching session_id
        let targetAgent: AgentSession | null = null;
        for (const agent of agents.values()) {
          if (agent.claudeSessionId === request.session_id) {
            targetAgent = agent;
            break;
          }
        }

        // Fallback: use first agent
        if (!targetAgent) {
          targetAgent = agents.values().next().value as AgentSession | undefined ?? null;
        }

        if (!targetAgent) {
          log(`No agent found for hook approval, denying`);
          writeFileSync(`${APPROVAL_DIR}/${requestId}.response`, 'deny');
          continue;
        }

        // Find the room this agent is currently working in
        const roomId = targetAgent.currentRoomId || getAgentDefaultRoom(targetAgent);
        if (!roomId) {
          log(`No room context for hook approval, denying`);
          writeFileSync(`${APPROVAL_DIR}/${requestId}.response`, 'deny');
          continue;
        }

        // Create approval thread in Matrix
        const inputPreview = formatToolInput(request.tool_input);
        const rootBody = `🔐 **Permission Request** (${targetAgent.name})\nTool: \`${request.tool_name}\`\n\`\`\`\n${inputPreview}\n\`\`\`\nReact ✅ to approve or ❌ to deny`;
        const rootEvent = await sendMessage(targetAgent.matrixToken, roomId, rootBody);

        if (rootEvent) {
          hookApprovals.set(requestId, {
            threadRootId: rootEvent.event_id,
            roomId,
            agentName: targetAgent.name,
            toolName: request.tool_name,
            timestamp: Date.now(),
          });
          log(`Created hook approval thread for ${request.tool_name}: ${rootEvent.event_id}`);
        } else {
          // Failed to create thread, deny
          writeFileSync(`${APPROVAL_DIR}/${requestId}.response`, 'deny');
        }
      } catch (err) {
        logError(`Failed to process hook request ${file}`, err);
        // Write deny response so the hook doesn't hang
        try { writeFileSync(`${APPROVAL_DIR}/${requestId}.response`, 'deny'); } catch { /* ignore */ }
      }
    }
  } catch (err) {
    // Don't log frequently - directory may not exist
    if ((err as NodeJS.ErrnoException).code !== 'ENOENT') {
      logError('Hook approval poll error', err);
    }
  }
}

// Handle reaction to a hook-based approval thread
function handleHookApprovalReaction(event: MatrixReactionEvent): void {
  const relatesTo = event.content['m.relates_to'];
  const targetEventId = relatesTo.event_id;
  const key = relatesTo.key;

  // Only allow approval owner
  if (event.sender !== config.settings.approval_owner) return;

  // Find the hook approval matching this event
  for (const [requestId, approval] of hookApprovals) {
    if (approval.threadRootId === targetEventId) {
      const responseFile = `${APPROVAL_DIR}/${requestId}.response`;

      if (key === '✅' || key === '👍') {
        log(`Hook approval granted: ${approval.toolName} (${requestId.slice(0, 16)})`);
        writeFileSync(responseFile, 'allow');
        hookApprovals.delete(requestId);
      } else if (key === '❌' || key === '👎') {
        log(`Hook approval denied: ${approval.toolName} (${requestId.slice(0, 16)})`);
        writeFileSync(responseFile, 'deny');
        hookApprovals.delete(requestId);
      }
      break;
    }
  }
}

// Clean up stale hook approvals (older than 10 minutes)
function cleanupStaleHookApprovals(): void {
  const now = Date.now();
  for (const [requestId, approval] of hookApprovals) {
    if (now - approval.timestamp > 600000) {
      log(`Cleaning up stale hook approval: ${requestId.slice(0, 16)}`);
      try { writeFileSync(`${APPROVAL_DIR}/${requestId}.response`, 'deny'); } catch { /* ignore */ }
      hookApprovals.delete(requestId);
    }
  }
}

// ============================================================================
// Token Refresh
// ============================================================================

async function refreshAgentToken(agent: AgentSession): Promise<void> {
  if (!tokenManager) {
    logError(`[${agent.name}] Token manager not initialized`);
    return;
  }

  if (tokenManager.isRefreshInProgress(agent.name)) {
    log(`[${agent.name}] Token refresh already in progress, skipping`);
    return;
  }

  try {
    log(`[${agent.name}] Attempting token refresh...`);
    const newToken = await tokenManager.refreshToken(agent.name, agent.config.token_file);

    // Update in-memory token
    agent.matrixToken = newToken;

    // Update token health
    if (agent.tokenHealth) {
      agent.tokenHealth.lastValidated = Date.now();
      agent.tokenHealth.consecutiveFailures = 0;
      agent.tokenHealth.needsRefresh = false;
    }

    log(`[${agent.name}] Token refreshed successfully`);
  } catch (err) {
    logError(`[${agent.name}] Token refresh failed`, err);
    throw err;
  }
}

async function matrixSyncWithRetry(agent: AgentSession): Promise<SyncResponse> {
  try {
    const sync = await matrixSync(agent.matrixToken, agent.syncToken);

    // Record success
    if (tokenManager) {
      tokenManager.recordSuccess(agent.name);
    }

    return sync;
  } catch (err) {
    const error = err as Error & { status?: number };

    if (error.status === 401) {
      log(`[${agent.name}] 401 authentication error, attempting token refresh...`);

      if (tokenManager) {
        tokenManager.recordFailure(agent.name);
      }

      // Attempt refresh
      await refreshAgentToken(agent);

      // Retry sync with new token
      const sync = await matrixSync(agent.matrixToken, agent.syncToken);

      if (tokenManager) {
        tokenManager.recordSuccess(agent.name);
      }

      return sync;
    }

    throw err;
  }
}

// ============================================================================
// Agent Polling
// ============================================================================

async function pollAgent(agent: AgentSession): Promise<void> {
  try {
    // Periodic token validation (every 5 minutes)
    if (tokenManager && tokenManager.needsValidation(agent.name)) {
      const baseUrl = getMatrixBaseUrl();
      const isValid = await tokenManager.validateToken(agent.matrixToken, baseUrl);

      if (!isValid) {
        log(`[${agent.name}] Token validation failed, refreshing...`);
        await refreshAgentToken(agent);
      } else {
        tokenManager.recordSuccess(agent.name);
      }
    }

    const sync = await matrixSyncWithRetry(agent);
    agent.syncToken = sync.next_batch;

    if (!sync.rooms?.join) return;

    const joinedRooms = sync.rooms!.join!;
    const joinedRoomIds = Object.keys(joinedRooms);
    const roomsWithEvents = joinedRoomIds.filter(
      rid => (joinedRooms[rid].timeline?.events?.length || 0) > 0
    );
    if (roomsWithEvents.length > 0) {
      log(`[${agent.name}] Sync: ${roomsWithEvents.length} rooms with events`);
    }

    for (const [roomId, roomData] of Object.entries(sync.rooms.join)) {
      // Only process rooms assigned to this agent
      if (!agent.rooms.has(roomId)) continue;

      const events = roomData.timeline?.events || [];

      // Handle messages
      for (const event of events) {
        // Debug: log all events we see
        if (events.length > 0 && event === events[0]) {
          log(`[${agent.name}] Room ${roomId.slice(0, 12)}: ${events.length} events, types: ${events.map((e: any) => e.type).join(', ')}`);
        }
        if (
          event.type === 'm.room.message' &&
          event.content?.msgtype === 'm.text' &&
          event.sender !== agent.matrixUserId
        ) {
          log(`[${agent.name}] Message from ${event.sender} in ${roomId.slice(0, 12)}: "${(event.content.body || '').slice(0, 80)}"`);
          await handleMessage(agent, event, roomId);
        }
      }

      // Handle reactions (for approvals - both Claude session and hook-based)
      const reactions = extractReactions(sync, roomId);
      for (const reaction of reactions) {
        await handleReactionEvent(agent, roomId, reaction);
        // Also check for hook-based approval reactions
        handleHookApprovalReaction(reaction);
      }
    }
  } catch (err) {
    logError(`[${agent.name}] Sync failed`, err);
  }
}

// ============================================================================
// Initialization
// ============================================================================

async function initializeAgent(name: string, agentConfig: AgentConfig): Promise<AgentSession> {
  const token = getToken(agentConfig.token_file);
  const userId = await getMatrixUserId(token);

  log(`Initialized agent ${name} as ${userId}`);

  // Initial sync to get token
  const sync = await matrixSync(token);

  // Determine which rooms this agent handles
  // Agent gets a room if: default_agent matches, default_agent is null, or agent is in agents array
  const rooms = new Set<string>();
  for (const [roomId, room] of Object.entries(config.rooms)) {
    if (room.default_agent === name || room.default_agent === null) {
      rooms.add(roomId);
    } else if (room.agents?.includes(name)) {
      rooms.add(roomId);
    }
  }

  const agent: AgentSession = {
    name,
    config: agentConfig,
    matrixToken: token,
    matrixUserId: userId,
    syncToken: sync.next_batch,

    claudeProcess: null,
    claudeStdin: null,
    claudeReader: null,
    claudeReady: false,
    claudeSessionId: null,

    currentRequestResolver: null,
    currentRequestRejecter: null,
    currentAssistantMessage: null,
    currentRoomId: null,

    rooms,
    pendingApprovals: new Map(),
    lastApprovalContext: null,
    pendingConversationalApproval: null,
    activeSprints: new Map(),
    currentSprintName: null,
    verboseMode: false,
    tokenHealth: null,
    recentMessages: [],
  };

  // Initialize token health tracking
  if (tokenManager) {
    tokenManager.initializeAgent(name, agentConfig.token_file);
    agent.tokenHealth = tokenManager.getHealth(name) || null;
  }

  log(`[${name}] Assigned ${rooms.size} rooms`);

  return agent;
}

// ============================================================================
// Shutdown
// ============================================================================

function handleShutdown(signal: string): void {
  if (shuttingDown) return;
  shuttingDown = true;

  log(`Received ${signal}, shutting down...`);

  // Save checkpoints for all agents before killing processes
  for (const agent of agents.values()) {
    saveCheckpoint(agent);
  }

  // Kill all Claude processes
  for (const agent of agents.values()) {
    if (agent.claudeProcess) {
      agent.claudeProcess.kill('SIGTERM');
    }
  }

  // Give some time for cleanup
  setTimeout(() => {
    log('Shutdown complete');
    process.exit(0);
  }, 2000);
}

// ============================================================================
// Main
// ============================================================================

async function main(): Promise<void> {
  console.log('');
  console.log('='.repeat(60));
  console.log('  IG-88 Matrix Coordinator');
  console.log('  Multi-Agent | Persistent Sessions | Approval Passthrough');
  console.log('='.repeat(60));
  console.log('');

  // Register shutdown handlers
  process.on('SIGTERM', () => handleShutdown('SIGTERM'));
  process.on('SIGINT', () => handleShutdown('SIGINT'));
  process.on('SIGHUP', reloadConfig);

  // Load configuration
  config = loadConfig();

  // Initialize token manager
  const pantalaimonUrl = config.settings.pantalaimon_url || 'http://localhost:41200';
  const credentialSource = config.settings.credential_source || 'systemd';
  const credentialPath = config.settings.credential_path;

  tokenManager = new TokenManager({
    pantalaimonUrl,
    credentialSource,
    credentialPath,
  });

  log(`Token manager initialized (credential source: ${credentialSource})`);

  // Watch config file for changes
  watchFile(CONFIG_PATH, { interval: 5000 }, () => {
    log('Config file changed, reloading...');
    reloadConfig();
  });

  const baseUrl = getMatrixBaseUrl();
  log(`Matrix API: ${baseUrl}`);
  log(`Max Claude sessions: ${config.settings.max_claude_sessions}`);
  log(`Approval owner: ${config.settings.approval_owner}`);
  log(`Send SIGHUP to reload configuration`);
  console.log('');

  // Initialize all agents
  log('Initializing agents...');
  for (const [name, agentConfig] of Object.entries(config.agents)) {
    try {
      const agent = await initializeAgent(name, agentConfig);
      agents.set(name, agent);

      // Start Claude session for this agent
      startClaudeSession(agent);
    } catch (err) {
      logError(`Failed to initialize agent ${name}`, err);
    }
  }

  // Wait for Claude sessions to initialize
  await sleep(1000);

  log('');
  log('Coordinator online. Listening for messages...');
  console.log('');

  // Send startup notification to first room of first agent
  const firstAgent = agents.values().next().value as AgentSession | undefined;
  if (firstAgent && firstAgent.rooms.size > 0) {
    const firstRoom = firstAgent.rooms.values().next().value as string | undefined;
    if (firstRoom) {
      await sendMessage(
        firstAgent.matrixToken,
        firstRoom,
        `IG-88 Coordinator online.\n${agents.size} agents active. Type /help for commands.`
      );
    }
  }

  // Ensure approval directory exists
  try {
    if (!existsSync(APPROVAL_DIR)) {
      mkdirSync(APPROVAL_DIR, { recursive: true });
    }
  } catch { /* ignore */ }

  let cleanupCounter = 0;

  // Main polling loop
  while (!shuttingDown) {
    // Poll all agents in parallel + hook approvals
    await Promise.all([
      ...([...agents.values()].map(agent => pollAgent(agent))),
      pollHookApprovals(),
    ]);

    // Periodic cleanup of stale hook approvals (every ~60 seconds)
    cleanupCounter++;
    if (cleanupCounter >= 20) {
      cleanupStaleHookApprovals();
      cleanupCounter = 0;
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

// Entry point
main().catch((err) => {
  logError('Fatal error', err);
  process.exit(1);
});
