/**
 * Matrix cross-signing cryptographic utilities.
 *
 * Unified SSSS + cross-signing key import sequence extracted from
 * cross-sign.ts (bootstrapSecretStorage) and bot-trust.ts
 * (loadChrissCrossSigningKeys, cmdSetupBot, cmdSignDevice).
 *
 * CRITICAL: This code touches live Matrix device trust. Changes to retry
 * counts, delays, or key validation will silently produce invalid crypto
 * state. Do not modify without diffing against all call sites.
 */

import type { MatrixClient } from "matrix-js-sdk";

export interface CryptoBootstrapOptions {
  /**
   * If true, throw when cross-signing public keys are not available
   * after 5 attempts. If false, log a warning and continue (import
   * will likely fail, but the caller may want to attempt it anyway).
   */
  throwOnMissingPublicKeys?: boolean;

  /**
   * Which imported key to check for success:
   * - "selfSigning": checks hasSelfSigning (used for device signing flows)
   * - "userSigning": checks hasUserSigning (used for user trust flows)
   */
  requiredKey?: "selfSigning" | "userSigning";

  /**
   * Delay in ms before the first import attempt. The OlmMachine sometimes
   * needs time to process the public keys downloaded in an earlier step.
   * Default: 0 (no delay). cmdSetupBot uses 2000.
   */
  preImportDelayMs?: number;

  /**
   * If true, perform a secondary verification via getCrossSigningStatus()
   * after import attempts. Only cross-sign.ts uses this — the other call
   * sites throw immediately on import failure.
   */
  verifyViaCrossSigningStatus?: boolean;
}

/**
 * Downloads cross-signing public keys, unlocks SSSS with the recovery key
 * (via the client's cryptoCallbacks.getSecretStorageKey), reads the three
 * cross-signing private keys, and imports them into the Rust OlmMachine.
 *
 * The client MUST have been created with a `cryptoCallbacks.getSecretStorageKey`
 * that returns the correct recovery key, and `initRustCrypto()` + `startClient()`
 * must have been called before this function.
 */
export async function bootstrapAndImportCrossSigningKeys(
  client: MatrixClient,
  options: CryptoBootstrapOptions = {}
): Promise<void> {
  const {
    throwOnMissingPublicKeys = false,
    requiredKey = "selfSigning",
    preImportDelayMs = 0,
    verifyViaCrossSigningStatus = false,
  } = options;

  const crypto = client.getCrypto();
  if (!crypto) throw new Error("Crypto not initialized");

  const userId = client.getUserId()!;

  // ── Phase 1: Download cross-signing public keys ────────────
  // Force a /keys/query so the OlmMachine has the public keys.
  // Without these, importCrossSigningKeys silently fails (private
  // keys can't be verified against unknown public keys).
  //
  // The WASM backend processes key query responses asynchronously,
  // so we retry with a delay to ensure availability before import.
  console.error("Downloading cross-signing public keys from server...");
  await crypto.getUserDeviceInfo([userId], true);

  let publicKeysReady = false;
  for (let attempt = 1; attempt <= 5; attempt++) {
    const status = await crypto.getCrossSigningStatus();
    if (status.publicKeysOnDevice) {
      publicKeysReady = true;
      console.error(`  Public keys available (attempt ${attempt}).`);
      break;
    }
    if (attempt < 5) {
      console.error(`  Public keys not ready (attempt ${attempt}/5), waiting 2s...`);
      await new Promise((r) => setTimeout(r, 2000));
      await crypto.getUserDeviceInfo([userId], true);
    }
  }

  if (!publicKeysReady) {
    if (throwOnMissingPublicKeys) {
      throw new Error(
        "Cross-signing public keys not available after 5 attempts — " +
        "cross-signing may not be set up (run setup-bot first)."
      );
    }
    console.error(
      "WARNING: Cross-signing public keys not available after 5 attempts.\n" +
      "Cross-signing may not be set up, or may have been reset during\n" +
      "recovery key rotation. The import will likely fail."
    );
  }

  // ── Phase 2: Bootstrap SSSS access ─────────────────────────
  console.error("Bootstrapping secret storage with recovery key...");
  await crypto.bootstrapSecretStorage({
    createSecretStorageKey: async () => {
      throw new Error(
        "Refusing to create new secret storage — should use existing"
      );
    },
    setupNewSecretStorage: false,
    setupNewKeyBackup: false,
  });

  // ── Phase 3: Read cross-signing private keys from SSSS ─────
  console.error("Reading cross-signing private keys from SSSS...");
  const secretStorage = client.secretStorage;

  const masterKey = await secretStorage.get("m.cross_signing.master");
  const selfSigningKey = await secretStorage.get("m.cross_signing.self_signing");
  const userSigningKey = await secretStorage.get("m.cross_signing.user_signing");

  if (!masterKey || !selfSigningKey || !userSigningKey) {
    const missing = [
      !masterKey && "master",
      !selfSigningKey && "self_signing",
      !userSigningKey && "user_signing",
    ].filter(Boolean);
    throw new Error(
      `Cross-signing keys missing from SSSS: ${missing.join(", ")}. ` +
      "Recovery key may be for a different secret storage generation."
    );
  }

  // WASM importCrossSigningKeys requires unpadded base64 strings.
  // secretStorage.get() may return standard (padded) base64.
  const stripPadding = (s: string) => s.replace(/=+$/, "");
  const mk = stripPadding(masterKey);
  const ssk = stripPadding(selfSigningKey);
  const usk = stripPadding(userSigningKey);

  console.error(`  master: \u2713 (${mk.length} chars)  self_signing: \u2713 (${ssk.length} chars)  user_signing: \u2713 (${usk.length} chars)`);

  // ── Phase 4: Import into Rust crypto store ─────────────────
  // Access internal OlmMachine API — no public API exists for this
  // operation (bootstrapCrossSigning is the public path, and it fails
  // with signature verification errors when keys already exist).
  const olmMachine = (crypto as any).olmMachine;
  if (!olmMachine?.importCrossSigningKeys) {
    throw new Error(
      "Cannot access OlmMachine.importCrossSigningKeys — " +
      "matrix-js-sdk internal API may have changed (expected ~35.x)."
    );
  }

  if (preImportDelayMs > 0) {
    await new Promise((r) => setTimeout(r, preImportDelayMs));
  }

  console.error("Importing cross-signing keys into crypto store...");
  let importSuccess = false;

  for (let attempt = 1; attempt <= 3; attempt++) {
    const importResult = await olmMachine.importCrossSigningKeys(mk, ssk, usk);
    const result = {
      hasMaster: importResult?.hasMaster ?? false,
      hasSelfSigning: importResult?.hasSelfSigning ?? false,
      hasUserSigning: importResult?.hasUserSigning ?? false,
    };
    console.error(`  Import attempt ${attempt}:`, result);

    const succeeded = requiredKey === "userSigning"
      ? result.hasUserSigning
      : result.hasSelfSigning;

    if (succeeded) {
      importSuccess = true;
      break;
    }

    if (attempt < 3) {
      const keyName = requiredKey === "userSigning" ? "USK" : "SSK";
      console.error(`  ${keyName} not cached, waiting 3s...`);
      await new Promise((r) => setTimeout(r, 3000));
      await crypto.getUserDeviceInfo([userId], true);
    }
  }

  // ── Phase 5: Verification ──────────────────────────────────
  if (verifyViaCrossSigningStatus) {
    const crossSigningStatus = await crypto.getCrossSigningStatus();
    console.error("Cross-signing status:", JSON.stringify(crossSigningStatus));

    if (!importSuccess && !crossSigningStatus.privateKeysCachedLocally.selfSigningKey) {
      throw new Error(
        "Self-signing key not cached after 3 import attempts. " +
        "The keys from SSSS may not match the published public keys, " +
        "or cross-signing may have been reset during recovery key rotation."
      );
    }
  } else if (!importSuccess) {
    const keyName = requiredKey === "userSigning" ? "User-signing" : "Self-signing";
    throw new Error(
      `${keyName} key not cached after 3 import attempts. ` +
      "Keys from SSSS may not match published public keys."
    );
  }

  console.error("Cross-signing keys imported successfully.");
}
