/**
 * Canonical JSON (Matrix spec section 11.1).
 *
 * Recursively sorts object keys. Required for reproducible ed25519 signatures.
 */

export function canonicalJson(obj: unknown): string {
  if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) return "[" + obj.map(canonicalJson).join(",") + "]";
  const keys = Object.keys(obj as Record<string, unknown>).sort();
  return (
    "{" +
    keys
      .map((k) => `${JSON.stringify(k)}:${canonicalJson((obj as any)[k])}`)
      .join(",") +
    "}"
  );
}
