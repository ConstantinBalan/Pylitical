/** Cloudflare Turnstile server-side verification. */

const VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

// Turnstile tokens are ~2KB at most; anything larger is not worth forwarding.
const MAX_TOKEN_LENGTH = 4096;

interface SiteVerifyResponse {
  success: boolean;
  "error-codes"?: string[];
}

/**
 * Verifies the client-side widget response. Passing `remoteIp` lets Cloudflare
 * bind the solve to the requesting address, and `idempotencyKey` means a
 * retried request re-verifies rather than being rejected as a token replay.
 *
 * Fails closed: any network or parse error is treated as a failed challenge.
 */
export async function verifyTurnstile(
  token: unknown,
  secret: string,
  remoteIp: string,
): Promise<boolean> {
  if (typeof token !== "string" || token.length === 0 || token.length > MAX_TOKEN_LENGTH) {
    return false;
  }

  const form = new FormData();
  form.append("secret", secret);
  form.append("response", token);
  if (remoteIp !== "unknown") form.append("remoteip", remoteIp);
  form.append("idempotency_key", crypto.randomUUID());

  try {
    const response = await fetch(VERIFY_URL, { method: "POST", body: form });
    if (!response.ok) return false;
    const result = (await response.json()) as SiteVerifyResponse;
    return result.success === true;
  } catch {
    return false;
  }
}
