/**
 * Trust users command — signs bot MSKs with @chrislyons USK.
 *
 * Logs in as @chrislyons, reads the USK private key from SSSS, then manually
 * signs each bot's MSK using Node.js ed25519 and uploads via /keys/signatures/upload.
 *
 * Bypasses WASM olmMachine.getIdentity() entirely — the tsx ESM/CJS split causes
 * a different UserId class to be loaded than what the OlmMachine expects, breaking
 * instanceof checks. Node.js crypto.sign('ed25519') is equivalent and reliable.
 */

import * as sdk from "matrix-js-sdk";
import { decodeRecoveryKey } from "matrix-js-sdk/lib/crypto-api";
import { HOMESERVER, CHRIS_USER, BOT_USERS } from "../utils/constants";
import { getCredential } from "../utils/credential-helpers";
import { matrixRequest } from "../utils/http-helpers";
import { cleanupClient } from "../utils/client-lifecycle";
import { canonicalJson } from "../utils/canonical-json";
import { startAndSync } from "../utils/matrix-client-utils";

export async function run(): Promise<void> {
  console.error("\n── Signing bot MSKs with @chrislyons USK ──");

  const password = await getCredential("MATRIX_PASSWORD", "Password for @chrislyons:matrix.org: ");
  const recoveryKey = await getCredential("MATRIX_RECOVERY_KEY", "Recovery key (base58): ");
  const decodedKey = decodeRecoveryKey(recoveryKey);

  const bareClient = sdk.createClient({ baseUrl: HOMESERVER });
  console.error("Logging in as @chrislyons...");
  const loginResp = await bareClient.login("m.login.password", {
    user: CHRIS_USER,
    password,
    initial_device_display_name: "bot-trust-setup (temporary)",
  });
  console.error(`  Device: ${loginResp.device_id}`);
  const chrisToken = loginResp.access_token;

  const client = sdk.createClient({
    baseUrl: HOMESERVER,
    userId: CHRIS_USER,
    deviceId: loginResp.device_id,
    accessToken: chrisToken,
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

    // Unlock SSSS and read the USK private key bytes
    console.error("Loading USK from SSSS...");
    await client.getCrypto()!.bootstrapSecretStorage({
      createSecretStorageKey: async () => {
        throw new Error("Refusing to create new storage — using existing");
      },
      setupNewSecretStorage: false,
      setupNewKeyBackup: false,
    });
    const uskBase64 = await client.secretStorage.get("m.cross_signing.user_signing");
    if (!uskBase64) throw new Error("USK not found in SSSS — wrong recovery key?");

    // Import USK bytes as a Node.js ed25519 private key for signing.
    // JWK requires both d (private) and x (public). Use PKCS#8 DER instead —
    // only needs the 32-byte seed plus a fixed 16-byte ASN.1 header.
    // Header encodes: SEQUENCE { version=0, AlgorithmIdentifier(OID 1.3.101.112), PrivateKey }
    const { createPrivateKey, sign: nodeCryptoSign } = await import("node:crypto");
    const uskBytes = Buffer.from(uskBase64.replace(/=+$/, ""), "base64");
    const PKCS8_ED25519_HEADER = Buffer.from("302e020100300506032b657004220420", "hex");
    const signingKey = createPrivateKey({
      format: "der",
      type: "pkcs8",
      key: Buffer.concat([PKCS8_ED25519_HEADER, uskBytes]),
    });
    console.error(`  USK loaded (${uskBytes.length} bytes).`);

    // Query /keys/query for all users to get MSKs and Chris's USK key ID
    console.error("\nQuerying key server...");
    const keysData = await matrixRequest(
      "POST", "/_matrix/client/v3/keys/query", chrisToken,
      { device_keys: Object.fromEntries([CHRIS_USER, ...BOT_USERS].map((u) => [u, []])) }
    );

    const chrisUSK = keysData.user_signing_keys?.[CHRIS_USER];
    const uskKeyId = chrisUSK
      ? Object.keys(chrisUSK.keys ?? {}).find((k: string) => k.startsWith("ed25519:"))
      : null;
    if (!uskKeyId) throw new Error("Chris's USK public key not found in /keys/query — query must use @chrislyons token");

    console.error(`  USK key ID: ${uskKeyId}`);

    // Sign each bot's MSK with the USK and upload
    const results: Array<{ userId: string; success: boolean; error?: string }> = [];

    for (const botUserId of BOT_USERS) {
      console.error(`\nTrusting ${botUserId}...`);
      try {
        const botMSK = keysData.master_keys?.[botUserId];
        if (!botMSK) throw new Error("No MSK found — run setup-bot first");

        const mskKeyId = Object.keys(botMSK.keys ?? {}).find((k: string) => k.startsWith("ed25519:"));
        if (!mskKeyId) throw new Error("MSK has no ed25519 key");

        // Canonical JSON of MSK without existing signatures (Matrix spec §11.1)
        const { signatures: _sigs, ...mskBody } = botMSK;
        const canonical = canonicalJson(mskBody);

        // Sign with USK
        const sig = nodeCryptoSign(null, Buffer.from(canonical), signingKey);
        const sig64 = sig.toString("base64");

        // Upload signature
        await matrixRequest(
          "POST", "/_matrix/client/v3/keys/signatures/upload", chrisToken,
          {
            [botUserId]: {
              [mskKeyId]: {
                ...botMSK,
                signatures: {
                  ...(botMSK.signatures ?? {}),
                  [CHRIS_USER]: { [uskKeyId]: sig64 },
                },
              },
            },
          }
        );

        console.log(`  ✓ Trusted: ${botUserId}`);
        results.push({ userId: botUserId, success: true });
      } catch (err: any) {
        console.error(`  ✗ Failed: ${botUserId} — ${err.message}`);
        results.push({ userId: botUserId, success: false, error: err.message });
      }
    }

    console.log("\n── Trust Results ──────────────────────────────────────────────");
    for (const r of results) {
      console.log(`  ${r.success ? "✓" : "✗"} ${r.userId}${r.error ? ` — ${r.error}` : ""}`);
    }
    const succeeded = results.filter((r) => r.success).length;
    console.log(`\n${succeeded}/${results.length} bots trusted.`);

    if (succeeded < results.length) {
      const failed = results.filter((r) => !r.success).map((r) => r.userId);
      console.log(`\nFailed bots: ${failed.join(", ")}`);
      console.log("Ensure each failed bot has cross-signing set up (run setup-bot first).");
    }
  } finally {
    await cleanupClient(client, "trust-users");
  }
}
