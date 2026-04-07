// Matrix Alert Client for IG-88
// Simple HTTP client - no SDK needed

import { readFileSync, existsSync } from 'fs';
import type { ScanResult, TradeParams, PendingApproval } from './types.js';

// Matrix event types
export interface MatrixReactionEvent {
  type: 'm.reaction';
  sender: string;
  event_id: string;
  content: {
    'm.relates_to': {
      rel_type: 'm.annotation';
      event_id: string;
      key: string; // emoji
    };
  };
}

export interface SyncResponse {
  next_batch: string;
  rooms?: {
    join?: Record<string, {
      timeline?: {
        events?: MatrixEvent[];
      };
    }>;
  };
}

export interface MatrixEvent {
  type: string;
  sender: string;
  content: {
    msgtype?: string;
    body?: string;
    'm.relates_to'?: {
      rel_type?: string;
      event_id?: string;
      key?: string;
    };
  };
  event_id: string;
}

export interface MatrixConfig {
  homeserver: string;
  roomId: string;
  tokenFile: string;
}

// Load config from environment
export function loadConfig(): MatrixConfig {
  const homeserver = process.env.MATRIX_HOMESERVER || 'https://matrix.org';
  const roomId = process.env.MATRIX_ROOM_ID;
  const tokenFile = process.env.MATRIX_TOKEN_FILE || `${process.env.HOME}/.config/ig88/matrix_token`;

  if (!roomId) {
    throw new Error('MATRIX_ROOM_ID environment variable required');
  }

  return { homeserver, roomId, tokenFile };
}

// Read token from file
export function getToken(tokenFile: string): string {
  if (!existsSync(tokenFile)) {
    throw new Error(`Matrix token file not found: ${tokenFile}`);
  }
  return readFileSync(tokenFile, 'utf-8').trim();
}

// Send typing indicator to Matrix room
export async function sendTyping(
  config: MatrixConfig,
  typing: boolean,
  timeout = 30000
): Promise<boolean> {
  const token = getToken(config.tokenFile);
  const url = `${config.homeserver}/_matrix/client/r0/rooms/${encodeURIComponent(config.roomId)}/typing/${encodeURIComponent('@ig88:matrix.org')}`;

  try {
    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        typing,
        timeout: typing ? timeout : undefined,
      }),
    });

    return response.ok;
  } catch {
    return false;
  }
}

// Send a message to Matrix room
export async function sendMessage(
  config: MatrixConfig,
  body: string,
  formatted?: string
): Promise<boolean> {
  const token = getToken(config.tokenFile);
  const txnId = `ig88_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  const url = `${config.homeserver}/_matrix/client/r0/rooms/${encodeURIComponent(config.roomId)}/send/m.room.message/${txnId}`;

  const message: Record<string, string> = {
    msgtype: 'm.text',
    body,
  };

  // Add formatted HTML if provided
  if (formatted) {
    message.format = 'org.matrix.custom.html';
    message.formatted_body = formatted;
  }

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
      const error = await response.text();
      console.error(`Matrix API error ${response.status}: ${error}`);
      return false;
    }

    return true;
  } catch (err) {
    console.error('Matrix send failed:', err);
    return false;
  }
}

// Format trade alert for Matrix
export function formatTradeAlert(
  cycleId: string,
  candidate: { symbol: string; name: string; price: number },
  trade: TradeParams,
  reasoning: string
): { plain: string; html: string } {
  const rr = ((trade.takeProfit - trade.entry) / (trade.entry - trade.stopLoss)).toFixed(1);

  const plain = `
🚨 IG-88 TRADE SIGNAL
═══════════════════════
Cycle: ${cycleId}
Token: ${candidate.symbol} (${candidate.name})

📍 Entry: $${trade.entry.toFixed(6)}
🛑 Stop Loss: $${trade.stopLoss.toFixed(6)}
🎯 Take Profit: $${trade.takeProfit.toFixed(6)}

💰 Position: $${trade.positionSize.toFixed(2)}
📊 R:R: ${rr}:1
🔥 Conviction: ${(trade.conviction * 100).toFixed(0)}%

Reasoning: ${reasoning}
═══════════════════════
  `.trim();

  const html = `
<h3>🚨 IG-88 TRADE SIGNAL</h3>
<p><strong>Cycle:</strong> ${cycleId}<br/>
<strong>Token:</strong> ${candidate.symbol} (${candidate.name})</p>

<table>
<tr><td>📍 Entry</td><td><code>$${trade.entry.toFixed(6)}</code></td></tr>
<tr><td>🛑 Stop Loss</td><td><code>$${trade.stopLoss.toFixed(6)}</code></td></tr>
<tr><td>🎯 Take Profit</td><td><code>$${trade.takeProfit.toFixed(6)}</code></td></tr>
<tr><td>💰 Position</td><td><code>$${trade.positionSize.toFixed(2)}</code></td></tr>
<tr><td>📊 R:R</td><td><code>${rr}:1</code></td></tr>
<tr><td>🔥 Conviction</td><td><code>${(trade.conviction * 100).toFixed(0)}%</code></td></tr>
</table>

<p><em>${reasoning}</em></p>
  `.trim();

  return { plain, html };
}

// Format daily summary for Matrix
export function formatDailySummary(
  date: string,
  cycles: number,
  signals: number,
  regime: string,
  notes: string[]
): { plain: string; html: string } {
  const plain = `
📊 IG-88 DAILY SUMMARY
═══════════════════════
Date: ${date}
Cycles Run: ${cycles}
Trade Signals: ${signals}
Dominant Regime: ${regime}

Notes:
${notes.map(n => `• ${n}`).join('\n')}
═══════════════════════
  `.trim();

  const html = `
<h3>📊 IG-88 Daily Summary</h3>
<p><strong>Date:</strong> ${date}</p>
<ul>
<li>Cycles Run: ${cycles}</li>
<li>Trade Signals: ${signals}</li>
<li>Dominant Regime: ${regime}</li>
</ul>
<p><strong>Notes:</strong></p>
<ul>
${notes.map(n => `<li>${n}</li>`).join('\n')}
</ul>
  `.trim();

  return { plain, html };
}

// Format error notification
export function formatError(
  component: string,
  error: string,
  context?: string
): { plain: string; html: string } {
  const plain = `
⚠️ IG-88 ERROR
═══════════════════════
Component: ${component}
Error: ${error}
${context ? `Context: ${context}` : ''}
Time: ${new Date().toISOString()}
═══════════════════════
  `.trim();

  const html = `
<h3>⚠️ IG-88 Error</h3>
<p><strong>Component:</strong> ${component}</p>
<p><strong>Error:</strong> <code>${error}</code></p>
${context ? `<p><strong>Context:</strong> ${context}</p>` : ''}
<p><small>${new Date().toISOString()}</small></p>
  `.trim();

  return { plain, html };
}

// High-level alert functions
export async function sendTradeAlert(
  cycleId: string,
  candidate: { symbol: string; name: string; price: number },
  trade: TradeParams,
  reasoning: string
): Promise<boolean> {
  const config = loadConfig();
  const { plain, html } = formatTradeAlert(cycleId, candidate, trade, reasoning);
  return sendMessage(config, plain, html);
}

export async function sendDailySummary(
  date: string,
  cycles: number,
  signals: number,
  regime: string,
  notes: string[]
): Promise<boolean> {
  const config = loadConfig();
  const { plain, html } = formatDailySummary(date, cycles, signals, regime, notes);
  return sendMessage(config, plain, html);
}

export async function sendError(
  component: string,
  error: string,
  context?: string
): Promise<boolean> {
  const config = loadConfig();
  const { plain, html } = formatError(component, error, context);
  return sendMessage(config, plain, html);
}

// Test function
export async function sendTest(): Promise<boolean> {
  const config = loadConfig();
  const message = `🤖 IG-88 Test Message\nTime: ${new Date().toISOString()}\nStatus: Matrix integration working`;
  return sendMessage(config, message);
}

// Send a message as a reply in a thread
export async function sendThreadMessage(
  config: MatrixConfig,
  threadRootId: string,
  body: string,
  formatted?: string
): Promise<{ event_id: string } | null> {
  const token = getToken(config.tokenFile);
  const txnId = `ig88_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const url = `${config.homeserver}/_matrix/client/r0/rooms/${encodeURIComponent(config.roomId)}/send/m.room.message/${txnId}`;

  const message: Record<string, unknown> = {
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

  if (formatted) {
    message.format = 'org.matrix.custom.html';
    message.formatted_body = formatted;
  }

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
      const error = await response.text();
      console.error(`Matrix thread API error ${response.status}: ${error}`);
      return null;
    }

    return response.json() as Promise<{ event_id: string }>;
  } catch (err) {
    console.error('Matrix thread send failed:', err);
    return null;
  }
}

// Send a message and return the event ID (for threading)
export async function sendMessageWithId(
  config: MatrixConfig,
  body: string,
  formatted?: string
): Promise<{ event_id: string } | null> {
  const token = getToken(config.tokenFile);
  const txnId = `ig88_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const url = `${config.homeserver}/_matrix/client/r0/rooms/${encodeURIComponent(config.roomId)}/send/m.room.message/${txnId}`;

  const message: Record<string, string> = {
    msgtype: 'm.text',
    body,
  };

  if (formatted) {
    message.format = 'org.matrix.custom.html';
    message.formatted_body = formatted;
  }

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
      const error = await response.text();
      console.error(`Matrix API error ${response.status}: ${error}`);
      return null;
    }

    return response.json() as Promise<{ event_id: string }>;
  } catch (err) {
    console.error('Matrix send failed:', err);
    return null;
  }
}

// Extract reaction events from sync response
export function extractReactions(sync: SyncResponse, roomId: string): MatrixReactionEvent[] {
  const room = sync.rooms?.join?.[roomId];
  if (!room?.timeline?.events) return [];

  return room.timeline.events.filter(
    (e): e is MatrixReactionEvent =>
      e.type === 'm.reaction' &&
      e.content?.['m.relates_to']?.rel_type === 'm.annotation'
  ) as MatrixReactionEvent[];
}

// Format tool input for display
export function formatToolInput(input: Record<string, unknown>): string {
  if (input.command && typeof input.command === 'string') {
    // Bash command - show command directly
    const cmd = input.command as string;
    if (cmd.length > 100) {
      return cmd.slice(0, 100) + '...';
    }
    return cmd;
  }

  if (input.file_path && typeof input.file_path === 'string') {
    // File operation
    return input.file_path as string;
  }

  // Generic - show JSON preview
  const str = JSON.stringify(input);
  if (str.length > 100) {
    return str.slice(0, 100) + '...';
  }
  return str;
}

// Format age for display
export function formatAge(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

// CLI entry point
if (import.meta.url === `file://${process.argv[1]}`) {
  const command = process.argv[2];

  if (command === 'test') {
    sendTest()
      .then(success => {
        console.log(success ? '✓ Test message sent' : '✗ Failed to send');
        process.exit(success ? 0 : 1);
      })
      .catch(err => {
        console.error('Error:', err.message);
        process.exit(1);
      });
  } else if (command === 'error') {
    const component = process.argv[3] || 'test';
    const error = process.argv[4] || 'Test error message';
    sendError(component, error)
      .then(success => {
        console.log(success ? '✓ Error notification sent' : '✗ Failed to send');
        process.exit(success ? 0 : 1);
      })
      .catch(err => {
        console.error('Error:', err.message);
        process.exit(1);
      });
  } else {
    console.log('Usage:');
    console.log('  node dist/matrix.js test              Send test message');
    console.log('  node dist/matrix.js error [comp] [msg]  Send error notification');
  }
}
