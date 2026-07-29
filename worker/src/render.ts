/**
 * Validation and rendering for digest content.
 *
 * The Worker renders the email rather than accepting ready-made HTML from CI.
 * That is the point: even with a valid OIDC token, the pipeline can only supply
 * *data*, and every field is escaped and bounded here. A compromised workflow
 * cannot inject markup, scripts, or off-site links into mail that carries our
 * domain's DKIM signature.
 */

import { escapeHtml } from "./http";

// Bill links may only point at the legislature. This is the control that stops
// a compromised pipeline from turning the digest into a phishing campaign.
const ALLOWED_LINK_HOSTS = new Set(["legislature.mi.gov", "www.legislature.mi.gov"]);

const MAX_BILLS = 500;
const MAX_NAME_LENGTH = 300;
const MAX_STATUS_LENGTH = 100;
const MAX_SUMMARY_LENGTH = 4000;

export interface DigestBill {
  name: string;
  status: string;
  sourceUrl: string | null;
  summary: string | null;
}

export interface DigestPayload {
  date: string;
  bills: DigestBill[];
}

function clampString(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
}

function safeUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2048) return null;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (!ALLOWED_LINK_HOSTS.has(parsed.hostname.toLowerCase())) return null;
  return parsed.toString();
}

export type ParseResult =
  | { ok: true; value: DigestPayload }
  | { ok: false; error: string };

export function parseDigestPayload(raw: unknown): ParseResult {
  if (typeof raw !== "object" || raw === null) return { ok: false, error: "body must be an object" };
  const body = raw as Record<string, unknown>;

  const date = body.date;
  if (typeof date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return { ok: false, error: "date must be YYYY-MM-DD" };
  }

  if (!Array.isArray(body.bills)) return { ok: false, error: "bills must be an array" };
  if (body.bills.length > MAX_BILLS) return { ok: false, error: "too many bills" };

  const bills: DigestBill[] = [];
  for (const entry of body.bills) {
    if (typeof entry !== "object" || entry === null) continue;
    const bill = entry as Record<string, unknown>;
    const name = clampString(bill.name, MAX_NAME_LENGTH);
    const status = clampString(bill.status, MAX_STATUS_LENGTH);
    // A bill with no name or status is unrenderable; drop it rather than
    // emitting a blank row.
    if (!name || !status) continue;
    bills.push({
      name,
      status,
      sourceUrl: safeUrl(bill.source_url),
      summary: clampString(bill.summary, MAX_SUMMARY_LENGTH),
    });
  }

  return { ok: true, value: { date, bills } };
}

function groupByStatus(bills: DigestBill[]): Map<string, DigestBill[]> {
  const grouped = new Map<string, DigestBill[]>();
  for (const bill of bills) {
    const bucket = grouped.get(bill.status);
    if (bucket) bucket.push(bill);
    else grouped.set(bill.status, [bill]);
  }
  return grouped;
}

export function digestSubject(payload: DigestPayload): string {
  const count = payload.bills.length;
  const noun = count === 1 ? "bill" : "bills";
  return `Michigan legislature: ${count} ${noun} on ${payload.date}`;
}

export function renderDigestHtml(
  payload: DigestPayload,
  links: { siteUrl: string; unsubscribeUrl: string },
): string {
  const sections: string[] = [];
  for (const [status, bills] of groupByStatus(payload.bills)) {
    const articles = bills
      .map((bill) => {
        const title = bill.sourceUrl
          ? `<a href="${escapeHtml(bill.sourceUrl)}" style="color:#1a4d8f;">${escapeHtml(bill.name)}</a>`
          : escapeHtml(bill.name);
        const summary = bill.summary
          ? escapeHtml(bill.summary)
          : "<em>No summary available.</em>";
        return `<div style="margin:0 0 1.25rem 0;">
  <div style="font-weight:bold;font-size:15px;">${title}</div>
  <div style="margin-top:.35rem;white-space:pre-wrap;">${summary}</div>
</div>`;
      })
      .join("\n");
    sections.push(
      `<h2 style="font-size:16px;border-bottom:1px solid #ddd;padding-bottom:.25rem;margin-top:1.75rem;">${escapeHtml(status)}</h2>\n${articles}`,
    );
  }

  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>${escapeHtml(digestSubject(payload))}</title></head>
<body style="font-family:Georgia,serif;line-height:1.55;color:#222;max-width:640px;margin:0 auto;padding:1.5rem;">
<h1 style="font-size:19px;">Michigan bills &middot; ${escapeHtml(payload.date)}</h1>
${sections.join("\n")}
<hr style="margin-top:2rem;border:none;border-top:1px solid #ddd;">
<p style="color:#666;font-size:12px;">
Summaries are AI-generated and may contain errors. Always read the bill text.<br>
<a href="${escapeHtml(links.siteUrl)}" style="color:#666;">View on the web</a> &middot;
<a href="${escapeHtml(links.unsubscribeUrl)}" style="color:#666;">Unsubscribe</a>
</p>
</body>
</html>`;
}

export function renderDigestText(
  payload: DigestPayload,
  links: { siteUrl: string; unsubscribeUrl: string },
): string {
  const lines = [`Michigan bills - ${payload.date}`, ""];
  for (const [status, bills] of groupByStatus(payload.bills)) {
    lines.push(status.toUpperCase(), "-".repeat(status.length), "");
    for (const bill of bills) {
      lines.push(bill.name);
      if (bill.sourceUrl) lines.push(bill.sourceUrl);
      lines.push(bill.summary ?? "No summary available.", "");
    }
  }
  lines.push(
    "---",
    "Summaries are AI-generated and may contain errors.",
    `Web: ${links.siteUrl}`,
    `Unsubscribe: ${links.unsubscribeUrl}`,
  );
  return lines.join("\n");
}

export function renderConfirmEmail(confirmUrl: string): { html: string; text: string } {
  const safe = escapeHtml(confirmUrl);
  return {
    html: `<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Confirm your subscription</title></head>
<body style="font-family:Georgia,serif;line-height:1.55;color:#222;max-width:560px;margin:0 auto;padding:1.5rem;">
<h1 style="font-size:18px;">Confirm your subscription</h1>
<p>Somebody (hopefully you) asked for a daily digest of Michigan legislature activity at this address.</p>
<p><a href="${safe}" style="color:#1a4d8f;">Confirm this subscription</a></p>
<p style="color:#666;font-size:12px;">This link expires in 24 hours and can be used once.
If you did not request this, ignore this email &mdash; nothing will be sent and the
address will be dropped.</p>
</body>
</html>`,
    text: [
      "Confirm your subscription",
      "",
      "Somebody (hopefully you) asked for a daily digest of Michigan legislature",
      "activity at this address. To start receiving it, open this link:",
      "",
      confirmUrl,
      "",
      "The link expires in 24 hours and can be used once. If you did not request",
      "this, ignore this email - nothing will be sent and the address will be dropped.",
    ].join("\n"),
  };
}
