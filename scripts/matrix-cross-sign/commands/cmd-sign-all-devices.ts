/**
 * Sign all devices command — signs every unsigned device for each bot using
 * its existing SSK loaded from SSSS.
 *
 * Use when stale unsigned devices are accumulating and causing "Someone is
 * using an unknown session" warnings in Element. Unlike setup-bot, no browser
 * approval is required — we're signing with keys that already exist.
 *
 * Per-bot credentials required:
 *   - Recovery key (from setup-bot output, stored in age-encrypted secrets)
 *   - Bot password (for temp device login)
 *
 * Run:
 *   npx tsx bot-trust.ts sign-all-devices
 *   npx tsx bot-trust.ts sign-all-devices --user @sir.kelk:matrix.org  (single bot)
 */

import * as sdk from "matrix-js-sdk";
import { decodeRecoveryKey } from "matrix-js-sdk/lib/crypto-api";
import { HOMESERVER, BOT_USERS, BOT_AGENT_NAMES } from "../utils/constants";
import { getCredential } from "../utils/credential-helpers";
import { matrixRequest } from "../utils/http-helpers";
import { cleanupClient } from "../utils/client-lifecycle";
import { startAndSync } from "../utils/matrix-client-utils";
import { bootstrapAndImportCrossSigningKeys } from "../utils/matrix-crypto-utils";

interface BotResult {
  userId: string;
  signed: string[];
  skipped: string[];
  failed: Array<{ deviceId: string; error: string }>;
  error?: string;
}

async function signAllDevicesForBot(
  userId: string,
  recoveryKey: string,
  botPassword: string
): Promise<BotResult> {
  const result: BotResult = { userId, signed: [], skipped: [], failed: [] };
  const decodedKey = decodeRecoveryKey(recoveryKey);

  // Create temp device via password login
  const bareClient = sdk.createClient({ baseUrl: HOMESERVER });
  const loginResp = await bareClient.login("m.login.password", {
    user: userId,
    password: botPassword,
    initial_device_display_name: "bot-trust-setup (temporary)",
  });
  console.error(`  Temp device: ${loginResp.device_id}`);
  const tempToken = loginResp.access_token;

  const client = sdk.createClient({
    baseUrl: HOMESERVER,
    userId,
    deviceId: loginResp.device_id,
    accessToken: tempToken,
    cryptoCallbacks: {
      getSecretStorageKey: async ({ keys }: { keys: Record<string, any> }) => {
        const keyId = Object.keys(keys)[0];
        return [keyId, decodedKey];
      },
    },
  });

  try {
    console.error("  Initializing Rust crypto engine...");
    await client.initRustCrypto({ useIndexedDB: false });
    await startAndSync(client);
    const crypto = client.getCrypto()!;

    // Load SSK from SSSS into OlmMachine
    await bootstrapAndImportCrossSigningKeys(client, {
      requiredKey: "selfSigning",
      throwOnMissingPublicKeys: true,
    });

    // Get full device list from key server — includes signed and unsigned
    console.error(`  Fetching device list from key server...`);
    const deviceMap = await crypto.getUserDeviceInfo([userId], true);
    await new Promise((r) => setTimeout(r, 1000));
    const knownDevices = deviceMap.get(userId);

    if (!knownDevices || knownDevices.size === 0) {
      throw new Error("No devices found in key server for this account");
    }

    // Determine which devices are unsigned via /keys/query.
    // Fetch both device keys and cross-signing keys in one request so we can
    // check against the *current* SSK key ID — not just any non-self ed25519
    // signature, which would falsely match stale signatures from old SSKs.
    const keysData = await matrixRequest(
      "POST", "/_matrix/client/v3/keys/query", tempToken,
      { device_keys: { [userId]: [] } }
    );
    const serverDevices = keysData.device_keys?.[userId] ?? {};
    const sskKeys = keysData.self_signing_keys?.[userId]?.keys ?? {};
    const currentSskKeyId = Object.keys(sskKeys).find((k) => k.startsWith("ed25519:"));
    if (!currentSskKeyId) throw new Error("Could not determine current SSK key ID from /keys/query");
    console.error(`  Current SSK key ID: ${currentSskKeyId}`);

    const unsignedDeviceIds: string[] = [];
    const signedDeviceIds: string[] = [];

    for (const [deviceId, deviceInfo] of Object.entries(serverDevices)) {
      const sigs = (deviceInfo as any).signatures?.[userId] ?? {};
      const isSignedByCurrentSSK = sigs[currentSskKeyId] !== undefined;

      if (isSignedByCurrentSSK) {
        signedDeviceIds.push(deviceId);
        result.skipped.push(deviceId);
      } else {
        unsignedDeviceIds.push(deviceId);
      }
    }

    console.error(`  Already signed: ${signedDeviceIds.join(", ") || "(none)"}`);
    console.error(`  To sign: ${unsignedDeviceIds.join(", ") || "(none)"}`);

    if (unsignedDeviceIds.length === 0) {
      console.error("  All devices already signed — nothing to do.");
      return result;
    }

    // Sign each unsigned device
    for (const deviceId of unsignedDeviceIds) {
      // Skip the temp device we just created — it will be deleted on cleanup
      if (deviceId === loginResp.device_id) {
        console.error(`  Skipping temp device ${deviceId}`);
        result.skipped.push(deviceId);
        continue;
      }

      // Force a fresh key download for this device before signing.
      // crossSignDevice requires the device's ed25519 key to be in the
      // OlmMachine store — a single upfront getUserDeviceInfo isn't always
      // sufficient, especially for the active pan device which may not yet
      // have an Olm session with this ephemeral client.
      console.error(`  Refreshing keys for ${deviceId}...`);
      await crypto.getUserDeviceInfo([userId], true);
      await new Promise((r) => setTimeout(r, 1500));

      let signed = false;
      let lastError = "";
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          console.error(`  Signing ${deviceId}${attempt > 1 ? ` (attempt ${attempt})` : ""}...`);
          await crypto.crossSignDevice(deviceId);
          console.log(`    ✓ ${deviceId}`);
          result.signed.push(deviceId);
          signed = true;
          break;
        } catch (err: any) {
          lastError = err.message;
          console.error(`    ✗ attempt ${attempt}: ${err.message}`);
          if (attempt < 3) {
            console.error(`    Retrying in 3s...`);
            await crypto.getUserDeviceInfo([userId], true);
            await new Promise((r) => setTimeout(r, 3000));
          }
        }
      }
      if (!signed) {
        console.error(`    ✗ ${deviceId} failed after 3 attempts: ${lastError}`);
        result.failed.push({ deviceId, error: lastError });
      }
    }
  } finally {
    await cleanupClient(client, `sign-all-devices(${userId})`);
  }

  return result;
}

export async function run(targetUserId?: string): Promise<void> {
  const bots = targetUserId ? [targetUserId] : [...BOT_USERS];

  console.error("\n── Sign All Devices ──");
  console.error(`Bots: ${bots.join(", ")}`);
  console.error("\nFor each bot, you'll be prompted for its recovery key and password.");
  console.error("Recovery keys were printed during setup-bot and should be in age-encrypted secrets.\n");

  const allResults: BotResult[] = [];

  for (const userId of bots) {
    const agentName = BOT_AGENT_NAMES[userId];
    if (!agentName) {
      console.error(`\nUnknown bot ${userId} — skipping`);
      continue;
    }

    console.error(`\n── ${userId} (${agentName}) ──`);

    let recoveryKey: string;
    let botPassword: string;

    try {
      recoveryKey = await getCredential(
        `MATRIX_RECOVERY_KEY_${agentName.toUpperCase()}`,
        `Recovery key for ${userId}: `
      );
      botPassword = await getCredential(
        `MATRIX_BOT_PASSWORD_${agentName.toUpperCase()}`,
        `Password for ${userId}: `
      );
    } catch (err: any) {
      console.error(`  Skipping ${userId} — credential error: ${err.message}`);
      allResults.push({ userId, signed: [], skipped: [], failed: [], error: err.message });
      continue;
    }

    try {
      const result = await signAllDevicesForBot(userId, recoveryKey, botPassword);
      allResults.push(result);
    } catch (err: any) {
      console.error(`  ✗ ${userId} failed: ${err.message}`);
      allResults.push({ userId, signed: [], skipped: [], failed: [], error: err.message });
    }
  }

  // Summary
  const anyFailures = allResults.some(r => r.error || r.failed.length > 0);
  console.log("\n── Sign All Devices Results ───────────────────────────────────");
  for (const r of allResults) {
    if (r.error) {
      console.log(`  ✗ ${r.userId} — ERROR: ${r.error}`);
    } else {
      const signedStr = r.signed.length > 0 ? `signed ${r.signed.length}` : "nothing new";
      const failedStr = r.failed.length > 0 ? `, ${r.failed.length} FAILED` : "";
      const icon = r.failed.length > 0 ? "⚠" : "✓";
      console.log(`  ${icon} ${r.userId} — ${signedStr}${failedStr}`);
      for (const f of r.failed) {
        console.log(`      ✗ ${f.deviceId}: ${f.error}`);
      }
    }
  }
  if (anyFailures) {
    console.log("\n  Some devices could not be signed. Run again or check errors above.");
    process.exitCode = 1;
  }
}
