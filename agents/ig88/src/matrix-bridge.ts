// Matrix Bridge - Bidirectional Claude Code conduit
// Uses persistent Claude session with streaming JSON mode for conversation continuity
// Supports permission passthrough via Matrix threads and reactions

import { spawn, ChildProcess } from 'child_process';
import { createInterface, Interface } from 'readline';
import {
  loadConfig,
  getToken,
  sendMessage,
  sendTyping,
  sendMessageWithId,
  sendThreadMessage,
  extractReactions,
  formatToolInput,
  formatAge,
  type MatrixConfig,
  type MatrixReactionEvent,
  type SyncResponse,
} from './matrix.js';
import { runScan, formatScanResult } from './scanner.js';
import type { PendingApproval, Sprint } from './types.js';

// Local MatrixEvent type for message handling
interface MatrixMessageEvent {
  type: string;
  sender: string;
  content: {
    msgtype?: string;
    body?: string;
    'm.relates_to'?: {
      rel_type?: string;
      event_id?: string;
    };
  };
  event_id: string;
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

// Permission request from Claude (tool approval)
interface ClaudeInputRequest {
  type: 'input_request';
  request_id: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  // Can be for user questions or permission requests
}

type ClaudeResponse = ClaudeInitResponse | ClaudeAssistantResponse | ClaudeResultResponse | ClaudeInputRequest;

// Configuration
const POLL_INTERVAL_MS = 3000; // 3 seconds
const CLAUDE_TIMEOUT_MS = 120000; // 2 minutes
const MAX_RESPONSE_LENGTH = 4000; // Matrix message limit
const CLAUDE_RESTART_DELAY_MS = 5000; // 5 seconds before restart

// Claude model configuration - Haiku preferred, never Opus
const CLAUDE_MODEL = 'haiku';
const CLAUDE_FALLBACK_MODEL = 'sonnet';

// Approval configuration
const APPROVAL_TIMEOUT_MS = 600000; // 10 minutes
const APPROVAL_OWNER = '@chrislyons:matrix.org'; // Only user who can approve
// SECURITY: Restricted patterns - no echo *, cat restricted to safe paths (BKX018)
const AUTO_APPROVE_PATTERNS = [
  'ls *', 'cat ~/dev/*', 'cat ~/projects/*/docs/*', 'cat ~/projects/*/README*',
  'grep *', 'git status', 'git diff', 'git log',
  'head *', 'tail *', 'wc *', 'file *', 'pwd',
];
const ALWAYS_REQUIRE_APPROVAL = [
  'rm *', 'sudo *', 'ssh *', 'mv *', 'cp *', 'sed *',
  'awk *', 'chmod *', 'chown *', 'curl *', 'wget *',
  'python *', 'node *', 'bash *', 'sh *',
];
// Shell metacharacters that indicate command chaining, redirection, or subshells (BKX018)
const SHELL_METACHAR_PATTERN = /[|><;&`$()]/;

let syncToken: string | null = null;
let botUserId: string | null = null;
let currentConfig: MatrixConfig | null = null;

// Pending approvals state
const pendingApprovals = new Map<string, PendingApproval>();

// Active sprints state
const activeSprints = new Map<string, Sprint>();
let currentSprintName: string | null = null;

// Persistent Claude session state
let claudeProcess: ChildProcess | null = null;
let claudeStdin: NodeJS.WritableStream | null = null;
let claudeReader: Interface | null = null;
let claudeSessionReady = false;
let currentRequestResolver: ((response: ClaudeResultResponse) => void) | null = null;
let currentRequestRejecter: ((error: Error) => void) | null = null;
let currentAssistantMessage: ClaudeAssistantResponse | null = null;

// Verbose mode state
let verboseMode = false;

// Logging helper
function log(message: string): void {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

function logError(message: string, err?: unknown): void {
  console.error(`[${new Date().toISOString()}] ERROR: ${message}`, err || '');
}

// Sleep helper
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Start persistent Claude session
function startClaudeSession(): void {
  log('Starting Claude session...');

  claudeProcess = spawn('claude', [
    '--input-format', 'stream-json',
    '--output-format', 'stream-json',
    '--permission-mode', 'delegate',
    '--verbose',
    '--model', CLAUDE_MODEL,
    '--fallback-model', CLAUDE_FALLBACK_MODEL,
  ], {
    cwd: process.env.HOME,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  claudeStdin = claudeProcess.stdin!;

  // Read streaming JSON responses line by line
  claudeReader = createInterface({ input: claudeProcess.stdout! });
  claudeReader.on('line', (line) => {
    if (!line.trim()) return;

    try {
      const response = JSON.parse(line) as ClaudeResponse;
      handleClaudeResponse(response);
    } catch (e) {
      // Non-JSON output, log it
      log(`Claude non-JSON: ${line.slice(0, 100)}`);
    }
  });

  // Log stderr for debugging
  claudeProcess.stderr?.on('data', (data: Buffer) => {
    const text = data.toString().trim();
    if (text) {
      log(`Claude stderr: ${text.slice(0, 200)}`);
    }
  });

  claudeProcess.on('exit', (code, signal) => {
    log(`Claude process exited with code ${code}, signal ${signal}`);
    claudeSessionReady = false;
    claudeProcess = null;
    claudeStdin = null;
    claudeReader = null;

    // Reject any pending request
    if (currentRequestRejecter) {
      currentRequestRejecter(new Error(`Claude process exited unexpectedly (code ${code})`));
      currentRequestResolver = null;
      currentRequestRejecter = null;
    }

    // Restart if unexpected exit (not from graceful shutdown)
    if (code !== 0 && !shuttingDown) {
      log(`Restarting Claude session in ${CLAUDE_RESTART_DELAY_MS}ms...`);
      setTimeout(startClaudeSession, CLAUDE_RESTART_DELAY_MS);
    }
  });

  claudeProcess.on('error', (err) => {
    logError('Claude process error', err);
    claudeSessionReady = false;
  });

  claudeSessionReady = true;
  log('Claude session started');
}

// Handle Claude streaming JSON response
function handleClaudeResponse(response: ClaudeResponse): void {
  switch (response.type) {
    case 'system':
      if (response.subtype === 'init') {
        log(`Claude session initialized: model=${response.model}, session_id=${response.session_id}`);
      }
      break;

    case 'assistant':
      // Store assistant message for verbose output
      currentAssistantMessage = response;
      break;

    case 'result':
      // Resolve the pending request
      if (currentRequestResolver) {
        currentRequestResolver(response);
        currentRequestResolver = null;
        currentRequestRejecter = null;
      }
      break;

    case 'input_request':
      // Permission or user input request
      handleInputRequest(response);
      break;
  }
}

// Handle input/permission request from Claude
async function handleInputRequest(request: ClaudeInputRequest): Promise<void> {
  const { request_id, tool_name, tool_input } = request;

  if (!tool_name || !tool_input || !currentConfig) {
    log(`Input request without tool info: ${request_id}`);
    // For non-tool input requests, we might need different handling
    return;
  }

  log(`Permission request: ${tool_name} (${request_id})`);

  // Check for auto-approve patterns
  if (shouldAutoApprove(tool_name, tool_input)) {
    log(`Auto-approving: ${tool_name}`);
    sendApprovalToClaudeSession(request_id, 'allow');
    return;
  }

  // Create approval thread in Matrix
  const approval = await createApprovalThread(request_id, tool_name, tool_input);
  if (approval) {
    pendingApprovals.set(request_id, approval);

    // Set timeout for re-prompting
    setTimeout(() => {
      checkApprovalTimeout(request_id);
    }, APPROVAL_TIMEOUT_MS);
  } else {
    // Failed to create thread, deny by default
    log(`Failed to create approval thread, denying ${tool_name}`);
    sendApprovalToClaudeSession(request_id, 'deny', 'Failed to create approval thread');
  }
}

// Check if command matches auto-approve patterns
function shouldAutoApprove(toolName: string, input: Record<string, unknown>): boolean {
  if (toolName !== 'Bash') return false;

  const command = input.command as string | undefined;
  if (!command) return false;

  // Reject any command containing shell metacharacters (pipes, redirects, chaining, subshells)
  if (SHELL_METACHAR_PATTERN.test(command)) {
    return false;
  }

  // Check against always-require patterns first
  for (const pattern of ALWAYS_REQUIRE_APPROVAL) {
    if (matchesPattern(command, pattern)) {
      return false;
    }
  }

  // Check auto-approve patterns
  for (const pattern of AUTO_APPROVE_PATTERNS) {
    if (matchesPattern(command, pattern)) {
      return true;
    }
  }

  return false;
}

// Glob pattern matching for commands (anchored at both start and end)
function matchesPattern(command: string, pattern: string): boolean {
  const regexStr = pattern
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\\\*/g, '.*');
  const regex = new RegExp(`^${regexStr}$`, 'i');
  return regex.test(command);
}

// Create approval thread in Matrix
async function createApprovalThread(
  requestId: string,
  toolName: string,
  toolInput: Record<string, unknown>
): Promise<PendingApproval | null> {
  if (!currentConfig) return null;

  const inputPreview = formatToolInput(toolInput);

  // Send root message
  const rootBody = `🔐 **Permission Request**\nTool: \`${toolName}\`\n\`\`\`\n${inputPreview}\n\`\`\``;
  const rootEvent = await sendMessageWithId(currentConfig, rootBody);

  if (!rootEvent) return null;

  // Send thread prompt
  const threadBody = `React with ✅ to approve or ❌ to deny\nRequest ID: \`${requestId.slice(0, 8)}\``;
  const threadEvent = await sendThreadMessage(currentConfig, rootEvent.event_id, threadBody);

  if (!threadEvent) return null;

  return {
    requestId,
    tool: toolName,
    input: toolInput,
    matrixEventId: threadEvent.event_id,
    threadRootId: rootEvent.event_id,
    sender: APPROVAL_OWNER,
    timestamp: Date.now(),
  };
}

// Check if approval has timed out and re-prompt
function checkApprovalTimeout(requestId: string): void {
  const approval = pendingApprovals.get(requestId);
  if (!approval || !currentConfig) return;

  const age = Date.now() - approval.timestamp;
  if (age >= APPROVAL_TIMEOUT_MS) {
    log(`Approval timeout for ${requestId}, re-prompting...`);

    // Send reminder in thread
    sendThreadMessage(
      currentConfig,
      approval.threadRootId,
      `⏰ Approval still pending. React ✅ or ❌ to continue.`
    );

    // Update timestamp and set another timeout
    approval.timestamp = Date.now();
    pendingApprovals.set(requestId, approval);

    setTimeout(() => {
      checkApprovalTimeout(requestId);
    }, APPROVAL_TIMEOUT_MS);
  }
}

// Send approval/denial response to Claude session
function sendApprovalToClaudeSession(
  requestId: string,
  decision: 'allow' | 'deny',
  message?: string
): void {
  if (!claudeStdin || !claudeSessionReady) {
    logError('Cannot send approval - Claude session not ready');
    return;
  }

  const response = JSON.stringify({
    type: 'user',
    message: {
      role: 'user',
      content: decision === 'allow' ? 'yes' : `no${message ? `: ${message}` : ''}`,
    },
  });

  claudeStdin.write(response + '\n');
  log(`Sent ${decision} for request ${requestId.slice(0, 8)}`);
}

// Handle reaction event from Matrix
function handleReactionEvent(event: MatrixReactionEvent): void {
  const relatesTo = event.content['m.relates_to'];
  const targetEventId = relatesTo.event_id;
  const key = relatesTo.key; // emoji

  // Only allow approval owner to react
  if (event.sender !== APPROVAL_OWNER) {
    log(`Ignoring reaction from ${event.sender} (not owner)`);
    return;
  }

  // Find pending approval for this event
  for (const [requestId, approval] of pendingApprovals) {
    if (approval.threadRootId === targetEventId || approval.matrixEventId === targetEventId) {
      if (key === '✅' || key === '👍') {
        log(`Approved: ${approval.tool} (${requestId.slice(0, 8)})`);
        sendApprovalToClaudeSession(requestId, 'allow');
        pendingApprovals.delete(requestId);

        // Confirm in thread
        if (currentConfig) {
          sendThreadMessage(currentConfig, approval.threadRootId, '✅ Approved');
        }
      } else if (key === '❌' || key === '👎') {
        log(`Denied: ${approval.tool} (${requestId.slice(0, 8)})`);
        sendApprovalToClaudeSession(requestId, 'deny', 'User denied');
        pendingApprovals.delete(requestId);

        // Confirm in thread
        if (currentConfig) {
          sendThreadMessage(currentConfig, approval.threadRootId, '❌ Denied');
        }
      }
      break;
    }
  }
}

// Send message to persistent Claude session
async function sendToClaudeSession(message: string): Promise<{ result: string; assistantMessage: ClaudeAssistantResponse | null; resultResponse: ClaudeResultResponse }> {
  if (!claudeStdin || !claudeSessionReady) {
    throw new Error('Claude session not ready');
  }

  // Clear previous assistant message
  currentAssistantMessage = null;

  // Create the JSON input
  const input = JSON.stringify({
    type: 'user',
    message: { role: 'user', content: message },
  });

  // Write to stdin
  claudeStdin.write(input + '\n');

  // Wait for result response
  return new Promise((resolve, reject) => {
    currentRequestResolver = (resultResponse: ClaudeResultResponse) => {
      if (resultResponse.subtype === 'error') {
        reject(new Error(resultResponse.error || 'Claude returned an error'));
      } else {
        resolve({
          result: resultResponse.result || '',
          assistantMessage: currentAssistantMessage,
          resultResponse,
        });
      }
    };
    currentRequestRejecter = reject;

    // Timeout
    setTimeout(() => {
      if (currentRequestRejecter === reject) {
        currentRequestResolver = null;
        currentRequestRejecter = null;
        reject(new Error('Claude response timeout'));
      }
    }, CLAUDE_TIMEOUT_MS);
  });
}

// Format response with verbose info if enabled
function formatResponse(result: string, assistantMessage: ClaudeAssistantResponse | null, resultResponse: ClaudeResultResponse): string {
  if (!verboseMode) {
    return result;
  }

  // Build verbose output
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

// Get bot's user ID from whoami endpoint
async function getBotUserId(token: string, config: MatrixConfig): Promise<string> {
  const url = `${config.homeserver}/_matrix/client/r0/account/whoami`;
  const response = await fetch(url, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Failed to get user ID: ${response.status}`);
  }

  const data = await response.json() as { user_id: string };
  return data.user_id;
}

// Matrix sync API call
async function matrixSync(token: string, config: MatrixConfig): Promise<SyncResponse> {
  const params = new URLSearchParams({
    timeout: '30000',
  });

  if (syncToken) {
    params.set('since', syncToken);
  }

  const url = `${config.homeserver}/_matrix/client/r0/sync?${params}`;
  const response = await fetch(url, {
    headers: { 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error(`Sync failed: ${response.status}`);
  }

  return response.json() as Promise<SyncResponse>;
}

// Extract new messages from sync response
function extractMessages(sync: SyncResponse, roomId: string): MatrixMessageEvent[] {
  const room = sync.rooms?.join?.[roomId];
  if (!room?.timeline?.events) return [];

  return room.timeline.events.filter((e): e is MatrixMessageEvent =>
    e.type === 'm.room.message' &&
    e.content?.msgtype === 'm.text' &&
    e.sender !== botUserId // Ignore own messages
  );
}

// Handle built-in commands
async function handleCommand(command: string, config: MatrixConfig): Promise<string | null> {
  const cmd = command.toLowerCase().trim();
  const args = command.trim().split(/\s+/).slice(1);

  if (cmd === '/scan') {
    log('Running scan command...');
    const result = await runScan();
    return formatScanResult(result);
  }

  if (cmd === '/status' || cmd === '/session') {
    return `IG-88 Bridge Status
========================
Online: ${new Date().toISOString()}
Sync Token: ${syncToken ? 'Active' : 'None'}
Bot User: ${botUserId}
Room: ${config.roomId}
Claude Session: ${claudeSessionReady ? 'Active' : 'Inactive'}
Verbose Mode: ${verboseMode ? 'On' : 'Off'}
Pending Approvals: ${pendingApprovals.size}
Active Sprints: ${activeSprints.size}
Current Sprint: ${currentSprintName || 'None'}
========================`;
  }

  if (cmd === '/help') {
    return `IG-88 Bridge Commands
========================
**Core:**
/scan    - Run market scanner
/status  - Show bridge status
/verbose - Toggle verbose output

**Approvals:**
/pending           - Show pending approvals
/approve <id>      - Approve by request ID
/deny <id> [reason] - Deny by request ID

**Sprints:**
/sprint start <name> - Start a new sprint thread
/sprint end          - End current sprint
/sprint list         - Show active sprints

/help    - Show this help
========================`;
  }

  // Verbose mode commands
  if (cmd === '/verbose on') {
    verboseMode = true;
    return 'Verbose mode enabled. Responses will include tool summaries and token/cost info.';
  }

  if (cmd === '/verbose off') {
    verboseMode = false;
    return 'Verbose mode disabled.';
  }

  if (cmd === '/verbose') {
    return `Verbose mode is currently ${verboseMode ? 'ON' : 'OFF'}.\nUse /verbose on or /verbose off to change.`;
  }

  // Pending approvals command
  if (cmd === '/pending') {
    if (pendingApprovals.size === 0) {
      return 'No pending approvals.';
    }
    let output = '**Pending Approvals:**\n';
    for (const [id, approval] of pendingApprovals) {
      output += `- \`${id.slice(0, 8)}\`: ${approval.tool} (${formatAge(approval.timestamp)})\n`;
    }
    return output;
  }

  // Approve command
  if (cmd.startsWith('/approve ')) {
    const id = args[0];
    if (!id) return 'Usage: /approve <request_id>';

    const approval = findApprovalByPrefix(id);
    if (!approval) return `No pending approval matching: ${id}`;

    sendApprovalToClaudeSession(approval.requestId, 'allow');
    pendingApprovals.delete(approval.requestId);

    // Confirm in thread
    sendThreadMessage(config, approval.threadRootId, '✅ Approved via /approve');

    return `✅ Approved: ${approval.tool}`;
  }

  // Deny command
  if (cmd.startsWith('/deny ')) {
    const id = args[0];
    if (!id) return 'Usage: /deny <request_id> [reason]';

    const approval = findApprovalByPrefix(id);
    if (!approval) return `No pending approval matching: ${id}`;

    const reason = args.slice(1).join(' ') || 'User denied via command';
    sendApprovalToClaudeSession(approval.requestId, 'deny', reason);
    pendingApprovals.delete(approval.requestId);

    // Confirm in thread
    sendThreadMessage(config, approval.threadRootId, `❌ Denied: ${reason}`);

    return `❌ Denied: ${approval.tool}`;
  }

  // Sprint commands
  if (cmd.startsWith('/sprint ')) {
    const subCmd = args[0]?.toLowerCase();

    if (subCmd === 'start') {
      const name = args.slice(1).join(' ');
      if (!name) return 'Usage: /sprint start <name>';

      // Create sprint thread root
      const rootEvent = await sendMessageWithId(config, `🏃 **Sprint Started:** ${name}`);
      if (!rootEvent) return 'Failed to create sprint thread';

      const sprint: Sprint = {
        name,
        threadRootId: rootEvent.event_id,
        startedAt: Date.now(),
        messageCount: 0,
      };
      activeSprints.set(name, sprint);
      currentSprintName = name;

      return `Sprint "${name}" started. Messages will be tracked.`;
    }

    if (subCmd === 'end') {
      if (!currentSprintName) return 'No active sprint to end.';

      const sprint = activeSprints.get(currentSprintName);
      if (sprint) {
        const duration = formatAge(sprint.startedAt).replace(' ago', '');
        await sendThreadMessage(
          config,
          sprint.threadRootId,
          `🏁 **Sprint Ended**\nDuration: ${duration}\nMessages: ${sprint.messageCount}`
        );
        activeSprints.delete(currentSprintName);
      }

      const endedName = currentSprintName;
      currentSprintName = null;
      return `Sprint "${endedName}" ended.`;
    }

    if (subCmd === 'list') {
      if (activeSprints.size === 0) return 'No active sprints.';

      let output = '**Active Sprints:**\n';
      for (const [name, sprint] of activeSprints) {
        const active = name === currentSprintName ? ' (current)' : '';
        output += `- ${name}${active}: ${sprint.messageCount} msgs, started ${formatAge(sprint.startedAt)}\n`;
      }
      return output;
    }

    return 'Usage: /sprint start <name> | /sprint end | /sprint list';
  }

  // Tasks command - pass to Claude
  if (cmd === '/tasks') {
    try {
      const { result } = await sendToClaudeSession('Show me the current task list');
      return result;
    } catch (err) {
      return `Failed to get tasks: ${err instanceof Error ? err.message : String(err)}`;
    }
  }

  // Context command - pass to Claude
  if (cmd === '/context') {
    try {
      const { result } = await sendToClaudeSession('Show me the current context and session statistics');
      return result;
    } catch (err) {
      return `Failed to get context: ${err instanceof Error ? err.message : String(err)}`;
    }
  }

  // Not a command
  return null;
}

// Find approval by ID prefix
function findApprovalByPrefix(prefix: string): PendingApproval | null {
  for (const [id, approval] of pendingApprovals) {
    if (id.startsWith(prefix) || id.slice(0, 8) === prefix) {
      return approval;
    }
  }
  return null;
}

// Truncate long responses
function truncateResponse(response: string): string {
  if (response.length <= MAX_RESPONSE_LENGTH) {
    return response;
  }

  return response.slice(0, MAX_RESPONSE_LENGTH - 50) + '\n\n[...truncated]';
}

// Handle incoming message
async function handleMessage(event: MatrixMessageEvent, config: MatrixConfig): Promise<void> {
  const userMessage = event.content.body;
  if (!userMessage) return;

  // Skip thread messages (they're replies in approval threads)
  if (event.content['m.relates_to']?.rel_type === 'm.thread') {
    return;
  }

  log(`Received from ${event.sender}: ${userMessage.slice(0, 80)}${userMessage.length > 80 ? '...' : ''}`);

  // Track sprint message count
  if (currentSprintName) {
    const sprint = activeSprints.get(currentSprintName);
    if (sprint) {
      sprint.messageCount++;
    }
  }

  try {
    // Send typing indicator
    await sendTyping(config, true);

    let response: string;

    // Check for built-in commands
    if (userMessage.startsWith('/')) {
      const cmdResponse = await handleCommand(userMessage, config);
      if (cmdResponse) {
        response = cmdResponse;
      } else {
        // Unknown command, pass to Claude
        const { result, assistantMessage, resultResponse } = await sendToClaudeSession(userMessage);
        response = formatResponse(result, assistantMessage, resultResponse);
      }
    } else {
      // Regular message - pass to Claude Code via persistent session
      const { result, assistantMessage, resultResponse } = await sendToClaudeSession(userMessage);
      response = formatResponse(result, assistantMessage, resultResponse);
    }

    // Truncate if needed
    response = truncateResponse(response);

    // Send response (in sprint thread if active)
    if (currentSprintName) {
      const sprint = activeSprints.get(currentSprintName);
      if (sprint) {
        await sendThreadMessage(config, sprint.threadRootId, response);
      } else {
        await sendMessage(config, response);
      }
    } else {
      await sendMessage(config, response);
    }
    log(`Responded: ${response.slice(0, 80)}${response.length > 80 ? '...' : ''}`);

  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    const response = `Error: ${errorMsg.slice(0, 200)}`;
    await sendMessage(config, response);
    logError('Failed to process message', err);
  } finally {
    // Stop typing indicator
    await sendTyping(config, false);
  }
}

// Graceful shutdown state
let shuttingDown = false;

// Graceful shutdown handler
function handleShutdown(signal: string): void {
  if (shuttingDown) return;
  shuttingDown = true;

  log(`Received ${signal}, shutting down...`);

  // Kill Claude process gracefully
  if (claudeProcess) {
    claudeProcess.kill('SIGTERM');
  }

  // Give some time for cleanup
  setTimeout(() => {
    log('Shutdown complete');
    process.exit(0);
  }, 2000);
}

// Main loop
async function main(): Promise<void> {
  console.log('');
  console.log('='.repeat(50));
  console.log('  IG-88 Matrix Bridge (Persistent Session)');
  console.log('  Approval Passthrough Enabled');
  console.log('='.repeat(50));
  console.log('');

  // Register shutdown handlers
  process.on('SIGTERM', () => handleShutdown('SIGTERM'));
  process.on('SIGINT', () => handleShutdown('SIGINT'));

  // Load configuration
  const config = loadConfig();
  currentConfig = config; // Store for use in permission handlers
  const token = getToken(config.tokenFile);

  log(`Homeserver: ${config.homeserver}`);
  log(`Room ID: ${config.roomId}`);
  log(`Poll interval: ${POLL_INTERVAL_MS}ms`);
  log(`Claude model: ${CLAUDE_MODEL} (fallback: ${CLAUDE_FALLBACK_MODEL})`);
  log(`Approval owner: ${APPROVAL_OWNER}`);
  log(`Approval timeout: ${APPROVAL_TIMEOUT_MS / 1000}s`);

  // Start persistent Claude session
  startClaudeSession();

  // Wait a moment for Claude to initialize
  await sleep(1000);

  // Get bot user ID
  botUserId = await getBotUserId(token, config);
  log(`Bot user ID: ${botUserId}`);

  // Initial sync to get token (don't process messages from before startup)
  log('Performing initial sync...');
  const initial = await matrixSync(token, config);
  syncToken = initial.next_batch;
  log('Initial sync complete');
  log('Listening for messages and reactions...');
  console.log('');

  // Send startup notification
  await sendMessage(config, `IG-88 Bridge online (persistent session).\nApproval passthrough enabled. Type /help for commands.`);

  // Main polling loop
  while (!shuttingDown) {
    try {
      const sync = await matrixSync(token, config);
      syncToken = sync.next_batch;

      // Handle messages
      const messages = extractMessages(sync, config.roomId);
      for (const msg of messages) {
        await handleMessage(msg, config);
      }

      // Handle reactions for approval flow
      const reactions = extractReactions(sync, config.roomId);
      for (const reaction of reactions) {
        handleReactionEvent(reaction);
      }

    } catch (err) {
      logError('Sync error', err);
      await sleep(5000); // Back off on error
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

// Entry point
main().catch((err) => {
  logError('Fatal error', err);
  process.exit(1);
});

// ============================================================
// ROLLBACK: Original per-message invokeClaudeCode function
// Uncomment this and remove persistent session code if issues
// ============================================================
// async function invokeClaudeCode(message: string): Promise<string> {
//   return new Promise((resolve, reject) => {
//     const proc = spawn('claude', ['-p', message, '--output-format', 'text'], {
//       timeout: CLAUDE_TIMEOUT_MS,
//       cwd: process.env.HOME,
//       stdio: ['ignore', 'pipe', 'pipe'],
//       detached: false,
//     });
//
//     let stdout = '';
//     let stderr = '';
//
//     proc.stdout.on('data', (data: Buffer) => {
//       stdout += data.toString();
//     });
//
//     proc.stderr.on('data', (data: Buffer) => {
//       stderr += data.toString();
//     });
//
//     proc.on('close', (code) => {
//       if (code === 0) {
//         resolve(stdout.trim());
//       } else {
//         reject(new Error(stderr || `Claude exited with code ${code}`));
//       }
//     });
//
//     proc.on('error', (err) => {
//       reject(err);
//     });
//   });
// }
