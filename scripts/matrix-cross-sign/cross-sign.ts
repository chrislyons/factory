#!/usr/bin/env tsx
/**
 * Matrix E2EE Cross-Signing Automation Tool
 *
 * Cross-signs unverified devices for a Matrix account using the
 * self-signing key stored in SSSS (Secure Secret Storage and Sharing).
 *
 * Usage:
 *   npx tsx cross-sign.ts list              # List devices + verification status
 *   npx tsx cross-sign.ts sign              # Cross-sign unverified devices
 *   npx tsx cross-sign.ts sign --dry-run    # Preview what would be signed
 *   npx tsx cross-sign.ts sign --user @ig88bot:matrix.org  # Cross-sign a specific bot
 *
 * Environment (optional — prompts interactively if not set):
 *   MATRIX_RECOVERY_KEY   - Element security/recovery key (base58)
 *   MATRIX_PASSWORD        - Account password
 *   MATRIX_USER            - User ID (default: @chrislyons:matrix.org)
 *   MATRIX_HOMESERVER      - Homeserver URL (default: https://matrix.org)
 *
 * Recommended: pass secrets via short-lived subshell, not persistent env:
 *   MATRIX_PASSWORD=... MATRIX_RECOVERY_KEY=... npx tsx cross-sign.ts sign --user @ig88bot:matrix.org
 *
 * If env vars are not set, prompts interactively via stdin (secrets not echoed).
 */

import "fake-indexeddb/auto";
import * as sdk from "matrix-js-sdk";
import { decodeRecoveryKey } from "matrix-js-sdk/lib/crypto-api";
import * as readline from "node:readline";
// execSync removed — Pantalaimon integration retired.
import { suppressMatrixSdkLogs } from "./utils/suppress-sdk-logs";
import { startAndSync } from "./utils/matrix-client-utils";
import { bootstrapAndImportCrossSigningKeys } from "./utils/matrix-crypto-utils";

suppressMatrixSdkLogs();

// ── Types ──────────────────────────────────────────────────────

interface DeviceInfo {
  deviceId: string;
  displayName: string | undefined;
  crossSigningVerified: boolean;
  locallyVerified: boolean;
  isCurrentDevice: boolean;
}

// ── Credential Helpers ─────────────────────────────────────────

async function promptSecret(prompt: string): Promise<string> {
  process.stderr.write(prompt);

  // Suppress echo by routing readline's output to a muted stream.
  // This is the standard Node.js pattern for hidden password input.
  const { Writable } = await import("node:stream");
  const muted = new Writable({ write(_chunk, _enc, cb) { cb(); } });

  const rl = readline.createInterface({
    input: process.stdin,
    output: muted,
    terminal: true,
  });

  return new Promise((resolve) => {
    rl.question("", (answer) => {
      rl.close();
      process.stderr.write("\n");
      resolve(answer);
    });
  });
}

async function getCredential(
  envVar: string,
  prompt: string
): Promise<string> {
  const value = process.env[envVar];
  if (value) return value;
  return promptSecret(prompt);
}

// ── Matrix Client Setup ────────────────────────────────────────

async function createAuthenticatedClient(): Promise<sdk.MatrixClient> {
  const homeserver =
    process.env.MATRIX_HOMESERVER || "https://matrix.org";
  const userId =
    process.env.MATRIX_USER || "@chrislyons:matrix.org";

  // Gather both credentials upfront (before any network calls)
  const password = await getCredential(
    "MATRIX_PASSWORD",
    "Matrix password: "
  );
  // Cache password for interactive auth (device deletion)
  process.env._MATRIX_PASSWORD_CACHED = password;
  const recoveryKey = await getCredential(
    "MATRIX_RECOVERY_KEY",
    "Recovery key (base58): "
  );

  // Decode recovery key to raw bytes for the SSSS callback
  const decodedKey = decodeRecoveryKey(recoveryKey);

  // Two-step client creation:
  // 1. Login with a bare client to get the server-assigned device_id + access_token
  // 2. Create the real client with those credentials so initRustCrypto() is happy
  //
  // Why: initRustCrypto() requires deviceId in the constructor, but pre-setting a
  // custom one causes M_BAD_JSON (server assigns a different ID during login).
  const tempClient = sdk.createClient({ baseUrl: homeserver });

  console.error("Logging in as", userId, "...");
  const loginResponse = await tempClient.login("m.login.password", {
    user: userId,
    password,
    initial_device_display_name: "Cross-Sign Tool (temporary)",
  });
  console.error(`Device ID: ${loginResponse.device_id}`);

  // Create the real client with server-assigned credentials + SSSS callback.
  // The getSecretStorageKey callback is invoked by bootstrapSecretStorage to
  // decrypt the cross-signing keys stored in SSSS.
  const client = sdk.createClient({
    baseUrl: homeserver,
    userId,
    deviceId: loginResponse.device_id,
    accessToken: loginResponse.access_token,
    cryptoCallbacks: {
      getSecretStorageKey: async (
        { keys }: { keys: Record<string, any> }
      ) => {
        const keyId = Object.keys(keys)[0];
        return [keyId, decodedKey];
      },
    },
  });

  return client;
}

async function initCrypto(client: sdk.MatrixClient): Promise<void> {
  console.error("Initializing Rust crypto engine...");
  await client.initRustCrypto();
}

// ── Cross-Signing Bootstrap ────────────────────────────────────

async function bootstrapSecretStorage(
  client: sdk.MatrixClient
): Promise<void> {
  // Recovery key is already wired via cryptoCallbacks.getSecretStorageKey
  // (set during client creation).
  await bootstrapAndImportCrossSigningKeys(client, {
    requiredKey: "selfSigning",
    verifyViaCrossSigningStatus: true,
  });
}

// ── Device Enumeration ─────────────────────────────────────────

async function getDevices(
  client: sdk.MatrixClient
): Promise<DeviceInfo[]> {
  const crypto = client.getCrypto();
  if (!crypto) throw new Error("Crypto not initialized");

  const userId = client.getUserId()!;
  const ownDeviceId = client.getDeviceId()!;

  // Key download already done in bootstrapSecretStorage. Re-fetch device list.
  const deviceMap = await crypto.getUserDeviceInfo([userId], true);
  const devices = deviceMap.get(userId);

  if (!devices) return [];

  const result: DeviceInfo[] = [];
  for (const [deviceId, device] of devices) {
    let crossSigningVerified = false;
    let locallyVerified = false;

    try {
      const status = await crypto.getDeviceVerificationStatus(
        userId,
        deviceId
      );
      crossSigningVerified = status?.crossSigningVerified ?? false;
      locallyVerified = status?.locallyVerified ?? false;
    } catch {
      // Device might be deleted or unavailable
    }

    result.push({
      deviceId,
      displayName: device.displayName,
      crossSigningVerified,
      locallyVerified,
      isCurrentDevice: deviceId === ownDeviceId,
    });
  }

  return result.sort((a, b) => a.deviceId.localeCompare(b.deviceId));
}

function printDeviceTable(devices: DeviceInfo[]): void {
  const header = `${"Device ID".padEnd(28)} ${"Display Name".padEnd(36)} ${"Cross-Signed".padEnd(14)} Local`;
  console.log(header);
  console.log("─".repeat(header.length));

  for (const d of devices) {
    const cs = d.crossSigningVerified ? "  ✓" : "  ✗";
    const lv = d.locallyVerified ? "  ✓" : "  ✗";
    const name = d.displayName || "(unnamed)";
    const suffix = d.isCurrentDevice ? " ← this session" : "";
    console.log(
      `${d.deviceId.padEnd(28)} ${name.padEnd(36)} ${cs.padEnd(14)} ${lv}${suffix}`
    );
  }
}

// ── Cross-Sign Action ──────────────────────────────────────────

async function crossSignDevices(
  client: sdk.MatrixClient,
  dryRun: boolean
): Promise<void> {
  const crypto = client.getCrypto();
  if (!crypto) throw new Error("Crypto not initialized");

  const devices = await getDevices(client);
  const ownDeviceId = client.getDeviceId()!;

  const unsigned = devices.filter(
    (d) => !d.crossSigningVerified && !d.isCurrentDevice
  );

  if (unsigned.length === 0) {
    console.log("\nAll devices are already cross-signed. Nothing to do.");
    return;
  }

  console.log(
    `\n${dryRun ? "[DRY RUN] " : ""}${unsigned.length} device(s) to sign:\n`
  );

  const signed: string[] = [];

  for (const device of unsigned) {
    const label = `${device.deviceId} (${device.displayName || "unnamed"})`;

    if (dryRun) {
      console.log(`  Would sign: ${label}`);
      signed.push(device.deviceId);
      continue;
    }

    try {
      // crossSignDevice: signs device keys with self-signing key, then
      // uploads the signature to the server via outgoingRequestProcessor.
      // This is different from setDeviceVerified which only sets LOCAL trust.
      await crypto.crossSignDevice(device.deviceId);
      console.log(`  ✓ Cross-signed: ${label}`);
      signed.push(device.deviceId);
    } catch (err: any) {
      console.error(`  ✗ Failed: ${label} — ${err.message}`);
    }
  }

  if (dryRun) {
    console.log("\nDry run complete. No changes made.");
    return;
  }

  console.log(`\nSigned ${signed.length}/${unsigned.length} device(s).`);

}

// ── Purge Dead Devices ───────────────────────────────────────────

/** Known dead device display names that should be purged. */
const DEAD_DEVICE_NAMES = ["pantalaimon"];

async function purgeDeadDevices(
  client: sdk.MatrixClient,
  dryRun: boolean
): Promise<void> {
  // Fetch all devices from the server (not crypto — we want the full list)
  const resp = await client.getDevices();
  if (!resp?.devices) {
    console.log("No devices returned from server.");
    return;
  }

  const ownDeviceId = client.getDeviceId()!;
  const dead = resp.devices.filter((d: any) => {
    if (d.device_id === ownDeviceId) return false; // never delete self
    const name = (d.display_name || "").toLowerCase();
    return DEAD_DEVICE_NAMES.some((n) => name.includes(n));
  });

  if (dead.length === 0) {
    console.log("\nNo dead devices found. Nothing to purge.");
    return;
  }

  console.log(
    `\n${dryRun ? "[DRY RUN] " : ""}${dead.length} dead device(s) to purge:\n`
  );

  for (const d of dead) {
    const label = `${d.device_id} (${d.display_name || "unnamed"})`;
    if (dryRun) {
      console.log(`  Would delete: ${label}`);
      continue;
    }

    try {
      // deleteDevice requires interactive auth — use password from env
      const password = process.env._MATRIX_PASSWORD_CACHED;
      await client.deleteDevice(d.device_id, {
        type: "m.login.password",
        identifier: { type: "m.id.user", user: client.getUserId()! },
        password,
      });
      console.log(`  ✓ Deleted: ${label}`);
    } catch (err: any) {
      console.error(`  ✗ Failed: ${label} — ${err.message}`);
    }
  }

  if (dryRun) {
    console.log("\nDry run complete. No devices deleted.");
  }
}

// ── Cleanup ────────────────────────────────────────────────────

async function cleanup(client: sdk.MatrixClient): Promise<void> {
  try {
    client.stopClient();
    console.error("Logging out temporary device...");
    await client.logout(true);
    console.error("Temporary device removed.");
  } catch (err: any) {
    console.error(`Warning: cleanup error — ${err.message}`);
    console.error(
      "Check Element settings for orphaned 'Cross-Sign Tool (temporary)' device."
    );
  }
}

// ── Main ───────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const command = args.find((a) => !a.startsWith("-")) || "sign";
  const dryRun = args.includes("--dry-run");

  // --user flag overrides MATRIX_USER env var
  const userIdx = args.indexOf("--user");
  if (userIdx !== -1 && args[userIdx + 1]) {
    process.env.MATRIX_USER = args[userIdx + 1];
  }

  if (args.includes("--help") || args.includes("-h")) {
    console.log(`
Matrix E2EE Cross-Signing Tool

Usage:
  npx tsx cross-sign.ts list                           List devices + verification status
  npx tsx cross-sign.ts sign                           Cross-sign unverified devices
  npx tsx cross-sign.ts sign --dry-run                 Preview (no changes)
  npx tsx cross-sign.ts sign --user @bot:matrix.org    Cross-sign a specific bot's devices
  npx tsx cross-sign.ts purge                          Delete dead devices (pantalaimon, etc.)
  npx tsx cross-sign.ts purge --dry-run                Preview purge (no deletions)

Environment variables:
  MATRIX_RECOVERY_KEY   Recovery key (base58, from Element security settings)
  MATRIX_PASSWORD       Account password for @chrislyons:matrix.org
  MATRIX_USER           User ID (default: @chrislyons:matrix.org)
  MATRIX_HOMESERVER     Homeserver (default: https://matrix.org)

Security:
  Credentials are never logged or written to disk. Use env vars or stdin.
  After running: unset MATRIX_RECOVERY_KEY MATRIX_PASSWORD
`);
    process.exit(0);
  }

  if (!["list", "sign", "purge"].includes(command)) {
    console.error(`Unknown command: ${command}`);
    console.error("Use --help for usage information.");
    process.exit(1);
  }

  let client: sdk.MatrixClient | null = null;

  try {
    client = await createAuthenticatedClient();
    await initCrypto(client);
    await startAndSync(client);

    if (command === "list") {
      await bootstrapSecretStorage(client);
      const crypto = client.getCrypto()!;
      const crossSigningStatus = await crypto.getCrossSigningStatus();
      console.log("\n── Cross-Signing Key Status ──");
      console.log(`  Private keys on device: ${JSON.stringify(crossSigningStatus)}`);

      const userVerification = await crypto.getUserVerificationStatus(client.getUserId()!);
      console.log(`  User verified (own identity): ${userVerification?.crossSigningVerified ?? "unknown"}`);

      const devices = await getDevices(client);
      console.log(`\nDevices for ${client.getUserId()}:\n`);
      printDeviceTable(devices);
      const verified = devices.filter((d) => d.crossSigningVerified).length;
      console.log(
        `\n${verified}/${devices.length} cross-signed, ${devices.length - verified} unverified`
      );
    } else if (command === "purge") {
      await bootstrapSecretStorage(client);
      console.log(`\nDevices for ${client.getUserId()}:\n`);
      const before = await getDevices(client);
      printDeviceTable(before);
      await purgeDeadDevices(client, dryRun);
    } else {
      // sign
      await bootstrapSecretStorage(client);
      console.log(`\nCurrent device state:`);
      const before = await getDevices(client);
      printDeviceTable(before);
      await crossSignDevices(client, dryRun);

      if (!dryRun) {
        // Wait for server to propagate signatures before re-fetching
        console.log("\nWaiting for server propagation...");
        await new Promise((r) => setTimeout(r, 3000));
        console.log(`\nUpdated device state:`);
        const after = await getDevices(client);
        printDeviceTable(after);
      }
    }
  } catch (err: any) {
    console.error(`\nFatal: ${err.message}`);
    if (err.data) console.error("Server response:", JSON.stringify(err.data));
    process.exit(1);
  } finally {
    if (client) await cleanup(client);
  }
}

main();
