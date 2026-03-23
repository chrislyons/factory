/**
 * Shared constants for Matrix bot trust management.
 */

export const HOMESERVER = "https://matrix.org";
export const CHRIS_USER = "@chrislyons:matrix.org";
export const BOT_USERS = [
  "@boot.industries:matrix.org",
  "@ig88bot:matrix.org",
  "@sir.kelk:matrix.org",
  "@coord:matrix.org",
] as const;

export const BOT_AGENT_NAMES: Record<string, string> = {
  "@boot.industries:matrix.org": "boot",
  "@ig88bot:matrix.org": "ig88",
  "@sir.kelk:matrix.org": "kelk",
  "@coord:matrix.org": "coord",
};
