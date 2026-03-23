/**
 * HTTP request helpers for Matrix Client-Server API.
 */

import { HOMESERVER } from "./constants";

export async function matrixRequest(
  method: string,
  path: string,
  token: string,
  body?: object
): Promise<any> {
  const response = await fetch(`${HOMESERVER}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    throw Object.assign(
      new Error(`${method} ${path} → ${response.status}: ${data.error || response.statusText}`),
      { data }
    );
  }
  return data;
}
