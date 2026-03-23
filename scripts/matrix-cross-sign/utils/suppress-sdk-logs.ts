/**
 * Suppress noisy Matrix SDK console output.
 *
 * Rust WASM crypto backend emits verbose traces through console.debug/warn
 * that can include key material and session tokens. Must be called before
 * any crypto operations begin.
 */

import { logger } from "matrix-js-sdk/lib/logger";

export function suppressMatrixSdkLogs(): void {
  logger.setLevel("error");

  const _origDebug = console.debug;
  const _origWarn = console.warn;
  const _origInfo = console.info;
  const _origLog = console.log;

  console.debug = (...args: unknown[]) => {
    const msg = String(args[0] ?? "");
    if (msg.includes("matrix_sdk") || msg.includes("IndexedDb")) return;
    _origDebug.apply(console, args);
  };
  console.info = (...args: unknown[]) => {
    const msg = String(args[0] ?? "");
    if (msg.includes("matrix_sdk") || msg.includes("IndexedDb")) return;
    _origInfo.apply(console, args);
  };
  console.log = (...args: unknown[]) => {
    const msg = String(args[0] ?? "");
    if (msg.includes("PerSessionKeyBackupDownloader")) return;
    _origLog.apply(console, args);
  };
  console.warn = (...args: unknown[]) => {
    const msg = String(args[0] ?? "");
    if (
      msg.includes("matrix_sdk") ||
      msg.includes("MatrixRTCSession") ||
      msg.includes("MEGOLM_UNKNOWN") ||
      msg.includes("Failed to process outgoing request") ||
      msg.includes("Failed to decrypt") ||
      msg.includes("PerSessionKeyBackupDownloader")
    ) return;
    _origWarn.apply(console, args);
  };
}
