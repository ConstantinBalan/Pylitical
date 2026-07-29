/** Resend transport. Addresses are never written to logs. */

import type { Env } from "./env";

const SEND_URL = "https://api.resend.com/emails";
const BATCH_URL = "https://api.resend.com/emails/batch";

export const BATCH_MAX = 100;

export interface OutboundEmail {
  to: string;
  subject: string;
  html: string;
  text: string;
  headers?: Record<string, string>;
}

function payload(env: Env, email: OutboundEmail): Record<string, unknown> {
  const body: Record<string, unknown> = {
    from: env.MAIL_FROM,
    to: [email.to],
    subject: email.subject,
    html: email.html,
    text: email.text,
  };
  if (env.MAIL_REPLY_TO) body.reply_to = env.MAIL_REPLY_TO;
  if (email.headers) body.headers = email.headers;
  return body;
}

/**
 * One-click unsubscribe headers (RFC 8058). Gmail and Yahoo surface these as a
 * native "Unsubscribe" control, which materially reduces the odds a reader
 * reaches for "mark as spam" instead -- the single worst outcome for a small
 * sending domain's reputation.
 */
export function unsubscribeHeaders(apiOrigin: string, token: string): Record<string, string> {
  const url = `${apiOrigin}/unsubscribe?t=${encodeURIComponent(token)}`;
  return {
    "List-Unsubscribe": `<${url}>`,
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
  };
}

export async function sendOne(env: Env, email: OutboundEmail): Promise<boolean> {
  try {
    const response = await fetch(SEND_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload(env, email)),
    });
    if (!response.ok) {
      // Status only -- the body can echo the recipient address.
      console.error("resend_send_failed", { status: response.status });
      return false;
    }
    return true;
  } catch (error) {
    console.error("resend_send_error", { name: (error as Error).name });
    return false;
  }
}

/** Sends up to BATCH_MAX messages in one call. Returns true if accepted. */
export async function sendBatch(env: Env, emails: OutboundEmail[]): Promise<boolean> {
  if (emails.length === 0) return true;
  if (emails.length > BATCH_MAX) throw new Error("batch too large");

  try {
    const response = await fetch(BATCH_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(emails.map((email) => payload(env, email))),
    });
    if (!response.ok) {
      console.error("resend_batch_failed", {
        status: response.status,
        size: emails.length,
      });
      return false;
    }
    return true;
  } catch (error) {
    console.error("resend_batch_error", { name: (error as Error).name });
    return false;
  }
}
