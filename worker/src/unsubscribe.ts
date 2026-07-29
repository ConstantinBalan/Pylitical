/**
 * Stateless unsubscribe tokens: `<id>.<base64url(HMAC-SHA256(key, "<id>"))>`.
 *
 * Nothing about these is stored, so a leaked database dump yields no working
 * unsubscribe links. The signing key lives only in Worker secrets, and
 * rotating it invalidates every outstanding link in one move.
 */

import { timingSafeEqual } from "./tokens";

const MAX_TOKEN_LENGTH = 128;
const TOKEN_PATTERN = /^(\d{1,15})\.([A-Za-z0-9_-]{43})$/;

let cachedKey: CryptoKey | null = null;
let cachedKeyMaterial = "";

async function signingKey(secret: string): Promise<CryptoKey> {
  if (cachedKey && cachedKeyMaterial === secret) return cachedKey;
  cachedKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  cachedKeyMaterial = secret;
  return cachedKey;
}

async function signId(secret: string, id: number): Promise<string> {
  const key = await signingKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(String(id)));
  return btoa(String.fromCharCode(...new Uint8Array(signature)))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

export async function mintUnsubscribeToken(secret: string, id: number): Promise<string> {
  return `${id}.${await signId(secret, id)}`;
}

/** Returns the subscriber id if the signature checks out, otherwise null. */
export async function verifyUnsubscribeToken(
  secret: string,
  token: string | null,
): Promise<number | null> {
  if (typeof token !== "string" || token.length > MAX_TOKEN_LENGTH) return null;
  const match = TOKEN_PATTERN.exec(token);
  if (!match) return null;

  const id = Number.parseInt(match[1]!, 10);
  if (!Number.isSafeInteger(id) || id <= 0) return null;

  // Recompute rather than compare-then-parse, and compare in constant time.
  const expected = await signId(secret, id);
  return timingSafeEqual(expected, match[2]!) ? id : null;
}
