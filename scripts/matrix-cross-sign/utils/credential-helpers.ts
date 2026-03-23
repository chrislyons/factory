/**
 * Credential retrieval helpers for Matrix bot trust scripts.
 *
 * Provides interactive prompts for credential input.
 * No credentials are logged or written to disk.
 *
 * Bot tokens are now managed via BWS (Bitwarden Secrets Manager)
 * and injected as env vars by mcp-env.sh. Use MATRIX_TOKEN_PAN_<AGENT>
 * env vars instead of the old file-based approach.
 */

import * as readline from "node:readline";

export async function promptSecret(prompt: string): Promise<string> {
  process.stderr.write(prompt);
  const { Writable } = await import("node:stream");
  const muted = new Writable({ write(_chunk, _enc, cb) { cb(); } });
  const rl = readline.createInterface({ input: process.stdin, output: muted, terminal: true });
  return new Promise((resolve) => {
    rl.question("", (answer) => {
      rl.close();
      process.stderr.write("\n");
      resolve(answer);
    });
  });
}

export async function getCredential(envVar: string, prompt: string): Promise<string> {
  const value = process.env[envVar];
  if (value) return value;
  return promptSecret(prompt);
}

export function getBotPanToken(agentName: string): string {
  const envVar = `MATRIX_TOKEN_PAN_${agentName.toUpperCase()}`;
  const token = process.env[envVar];
  if (token) return token;
  throw new Error(
    `No token found. Set ${envVar} env var.\n` +
    `  Use mcp-env.sh to inject from BWS, or export manually.`
  );
}
