/**
 * Matrix client lifecycle utilities.
 *
 * Shared helpers for starting and syncing Matrix SDK clients
 * used by cross-sign.ts and bot-trust.ts.
 */

import * as sdk from "matrix-js-sdk";

export async function startAndSync(client: sdk.MatrixClient): Promise<void> {
  console.error("Starting sync...");
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error("Sync timeout after 60s — check network/homeserver")),
      60_000
    );
    client.once(sdk.ClientEvent.Sync, (state: string) => {
      clearTimeout(timeout);
      if (state === "PREPARED") {
        console.error("Sync ready.");
        resolve();
      } else {
        reject(new Error(`Unexpected sync state: ${state}`));
      }
    });
    client.startClient({ initialSyncLimit: 0 });
  });
}
