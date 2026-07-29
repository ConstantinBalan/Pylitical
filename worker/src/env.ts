export interface Env {
  DB: D1Database;

  SUBSCRIBE_IP_LIMIT: RateLimit;
  SUBSCRIBE_EMAIL_LIMIT: RateLimit;
  TOKEN_IP_LIMIT: RateLimit;

  // Secrets, set via `wrangler secret put`.
  RESEND_API_KEY: string;
  TURNSTILE_SECRET_KEY: string;
  // HMAC key backing derived unsubscribe tokens. Rotating it invalidates every
  // outstanding unsubscribe link, so treat rotation as a deliberate act.
  UNSUBSCRIBE_SIGNING_KEY: string;

  // Plain vars from wrangler.jsonc.
  SITE_ORIGIN: string;
  API_ORIGIN: string;
  MAIL_FROM: string;
  MAIL_REPLY_TO: string;
  GITHUB_REPOSITORY: string;
  GITHUB_REF: string;
  MAX_CONFIRM_EMAILS_PER_DAY: string;
  MAX_DIGEST_EMAILS_PER_DAY: string;
  MAX_SUBSCRIBERS: string;
}

export function intVar(value: string, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
