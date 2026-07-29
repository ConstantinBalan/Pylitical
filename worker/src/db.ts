/**
 * D1 access. Every statement is prepared with bound parameters -- no string
 * interpolation reaches SQL anywhere in this file.
 */

// RFC 5321 caps the whole address at 254 and the local part at 64.
const MAX_EMAIL_LENGTH = 254;
const MAX_LOCAL_LENGTH = 64;
// Deliberately stricter than RFC 5322: no quoted strings, no comments, no
// whitespace, no control characters. Anything exotic enough to fail this is
// not worth the parsing surface.
const EMAIL_PATTERN = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/;

export type SubscriberStatus = "pending" | "confirmed" | "unsubscribed";

export interface Subscriber {
  id: number;
  email: string;
  status: SubscriberStatus;
  confirm_expires_at: number | null;
  last_confirm_sent_at: number | null;
}

/** Returns the normalized address, or null if it is not one we will accept. */
export function normalizeEmail(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const email = raw.trim().toLowerCase();
  if (email.length === 0 || email.length > MAX_EMAIL_LENGTH) return null;
  // Control characters would be inert against Resend's JSON API, but rejecting
  // them keeps the value safe for any future SMTP-shaped consumer (where a
  // bare CR/LF is header injection).
  if (/[\u0000-\u001F\u007F]/.test(email)) return null;
  if (!EMAIL_PATTERN.test(email)) return null;
  const [local] = email.split("@") as [string];
  if (local.length > MAX_LOCAL_LENGTH) return null;
  if (email.includes("..")) return null;
  return email;
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export function utcDay(): string {
  return new Date().toISOString().slice(0, 10);
}

export async function findByEmail(db: D1Database, email: string): Promise<Subscriber | null> {
  return db
    .prepare(
      `SELECT id, email, status, confirm_expires_at, last_confirm_sent_at
         FROM subscribers WHERE email = ?`,
    )
    .bind(email)
    .first<Subscriber>();
}

export async function countSubscribers(db: D1Database): Promise<number> {
  const row = await db
    .prepare(`SELECT COUNT(*) AS total FROM subscribers WHERE status != 'unsubscribed'`)
    .first<{ total: number }>();
  return row?.total ?? 0;
}

/** Creates or re-arms a pending signup. Only the confirm token's hash lands here. */
export async function upsertPending(
  db: D1Database,
  args: { email: string; confirmTokenHash: string; expiresAt: number },
): Promise<void> {
  const ts = nowSeconds();
  await db
    .prepare(
      `INSERT INTO subscribers (
           email, status, confirm_token_hash, confirm_expires_at,
           created_at, last_confirm_sent_at
       ) VALUES (?, 'pending', ?, ?, ?, ?)
       ON CONFLICT(email) DO UPDATE SET
           status               = 'pending',
           confirm_token_hash   = excluded.confirm_token_hash,
           confirm_expires_at   = excluded.confirm_expires_at,
           last_confirm_sent_at = excluded.last_confirm_sent_at,
           unsubscribed_at      = NULL`,
    )
    .bind(args.email, args.confirmTokenHash, args.expiresAt, ts, ts)
    .run();
}

/**
 * Redeems a confirm token. The UPDATE itself enforces single-use and expiry in
 * one atomic statement -- checking first and updating after would leave a race
 * where a token could be redeemed twice.
 */
export async function confirmByTokenHash(
  db: D1Database,
  tokenHash: string,
): Promise<{ id: number; email: string } | null> {
  const ts = nowSeconds();
  const row = await db
    .prepare(
      `UPDATE subscribers
          SET status = 'confirmed',
              confirmed_at = ?,
              confirm_token_hash = NULL,
              confirm_expires_at = NULL
        WHERE confirm_token_hash = ?
          AND status = 'pending'
          AND confirm_expires_at > ?
        RETURNING id, email`,
    )
    .bind(ts, tokenHash, ts)
    .first<{ id: number; email: string }>();
  return row ?? null;
}

/** Idempotent: unsubscribing an already-unsubscribed row still reports success. */
export async function unsubscribeById(db: D1Database, id: number): Promise<boolean> {
  const row = await db
    .prepare(
      `UPDATE subscribers
          SET status = 'unsubscribed',
              unsubscribed_at = COALESCE(unsubscribed_at, ?),
              confirm_token_hash = NULL,
              confirm_expires_at = NULL
        WHERE id = ?
        RETURNING id`,
    )
    .bind(nowSeconds(), id)
    .first<{ id: number }>();
  return row !== null;
}

export async function subscriberExists(db: D1Database, id: number): Promise<boolean> {
  const row = await db
    .prepare(`SELECT id FROM subscribers WHERE id = ?`)
    .bind(id)
    .first<{ id: number }>();
  return row !== null;
}

export interface Recipient {
  id: number;
  email: string;
}

/**
 * Confirmed subscribers, keyset-paginated by id so a growing list never builds
 * an unbounded array in memory or a slow OFFSET scan.
 */
export async function pageConfirmed(
  db: D1Database,
  afterId: number,
  limit: number,
): Promise<Recipient[]> {
  const { results } = await db
    .prepare(
      `SELECT id, email
         FROM subscribers
        WHERE status = 'confirmed' AND id > ? AND bounce_count < 3
        ORDER BY id
        LIMIT ?`,
    )
    .bind(afterId, limit)
    .all<Recipient>();
  return results ?? [];
}

/**
 * Increments a daily counter and reports whether it is still within budget.
 * This is the circuit breaker: it bounds total outbound mail per day even if
 * every other control is bypassed.
 */
export async function consumeDailyBudget(
  db: D1Database,
  name: string,
  max: number,
  amount = 1,
): Promise<boolean> {
  const row = await db
    .prepare(
      `INSERT INTO daily_counters (day, name, value) VALUES (?, ?, ?)
       ON CONFLICT(day, name) DO UPDATE SET value = value + excluded.value
       RETURNING value`,
    )
    .bind(utcDay(), name, amount)
    .first<{ value: number }>();
  return (row?.value ?? Number.MAX_SAFE_INTEGER) <= max;
}

/** Claims a digest date. Returns false if that date was already mailed. */
export async function claimDigestDate(
  db: D1Database,
  digestDate: string,
  billCount: number,
): Promise<boolean> {
  const row = await db
    .prepare(
      `INSERT INTO sent_digests (digest_date, sent_at, recipient_count, bill_count)
       VALUES (?, ?, 0, ?)
       ON CONFLICT(digest_date) DO NOTHING
       RETURNING digest_date`,
    )
    .bind(digestDate, nowSeconds(), billCount)
    .first<{ digest_date: string }>();
  return row !== null;
}

export async function recordDigestRecipients(
  db: D1Database,
  digestDate: string,
  recipientCount: number,
): Promise<void> {
  await db
    .prepare(`UPDATE sent_digests SET recipient_count = ? WHERE digest_date = ?`)
    .bind(recipientCount, digestDate)
    .run();
}
