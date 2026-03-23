/**
 * Status command — queries /_matrix/client/v3/keys/query to show trust state
 * for all 4 accounts (Chris + 3 bots).
 *
 * Checks: MSK/SSK/USK presence, device signed by own SSK, MSK trusted by
 * Chris's USK.
 */

import { CHRIS_USER, BOT_USERS } from "../utils/constants";
import { matrixRequest } from "../utils/http-helpers";

export async function run(token: string): Promise<void> {
  console.error("Querying key server for all accounts...\n");
  const allUsers = [CHRIS_USER, ...BOT_USERS];

  const data = await matrixRequest("POST", "/_matrix/client/v3/keys/query", token, {
    device_keys: Object.fromEntries(allUsers.map((u) => [u, []])),
  });

  const masterKeys = data.master_keys ?? {};
  const selfSigningKeys = data.self_signing_keys ?? {};
  const userSigningKeys = data.user_signing_keys ?? {};
  const deviceKeys = data.device_keys ?? {};

  // Chris's USK key ID — needed to check bot trust signatures
  const chrisUSK = userSigningKeys[CHRIS_USER];
  const chrisUSKKeyId = chrisUSK
    ? Object.keys(chrisUSK.keys ?? {}).find((k) => k.startsWith("ed25519:"))
    : null;

  const icon = (v: boolean) => (v ? "✓" : "✗");
  const col = (s: string, w: number) => s.padEnd(w);

  // USK is private — only returned to the account owner. If queried with a bot
  // token, @chrislyons's USK will show ✗ even if it exists, and "Trusted by Chris"
  // will always show ✗. Use --token with a @chrislyons token for accurate USK/trust data.
  const queryingAsChris = !!(data.user_signing_keys?.[CHRIS_USER]);
  if (!queryingAsChris) {
    console.log("Note: USK column and 'Trusted by Chris' require a @chrislyons token to be accurate.");
    console.log("      (user_signing_keys is private — not returned for other accounts)\n");
  }

  console.log("── Account Trust State ───────────────────────────────────────────────────────");
  console.log(`${col("User", 38)} ${col("MSK", 5)} ${col("SSK", 5)} ${col("USK", 5)} ${col("Dev Signed", 12)} Trusted by Chris`);
  console.log("─".repeat(82));

  for (const userId of allUsers) {
    const hasMSK = !!(masterKeys[userId]);
    const hasSSK = !!(selfSigningKeys[userId]);
    const hasUSK = !!(userSigningKeys[userId]);

    if (userId === CHRIS_USER) {
      console.log(`${col(userId, 38)} ${col(icon(hasMSK), 5)} ${col(icon(hasSSK), 5)} ${col(icon(hasUSK), 5)} ${col("—", 12)} — (own account)`);
      continue;
    }

    // Check if any of the bot's devices is signed by its own SSK
    let deviceSigned = false;
    if (hasSSK && deviceKeys[userId]) {
      const sskKeyId = Object.keys(selfSigningKeys[userId].keys ?? {})
        .find((k) => k.startsWith("ed25519:"));
      for (const device of Object.values(deviceKeys[userId] as Record<string, any>)) {
        const sigs = device.signatures?.[userId] ?? {};
        if (sskKeyId && sigs[sskKeyId] !== undefined) {
          deviceSigned = true;
          break;
        }
      }
    }

    // Check if Chris's USK has signed the bot's MSK
    let trustedByChris = false;
    if (hasMSK && chrisUSKKeyId) {
      const mskSigs = masterKeys[userId].signatures?.[CHRIS_USER] ?? {};
      trustedByChris = mskSigs[chrisUSKKeyId] !== undefined;
    }

    console.log(
      `${col(userId, 38)} ${col(icon(hasMSK), 5)} ${col(icon(hasSSK), 5)} ${col(icon(hasUSK), 5)} ${col(icon(deviceSigned), 12)} ${icon(trustedByChris)}`
    );
  }

  // Show device list for each bot
  console.log("\n── Bot Devices ───────────────────────────────────────────────────────────────");
  for (const userId of BOT_USERS) {
    const devices = deviceKeys[userId] ?? {};
    const entries = Object.entries(devices as Record<string, any>);
    console.log(`\n${userId} (${entries.length} device${entries.length !== 1 ? "s" : ""}):`);
    for (const [deviceId, device] of entries) {
      const name = device.unsigned?.device_display_name || "(no display name)";
      const hasSig = (() => {
        const sskKeyId = selfSigningKeys[userId]
          ? Object.keys(selfSigningKeys[userId].keys ?? {}).find((k) => k.startsWith("ed25519:"))
          : null;
        if (!sskKeyId) return "no SSK";
        const sigs = device.signatures?.[userId] ?? {};
        return sigs[sskKeyId] !== undefined ? "signed ✓" : "unsigned ✗";
      })();
      console.log(`  ${deviceId.padEnd(28)} ${name.padEnd(30)} ${hasSig}`);
    }
  }
}
