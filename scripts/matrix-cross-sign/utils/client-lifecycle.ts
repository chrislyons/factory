/**
 * Matrix SDK client lifecycle helpers.
 */

import type { MatrixClient } from "matrix-js-sdk";

export async function cleanupClient(client: MatrixClient, label: string): Promise<void> {
  try {
    client.stopClient();
    await client.logout(true);
    console.error(`${label}: temp device removed.`);
  } catch (err: any) {
    console.error(`Warning: ${label} cleanup failed — ${err.message}`);
    console.error("Check Element settings for orphaned 'bot-trust-setup (temporary)' device.");
  }
}
