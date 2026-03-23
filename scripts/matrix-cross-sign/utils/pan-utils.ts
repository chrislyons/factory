/**
 * Pantalaimon database utilities.
 *
 * Queries the pan.db SQLite database on Whitebox via SSH
 * to resolve device IDs managed by Pantalaimon.
 */

import { execSync } from "node:child_process";

const PAN_DB_PATH = "/Users/nesbitt/.local/share/pantalaimon/pan.db";

export function getPanDeviceId(userId: string): string {
  const dbResult = execSync(
    `ssh whitebox "python3 -c \\"` +
    `import sqlite3; ` +
    `conn=sqlite3.connect('${PAN_DB_PATH}'); ` +
    `cur=conn.cursor(); ` +
    `cur.execute('SELECT device_id FROM accounts WHERE user_id=?', ('${userId}',)); ` +
    `row=cur.fetchone(); ` +
    `print(row[0] if row else ''); ` +
    `conn.close()` +
    `\\""`,
    { stdio: ["pipe", "pipe", "pipe"], timeout: 10_000 }
  ).toString().trim();

  if (!dbResult) {
    throw new Error(`No account found in pan.db for ${userId}`);
  }

  return dbResult;
}
