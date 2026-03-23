/**
 * Setup bot command — creates MSK/SSK/USK for a bot that has none (likely
 * first-time setup), bootstraps SSSS with a freshly generated recovery key,
 * then cross-signs the Pantalaimon device using the new SSK.
 *
 * Primary credential path: SSH to Blackbox -> Pantalaimon token -> /login/get_token
 * -> m.login.token UIA. No bot password needed if matrix.org supports this flow.
 * Fallback: interactive password prompt.
 */

import * as sdk from "matrix-js-sdk";
import { encodeRecoveryKey } from "matrix-js-sdk/lib/crypto-api";
import { randomBytes } from "node:crypto";
import { HOMESERVER, BOT_AGENT_NAMES } from "../utils/constants";
import { promptSecret, getCredential, getBotPanToken } from "../utils/credential-helpers";
import { matrixRequest } from "../utils/http-helpers";
import { cleanupClient } from "../utils/client-lifecycle";
import { startAndSync } from "../utils/matrix-client-utils";
import { getPanDeviceId } from "../utils/pan-utils";
import { bootstrapAndImportCrossSigningKeys } from "../utils/matrix-crypto-utils";

export async function run(userId: string): Promise<void> {
  const agentName = BOT_AGENT_NAMES[userId];
  if (!agentName) {
    throw new Error(
      `Unknown bot user: ${userId}\nValid bots: ${Object.keys(BOT_AGENT_NAMES).join(", ")}`
    );
  }

  console.error(`\n── Setting up cross-signing for ${userId} (${agentName}) ──`);

  // Step 1: Get Pantalaimon token via SSH
  console.error(`Fetching ${agentName} Pantalaimon token from Blackbox...`);
  const panToken = getBotPanToken(agentName);
  console.error(`  Token obtained (${panToken.length} chars).`);

  // Step 2: Identify Pantalaimon's actual device by querying its local SQLite database.
  // /account/whoami with the stored token can return the wrong device — the stored
  // token may correspond to a temp device created by a previous script run, not to
  // the E2EE-capable device Pantalaimon manages internally.
  console.error("Identifying Pantalaimon device from pan.db...");
  let panDeviceId: string;
  try {
    panDeviceId = getPanDeviceId(userId);
    console.error(`  Pantalaimon device (from pan.db): ${panDeviceId}`);
  } catch (err: any) {
    // Fallback to /account/whoami if pan.db query fails
    console.error(`  pan.db query failed (${err.message}), falling back to /account/whoami...`);
    const whoami = await matrixRequest("GET", "/_matrix/client/v3/account/whoami", panToken);
    panDeviceId = whoami.device_id;
    console.error(`  Pantalaimon device (from whoami): ${panDeviceId}`);
  }

  // Step 3: Get a login_token for the temp device login
  // POST /v1/login/get_token with the Pantalaimon token -> single-use login token
  let tempLoginToken: string | null = null;
  console.error("Requesting login token for temp device (/v1/login/get_token)...");
  try {
    const tokenData = await matrixRequest(
      "POST", "/_matrix/client/v1/login/get_token", panToken, {}
    );
    tempLoginToken = tokenData.login_token ?? null;
    console.error(tempLoginToken ? "  Login token obtained." : "  No login_token in response.");
  } catch (err: any) {
    console.error(`  /v1/login/get_token failed: ${err.message}`);
  }

  // Step 4: Create temporary device (m.login.token primary, password fallback)
  const bareClient = sdk.createClient({ baseUrl: HOMESERVER });
  let loginResp: any;

  if (tempLoginToken) {
    try {
      console.error("Logging in with m.login.token...");
      loginResp = await bareClient.login("m.login.token", {
        token: tempLoginToken,
        initial_device_display_name: "bot-trust-setup (temporary)",
      });
    } catch (err: any) {
      console.error(`  m.login.token failed: ${err.message}`);
    }
  }

  if (!loginResp) {
    console.error("Falling back to password login...");
    // Prefer MATRIX_BOT_PASSWORD env var to avoid blocking on interactive prompt
    const password = await getCredential(
      "MATRIX_BOT_PASSWORD",
      `Password for ${userId}: `
    );
    loginResp = await bareClient.login("m.login.password", {
      user: userId,
      password,
      initial_device_display_name: "bot-trust-setup (temporary)",
    });
  }
  console.error(`  Temp device: ${loginResp.device_id}`);

  // Step 5: Get a fresh login_token for UIA (Pantalaimon token is still valid)
  // The first token was consumed by the temp-device login above.
  let uiaLoginToken: string | null = null;
  console.error("Getting fresh login token for UIA callback...");
  try {
    const uiaTokenData = await matrixRequest(
      "POST", "/_matrix/client/v1/login/get_token", panToken, {}
    );
    uiaLoginToken = uiaTokenData.login_token ?? null;
    console.error(uiaLoginToken ? "  UIA token obtained." : "  No UIA token — will prompt for password if UIA required.");
  } catch (err: any) {
    console.error(`  UIA token fetch failed: ${err.message}`);
  }

  // Step 6: Generate new SSSS recovery key for this bot
  const newPrivateKey = randomBytes(32);
  const encodedRecoveryKey = encodeRecoveryKey(newPrivateKey);

  // Step 7: Build full SDK client with crypto
  const client = sdk.createClient({
    baseUrl: HOMESERVER,
    userId,
    deviceId: loginResp.device_id,
    accessToken: loginResp.access_token,
    cryptoCallbacks: {
      getSecretStorageKey: async ({ keys }: { keys: Record<string, any> }) => {
        const keyId = Object.keys(keys)[0] ?? "primary";
        return [keyId, newPrivateKey];
      },
    },
  });

  try {
    console.error("Initializing Rust crypto engine...");
    await client.initRustCrypto();
    await startAndSync(client);
    const crypto = client.getCrypto()!;

    // Step 8: Bootstrap cross-signing (creates MSK/SSK/USK on the server).
    // setupNewCrossSigning: true forces fresh key generation even if keys exist.
    // Without it, the SDK tries to read private keys from SSSS using our callback,
    // which returns a random key -> "bad MAC" for accounts that already have SSSS.
    //
    // matrix.org UIA note: m.login.password is no longer accepted for cross-signing
    // key upload. The server returns flows: [m.oauth, org.matrix.cross_signing_reset].
    // We attempt password first (works on other homeservers), then fall back to
    // the browser-based org.matrix.cross_signing_reset flow.
    console.error("\nBootstrapping cross-signing keys...");

    // Capture password before entering the callback (avoids double-prompt if
    // makeRequest is retried after the browser approval step)
    const botPassword = await getCredential(
      "MATRIX_BOT_PASSWORD",
      `Password for ${userId} (for UIA): `
    );

    await crypto.bootstrapCrossSigning({
      setupNewCrossSigning: true,
      authUploadDeviceSigningKeys: async (
        makeRequest: (authData: object) => Promise<void>
      ) => {
        // Attempt 1: m.login.password (works on homeservers that support it)
        try {
          console.error("  UIA: trying m.login.password...");
          await makeRequest({
            type: "m.login.password",
            password: botPassword,
            identifier: { type: "m.id.user", user: userId },
          });
          console.error("  UIA: accepted.");
          return;
        } catch (e: any) {
          // Parse the 401 response to check for org.matrix.cross_signing_reset
          const flows: any[] = e?.data?.flows ?? [];
          const params: any = e?.data?.params ?? {};
          const hasResetFlow = flows.some((f: any) =>
            f.stages?.includes("org.matrix.cross_signing_reset")
          );

          if (!hasResetFlow) {
            // Unexpected failure — not a known UIA challenge
            throw new Error(`UIA failed (${e.message}). Available flows: ${JSON.stringify(flows)}`);
          }

          // Attempt 2: org.matrix.cross_signing_reset — requires browser approval.
          // The user must log in as the bot in a browser and visit the account
          // management URL to authorise the cross-signing reset before we retry.
          const resetUrl: string =
            params["org.matrix.cross_signing_reset"]?.url ??
            "https://account.matrix.org/account/?action=org.matrix.cross_signing_reset";

          process.stderr.write(
            `\n⚠️  matrix.org requires browser approval for cross-signing reset.\n` +
            `\n   Bot account: ${userId}\n` +
            `   1. Open a browser and log in as ${userId}\n` +
            `      (same password you just provided)\n` +
            `   2. Visit this URL:\n` +
            `      ${resetUrl}\n` +
            `   3. Approve the "Reset cross-signing" prompt\n` +
            `   4. Come back here and press Enter...\n`
          );
          await promptSecret("");

          console.error("  UIA: submitting org.matrix.cross_signing_reset...");
          await makeRequest({ type: "org.matrix.cross_signing_reset" });
          console.error("  UIA: accepted.");
        }
      },
    });

    const csStatus = await crypto.getCrossSigningStatus();
    console.error("  Cross-signing status:", JSON.stringify(csStatus));

    if (!csStatus.publicKeysOnDevice) {
      throw new Error("Cross-signing public keys not present after bootstrap. Setup failed.");
    }

    // Step 9: Bootstrap SSSS — encrypts and stores the new cross-signing keys
    // under the generated recovery key. This is what allows future re-import.
    console.error("\nBootstrapping secret storage (new SSSS)...");
    await crypto.bootstrapSecretStorage({
      createSecretStorageKey: async () => ({
        keyInfo: {},
        privateKey: newPrivateKey,
      }),
      setupNewSecretStorage: true,
      setupNewKeyBackup: false,
    });
    console.error("  SSSS bootstrapped.");

    // Step 10: Load SSK from SSSS into the OlmMachine local cache.
    // bootstrapCrossSigning creates keys on the server and stores them in SSSS,
    // but does NOT cache the private keys locally. crossSignDevice() needs the
    // SSK in the local crypto store — same issue cross-sign.ts solved for @chrislyons.
    // preImportDelayMs: 2000 — the OlmMachine needs time to process the public
    // keys downloaded by bootstrapCrossSigning before it can verify the import.
    console.error("\nLoading cross-signing private keys from SSSS...");
    await bootstrapAndImportCrossSigningKeys(client, {
      requiredKey: "selfSigning",
      preImportDelayMs: 2000,
    });

    // Step 11: Re-download device list AFTER import — the import may reset internal
    // device tracking state in the OlmMachine. crossSignDevice() needs the target
    // device in the OlmMachine store, not just the public key download cache.
    console.error(`\nRefreshing device list post-import...`);
    const deviceMap = await crypto.getUserDeviceInfo([userId], true);
    const knownDevices = deviceMap.get(userId);
    const deviceIds = knownDevices ? [...knownDevices.keys()] : [];
    console.error(`  Devices visible to OlmMachine: ${deviceIds.join(", ") || "(none)"}`);

    if (!deviceIds.includes(panDeviceId)) {
      console.error(`  Warning: ${panDeviceId} not yet in device map, waiting 5s...`);
      await new Promise((r) => setTimeout(r, 5000));
      const retryMap = await crypto.getUserDeviceInfo([userId], true);
      const retryDevices = retryMap.get(userId);
      const retryIds = retryDevices ? [...retryDevices.keys()] : [];
      console.error(`  Retry device list: ${retryIds.join(", ") || "(none)"}`);
      if (!retryIds.includes(panDeviceId)) {
        throw new Error(
          `Device ${panDeviceId} not visible after two downloads. ` +
          `Device may have been removed from the server, or the server needs more time to propagate.`
        );
      }
    }

    // Step 12: Sign the Pantalaimon device with the bot's SSK
    console.error(`\nSigning Pantalaimon device ${panDeviceId}...`);
    await new Promise((r) => setTimeout(r, 1000));
    await crypto.crossSignDevice(panDeviceId);
    console.log(`  ✓ Device ${panDeviceId} signed.`);

    // Print recovery key to stderr so it appears distinct from script output
    process.stderr.write(
      `\n┌─────────────────────────────────────────────────────────────┐\n` +
      `│  RECOVERY KEY for ${userId}\n` +
      `│\n` +
      `│  ${encodedRecoveryKey}\n` +
      `│\n` +
      `│  Store in age-encrypted credentials on Blackbox.           │\n` +
      `│  Required to re-run setup-bot or recover cross-signing.    │\n` +
      `└─────────────────────────────────────────────────────────────┘\n\n`
    );

    console.log(`\n✓ Setup complete for ${userId}`);
    console.log(`  Cross-signing keys (MSK/SSK/USK): created`);
    console.log(`  SSSS: initialized with new recovery key`);
    console.log(`  Pantalaimon device ${panDeviceId}: signed`);
    console.log(`\n  Next step: run trust-users to sign this bot's MSK with @chrislyons's USK.`);
  } finally {
    await cleanupClient(client, `setup-bot(${userId})`);
  }
}
