/** CSPRNG tokens, stored only as hashes. */

const TOKEN_BYTES = 32; // 256 bits; base64url-encodes to 43 chars.
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export function generateToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(TOKEN_BYTES));
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

/**
 * Only the hash is ever persisted, so a leaked database snapshot cannot be
 * replayed against /confirm or /unsubscribe. SHA-256 with no salt or stretching
 * is right here: the input is 256 bits of entropy, not a guessable password.
 */
export async function hashToken(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Cheap shape check so malformed input never reaches a query. */
export function isWellFormedToken(value: string | null): value is string {
  return typeof value === "string" && TOKEN_PATTERN.test(value);
}

export function timingSafeEqual(a: string, b: string): boolean {
  const left = new TextEncoder().encode(a);
  const right = new TextEncoder().encode(b);
  if (left.byteLength !== right.byteLength) return false;
  let diff = 0;
  for (let i = 0; i < left.byteLength; i += 1) {
    diff |= left[i]! ^ right[i]!;
  }
  return diff === 0;
}
