/**
 * Prune devices command — deletes stale unsigned devices.
 *
 * Removes all unsigned devices except the active Pantalaimon device (from
 * pan.db) and the temporary login device. Requires UIA with m.login.password,
 * which matrix.org does support for device deletion.
 */

import * as sdk from "matrix-js-sdk";
import { HOMESERVER, BOT_AGENT_NAMES } from "../utils/constants";
import { getCredential } from "../utils/credential-helpers";
import { matrixRequest } from "../utils/http-helpers";
import { getPanDeviceId } from "../utils/pan-utils";

export async function run(userId: string): Promise<void> {
  const agentName = BOT_AGENT_NAMES[userId];
  if (!agentName) throw new Error(`Unknown bot: ${userId}`);

  console.error(`\n── Pruning stale Pantalaimon devices for ${userId} ──`);

  // Get the active Pantalaimon device from pan.db
  const activeDeviceId = getPanDeviceId(userId);
  console.error(`  Active device (pan.db): ${activeDeviceId}`);

  const password = await getCredential(
    `MATRIX_BOT_PASSWORD_${agentName.toUpperCase()}`,
    `Password for ${userId}: `
  );

  // Login with temp device to get an access token
  const bareClient = sdk.createClient({ baseUrl: HOMESERVER });
  const loginResp = await bareClient.login("m.login.password", {
    user: userId, password,
    initial_device_display_name: "prune-devices (temporary)",
  });
  const token = loginResp.access_token;
  console.error(`  Temp device: ${loginResp.device_id}`);

  try {
    // Get full device list and server-side signing state
    const { devices } = await matrixRequest("GET", "/_matrix/client/v3/devices", token);
    const keysData = await matrixRequest(
      "POST", "/_matrix/client/v3/keys/query", token,
      { device_keys: { [userId]: [] } }
    );
    const serverDevices = keysData.device_keys?.[userId] ?? {};

    const sskKeys = keysData.self_signing_keys?.[userId]?.keys ?? {};
    const currentSskKeyId = Object.keys(sskKeys).find((k) => k.startsWith("ed25519:"));
    const isSignedBySSK = (deviceId: string): boolean => {
      if (!currentSskKeyId) return false;
      const sigs = (serverDevices[deviceId] as any)?.signatures?.[userId] ?? {};
      return sigs[currentSskKeyId] !== undefined;
    };

    const stale = (devices as any[]).filter(
      (d) =>
        d.device_id !== activeDeviceId &&
        d.device_id !== loginResp.device_id &&
        !isSignedBySSK(d.device_id)
    );

    if (stale.length === 0) {
      console.log("No stale unsigned devices found.");
      return;
    }

    console.error(`  Stale unsigned devices to remove: ${stale.map((d: any) => `${d.device_id} (${d.display_name ?? "unnamed"})`).join(", ")}`);

    const staleIds = stale.map((d: any) => d.device_id);

    // Step 1: probe POST /delete_devices to get UIA session
    let session = "";
    try {
      await matrixRequest("POST", "/_matrix/client/v3/delete_devices", token, { devices: staleIds });
      console.log(`  ✓ Deleted ${staleIds.join(", ")} (no UIA needed)`);
      return;
    } catch (e: any) {
      if (!e?.data?.flows) throw e;
      session = e?.data?.session ?? "";
    }

    // Step 2: retry with password UIA
    await matrixRequest("POST", "/_matrix/client/v3/delete_devices", token, {
      devices: staleIds,
      auth: {
        type: "m.login.password",
        password,
        identifier: { type: "m.id.user", user: userId },
        session,
      },
    });
    for (const d of stale) console.log(`  ✓ Deleted ${d.device_id} (${d.display_name ?? "unnamed"})`);
  } finally {
    // Clean up temp device
    try {
      await matrixRequest("POST", "/_matrix/client/v3/delete_devices", token, { devices: [loginResp.device_id] });
    } catch (e: any) {
      const session = e?.data?.session ?? "";
      try {
        await matrixRequest("POST", "/_matrix/client/v3/delete_devices", token, {
          devices: [loginResp.device_id],
          auth: { type: "m.login.password", password, identifier: { type: "m.id.user", user: userId }, session },
        });
      } catch { /* best effort */ }
    }
  }
}
