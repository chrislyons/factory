/**
 * Sign device command — signs a specific device using existing cross-signing
 * keys loaded from SSSS.
 *
 * Use this after setup-bot has completed but the device sign step failed
 * (e.g. device wasn't in the key server yet — restart Pantalaimon first).
 *
 * Unlike setup-bot, no browser approval is needed — we're not resetting
 * cross-signing, just signing a device with keys that already exist.
 */

import * as sdk from "matrix-js-sdk";
import { decodeRecoveryKey } from "matrix-js-sdk/lib/crypto-api";
import { HOMESERVER, BOT_AGENT_NAMES } from "../utils/constants";
import { getCredential } from "../utils/credential-helpers";
import { cleanupClient } from "../utils/client-lifecycle";
import { startAndSync } from "../utils/matrix-client-utils";
import { bootstrapAndImportCrossSigningKeys } from "../utils/matrix-crypto-utils";

export async function run(userId: string, deviceId: string): Promise<void> {
  const agentName = BOT_AGENT_NAMES[userId];
  if (!agentName) {
    throw new Error(`Unknown bot user: ${userId}\nValid bots: ${Object.keys(BOT_AGENT_NAMES).join(", ")}`);
  }

  console.error(`\n── Signing device ${deviceId} for ${userId} ──`);

  const recoveryKey = await getCredential(
    "MATRIX_RECOVERY_KEY",
    `Recovery key for ${userId} (from setup-bot output): `
  );
  const decodedKey = decodeRecoveryKey(recoveryKey);

  const botPassword = await getCredential(
    "MATRIX_BOT_PASSWORD",
    `Password for ${userId}: `
  );

  // Login as bot with a fresh temp device
  const bareClient = sdk.createClient({ baseUrl: HOMESERVER });
  const loginResp = await bareClient.login("m.login.password", {
    user: userId,
    password: botPassword,
    initial_device_display_name: "bot-trust-setup (temporary)",
  });
  console.error(`  Temp device: ${loginResp.device_id}`);

  const client = sdk.createClient({
    baseUrl: HOMESERVER,
    userId,
    deviceId: loginResp.device_id,
    accessToken: loginResp.access_token,
    cryptoCallbacks: {
      getSecretStorageKey: async ({ keys }: { keys: Record<string, any> }) => {
        const keyId = Object.keys(keys)[0];
        return [keyId, decodedKey];
      },
    },
  });

  try {
    console.error("Initializing Rust crypto engine...");
    await client.initRustCrypto();
    await startAndSync(client);
    const crypto = client.getCrypto()!;

    // Load cross-signing private keys from SSSS. throwOnMissingPublicKeys
    // because sign-device requires setup-bot to have run first.
    await bootstrapAndImportCrossSigningKeys(client, {
      requiredKey: "selfSigning",
      throwOnMissingPublicKeys: true,
    });

    // Refresh device list and confirm target is visible
    console.error(`\nFetching device list...`);
    const deviceMap = await crypto.getUserDeviceInfo([userId], true);
    await new Promise((r) => setTimeout(r, 1000));
    const knownDevices = deviceMap.get(userId);
    const deviceIds = knownDevices ? [...knownDevices.keys()] : [];
    console.error(`  Devices in key server: ${deviceIds.join(", ") || "(none)"}`);

    if (!deviceIds.includes(deviceId)) {
      throw new Error(
        `Device ${deviceId} not in the key server.\n` +
        `Restart Pantalaimon on Whitebox to re-upload its device keys:\n` +
        `  ssh whitebox "launchctl stop com.pantalaimon && launchctl start com.pantalaimon"\n` +
        `Then re-run this command.`
      );
    }

    // Sign the device
    console.error(`\nSigning ${deviceId}...`);
    await crypto.crossSignDevice(deviceId);
    console.log(`  ✓ Device ${deviceId} signed.`);
  } finally {
    await cleanupClient(client, `sign-device(${userId})`);
  }
}
