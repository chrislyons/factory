#!/usr/bin/env tsx
/**
 * Matrix Bot E2EE Trust Setup (BKX065)
 *
 * Three-step process to establish E2EE trust for Matrix agent bots:
 *   Layer 1: Bootstrap MSK/SSK/USK cross-signing for each bot account
 *   Layer 2: Sign each bot's Pantalaimon device with its own SSK
 *   Layer 3: Sign each bot's MSK with @chrislyons's USK
 *
 * Commands:
 *   npx tsx bot-trust.ts status [--token <token>]
 *   npx tsx bot-trust.ts setup-bot --user <userId>
 *   npx tsx bot-trust.ts sign-device --user <userId> --device <deviceId>
 *   npx tsx bot-trust.ts prune-devices --user <userId>
 *   npx tsx bot-trust.ts trust-users
 *
 * Bot credentials are fetched via SSH from Blackbox — no bot passwords needed
 * (primary path). Interactive password prompt is the fallback if /login/get_token
 * UIA is rejected by the homeserver.
 *
 * Environment (trust-users only):
 *   MATRIX_RECOVERY_KEY   @chrislyons recovery key (base58)
 *   MATRIX_PASSWORD       @chrislyons account password
 *   MATRIX_TOKEN          Access token for status command (optional)
 */

import "fake-indexeddb/auto";
import { parseArgs } from "node:util";
import { suppressMatrixSdkLogs } from "./utils/suppress-sdk-logs";
import { getBotPanToken } from "./utils/credential-helpers";
import { run as cmdStatus } from "./commands/cmd-status";
import { run as cmdSetupBot } from "./commands/cmd-setup-bot";
import { run as cmdSignDevice } from "./commands/cmd-sign-device";
import { run as cmdPruneDevices } from "./commands/cmd-prune-devices";
import { run as cmdTrustUsers } from "./commands/cmd-trust-users";
import { run as cmdSignAllDevices } from "./commands/cmd-sign-all-devices";
import { BOT_USERS } from "./utils/constants";

suppressMatrixSdkLogs();

// ── Help ────────────────────────────────────────────────────────

function printHelp(): void {
  console.log(`
Matrix Bot E2EE Trust Setup (BKX065)

Commands:
  status [--token <token>]              Show E2EE trust state for all accounts
  setup-bot --user <userId>             Bootstrap cross-signing for a bot account
  sign-device --user <userId>           Sign a device using existing SSSS keys
             --device <deviceId>        (no browser approval needed)
  prune-devices --user <userId>         Remove stale Pantalaimon devices
  trust-users                           Sign bot MSKs with @chrislyons's USK

Options:
  --user <userId>      Bot user ID (required for setup-bot / sign-device / prune-devices)
  --device <deviceId>  Device ID to sign (required for sign-device)

Environment (sign-device):
  MATRIX_RECOVERY_KEY  Bot recovery key (from setup-bot output)
  MATRIX_BOT_PASSWORD  Bot account password

Environment (trust-users):
  MATRIX_RECOVERY_KEY  @chrislyons recovery key (base58)
  MATRIX_PASSWORD      @chrislyons account password

Environment (status):
  MATRIX_TOKEN         Access token (optional; falls back to SSH bot token)

Run order:
  1. npx tsx bot-trust.ts status
  2. npx tsx bot-trust.ts setup-bot --user @boot.industries:matrix.org  # browser approval
  3. npx tsx bot-trust.ts setup-bot --user @ig88bot:matrix.org           # browser approval
  4. npx tsx bot-trust.ts setup-bot --user @sir.kelk:matrix.org          # browser approval
  5. MATRIX_RECOVERY_KEY=<key> MATRIX_PASSWORD=<pw> npx tsx bot-trust.ts trust-users
  6. npx tsx bot-trust.ts status  # verify all green

If sign step failed in setup-bot (device not in key server):
  ssh whitebox "launchctl stop com.pantalaimon && launchctl start com.pantalaimon"
  MATRIX_RECOVERY_KEY=<bot-key> MATRIX_BOT_PASSWORD=<pw> \\
    npx tsx bot-trust.ts sign-device --user <botUserId> --device <deviceId>

Security:
  Credentials are never logged or written to disk.
  Bot passwords are not required (primary path uses SSH + /login/get_token).
  Generated bot recovery keys are printed to stderr only — save them manually.
  After running: unset MATRIX_RECOVERY_KEY MATRIX_PASSWORD
`);
}

// ── Main Dispatcher ─────────────────────────────────────────────

async function main(): Promise<void> {
  const { values, positionals } = parseArgs({
    options: {
      user: { type: "string" },
      device: { type: "string" },
      token: { type: "string" },
      bot: { type: "string" },
      all: { type: "boolean" },
      help: { type: "boolean", short: "h" },
    },
    allowPositionals: true,
  });

  const command = positionals[0] ?? "";

  if (values.help || command === "") {
    printHelp();
    process.exit(command === "" ? 1 : 0);
  }

  if (command === "status") {
    const token = values.token || process.env.MATRIX_TOKEN;
    try {
      if (token) {
        await cmdStatus(token);
      } else {
        console.error("No --token or MATRIX_TOKEN, fetching coord Pantalaimon token via SSH...");
        const panToken = getBotPanToken("coord");
        await cmdStatus(panToken);
      }
    } catch (err: any) {
      console.error(`\nFatal: ${err.message}`);
      if (err.data) console.error("Server response:", JSON.stringify(err.data));
      process.exit(1);
    }
    return;
  }

  if (command === "setup-bot") {
    if (!values.user) {
      console.error("Error: --user <userId> is required for setup-bot");
      console.error("Example: npx tsx bot-trust.ts setup-bot --user @boot.industries:matrix.org");
      process.exit(1);
    }
    try {
      await cmdSetupBot(values.user);
    } catch (err: any) {
      console.error(`\nFatal: ${err.message}`);
      if (err.data) console.error("Server response:", JSON.stringify(err.data));
      process.exit(1);
    }
    return;
  }

  if (command === "prune-devices") {
    const pruneTargets = values.user ? [values.user] : [...BOT_USERS];
    for (const u of pruneTargets) {
      try {
        await cmdPruneDevices(u);
      } catch (err: any) {
        console.error(`\n✗ ${u}: ${err.message}`);
      }
    }
    return;
  }

  if (command === "sign-device") {
    if (!values.user) {
      console.error("Error: --user <userId> is required for sign-device");
      process.exit(1);
    }
    if (!values.device) {
      console.error("Error: --device <deviceId> is required for sign-device");
      console.error("Tip: run 'status' to find the device ID, or check /account/whoami output");
      process.exit(1);
    }
    try {
      await cmdSignDevice(values.user, values.device);
    } catch (err: any) {
      console.error(`\nFatal: ${err.message}`);
      if (err.data) console.error("Server response:", JSON.stringify(err.data));
      process.exit(1);
    }
    return;
  }

  if (command === "sign-all-devices") {
    try {
      await cmdSignAllDevices(values.user);
    } catch (err: any) {
      console.error(`\nFatal: ${err.message}`);
      if (err.data) console.error("Server response:", JSON.stringify(err.data));
      process.exit(1);
    }
    return;
  }

  if (command === "trust-users") {
    try {
      await cmdTrustUsers();
    } catch (err: any) {
      console.error(`\nFatal: ${err.message}`);
      if (err.data) console.error("Server response:", JSON.stringify(err.data));
      process.exit(1);
    }
    return;
  }

  console.error(`Unknown command: ${command}`);
  console.error("Use --help for usage information.");
  process.exit(1);
}

main();
