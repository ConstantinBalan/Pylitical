import * as db from "./db";
import { BATCH_MAX, type OutboundEmail, sendBatch, sendOne, unsubscribeHeaders } from "./email";
import { type Env, intVar } from "./env";
import { clientIp, escapeHtml, htmlPage, json, preflight } from "./http";
import { verifyGitHubOidc } from "./oidc";
import {
  digestSubject,
  parseDigestPayload,
  renderConfirmEmail,
  renderDigestHtml,
  renderDigestText,
} from "./render";
import { generateToken, hashToken, isWellFormedToken } from "./tokens";
import { verifyTurnstile } from "./turnstile";
import { mintUnsubscribeToken, verifyUnsubscribeToken } from "./unsubscribe";

const MAX_SUBSCRIBE_BODY_BYTES = 8 * 1024;
const MAX_DIGEST_BODY_BYTES = 2 * 1024 * 1024;
const CONFIRM_TTL_SECONDS = 24 * 60 * 60;
const CONFIRM_COOLDOWN_SECONDS = 15 * 60;

/**
 * Identical for every outcome -- new address, already pending, already
 * confirmed, previously unsubscribed, or silently dropped for exceeding a
 * cap. Varying the response would turn this endpoint into an oracle for
 * "is this person subscribed?".
 */
const GENERIC_SUBSCRIBE_RESPONSE = {
  status: "accepted",
  message: "If that address still needs confirming, a confirmation link is on its way.",
};

async function readJsonBody(request: Request, maxBytes: number): Promise<unknown | null> {
  const contentType = (request.headers.get("Content-Type") ?? "").toLowerCase();
  if (!contentType.startsWith("application/json")) return null;

  const declared = Number.parseInt(request.headers.get("Content-Length") ?? "", 10);
  if (Number.isFinite(declared) && declared > maxBytes) return null;

  const text = await request.text();
  // Content-Length can lie or be absent under chunked encoding; re-check.
  if (text.length > maxBytes) return null;

  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function handleSubscribe(request: Request, env: Env): Promise<Response> {
  const ip = clientIp(request);

  // Browsers always send Origin on cross-origin POSTs, so a mismatch is a
  // cross-site submission. Absent Origin means a non-browser client, which
  // Turnstile still has to satisfy.
  const origin = request.headers.get("Origin");
  if (origin !== null && origin !== env.SITE_ORIGIN) {
    return json({ error: "forbidden_origin" }, { status: 403 });
  }

  const ipAllowed = await env.SUBSCRIBE_IP_LIMIT.limit({ key: ip });
  if (!ipAllowed.success) {
    return json({ error: "rate_limited" }, { status: 429, request, siteOrigin: env.SITE_ORIGIN });
  }

  const body = await readJsonBody(request, MAX_SUBSCRIBE_BODY_BYTES);
  if (body === null || typeof body !== "object") {
    return json({ error: "invalid_body" }, { status: 400, request, siteOrigin: env.SITE_ORIGIN });
  }
  const fields = body as Record<string, unknown>;

  const email = db.normalizeEmail(fields.email);
  // Address syntax is not a secret, so rejecting it plainly leaks nothing and
  // gives the user a usable error.
  if (!email) {
    return json({ error: "invalid_email" }, { status: 400, request, siteOrigin: env.SITE_ORIGIN });
  }

  // Key the per-address limiter on a hash so raw addresses stay out of the
  // rate limiter's key space.
  const emailKey = await hashToken(email);
  const emailAllowed = await env.SUBSCRIBE_EMAIL_LIMIT.limit({ key: emailKey });
  if (!emailAllowed.success) {
    return json({ error: "rate_limited" }, { status: 429, request, siteOrigin: env.SITE_ORIGIN });
  }

  const solved = await verifyTurnstile(fields.turnstile_token, env.TURNSTILE_SECRET_KEY, ip);
  if (!solved) {
    return json(
      { error: "challenge_failed" },
      { status: 403, request, siteOrigin: env.SITE_ORIGIN },
    );
  }

  const accepted = json(GENERIC_SUBSCRIBE_RESPONSE, {
    status: 202,
    request,
    siteOrigin: env.SITE_ORIGIN,
  });

  const existing = await db.findByEmail(env.DB, email);

  // Already subscribed: send nothing. Mailing "you're already signed up" would
  // hand an attacker a way to pester a known subscriber indefinitely.
  if (existing?.status === "confirmed") return accepted;

  // Authoritative cross-datacenter cooldown, unlike the rate limiter.
  const now = db.nowSeconds();
  if (existing?.last_confirm_sent_at && now - existing.last_confirm_sent_at < CONFIRM_COOLDOWN_SECONDS) {
    return accepted;
  }

  if (!existing) {
    const total = await db.countSubscribers(env.DB);
    if (total >= intVar(env.MAX_SUBSCRIBERS, 5000)) {
      console.error("subscriber_cap_reached", { total });
      return accepted;
    }
  }

  const withinBudget = await db.consumeDailyBudget(
    env.DB,
    "confirm_emails",
    intVar(env.MAX_CONFIRM_EMAILS_PER_DAY, 500),
  );
  if (!withinBudget) {
    console.error("confirm_email_budget_exhausted");
    return accepted;
  }

  const token = generateToken();
  await db.upsertPending(env.DB, {
    email,
    confirmTokenHash: await hashToken(token),
    expiresAt: now + CONFIRM_TTL_SECONDS,
  });

  const confirmUrl = `${env.API_ORIGIN}/confirm?t=${encodeURIComponent(token)}`;
  const { html, text } = renderConfirmEmail(confirmUrl);
  await sendOne(env, {
    to: email,
    subject: "Confirm your Michigan bills digest subscription",
    html,
    text,
  });

  return accepted;
}

async function handleConfirm(request: Request, env: Env, url: URL): Promise<Response> {
  const allowed = await env.TOKEN_IP_LIMIT.limit({ key: clientIp(request) });
  if (!allowed.success) {
    return htmlPage({
      title: "Slow down",
      heading: "Too many attempts",
      body: "<p>Try again in a minute.</p>",
      status: 429,
    });
  }

  const token = url.searchParams.get("t");
  if (!isWellFormedToken(token)) return invalidLinkPage();

  const confirmed = await db.confirmByTokenHash(env.DB, await hashToken(token));
  // One page for expired, unknown, and already-redeemed alike.
  if (!confirmed) return invalidLinkPage();

  return htmlPage({
    title: "Subscription confirmed",
    heading: "You're subscribed",
    body: `<p>You'll get a digest on days the Michigan legislature reports activity. Quiet days get no email.</p>
<p class="muted">Every digest carries a one-click unsubscribe link.</p>
<p><a href="${escapeHtml(env.SITE_ORIGIN)}">Back to the site</a></p>`,
  });
}

function invalidLinkPage(): Response {
  return htmlPage({
    title: "Link no longer valid",
    heading: "That link is no longer valid",
    body: `<p>Confirmation links expire after 24 hours and work only once.</p>
<p>You can sign up again to get a fresh one.</p>`,
    status: 410,
  });
}

/**
 * GET renders a confirmation button and changes nothing.
 *
 * This matters: mail providers and corporate security appliances routinely
 * prefetch links in messages. A GET that unsubscribed on sight would quietly
 * drop readers who never clicked anything. The state change lives on POST,
 * which is also what RFC 8058 one-click clients send.
 */
async function handleUnsubscribeGet(request: Request, env: Env, url: URL): Promise<Response> {
  const allowed = await env.TOKEN_IP_LIMIT.limit({ key: clientIp(request) });
  if (!allowed.success) {
    return htmlPage({
      title: "Slow down",
      heading: "Too many attempts",
      body: "<p>Try again in a minute.</p>",
      status: 429,
    });
  }

  const raw = url.searchParams.get("t");
  const id = await verifyUnsubscribeToken(env.UNSUBSCRIBE_SIGNING_KEY, raw);
  if (id === null || !(await db.subscriberExists(env.DB, id))) return invalidLinkPage();

  const action = `/unsubscribe?t=${encodeURIComponent(raw!)}`;
  return htmlPage({
    title: "Unsubscribe",
    heading: "Unsubscribe from the digest?",
    body: `<form method="POST" action="${escapeHtml(action)}">
  <input type="hidden" name="List-Unsubscribe" value="One-Click">
  <p><button type="submit">Yes, unsubscribe me</button></p>
</form>
<p class="muted">You will stop receiving the daily digest immediately.</p>`,
  });
}

async function handleUnsubscribePost(request: Request, env: Env, url: URL): Promise<Response> {
  const allowed = await env.TOKEN_IP_LIMIT.limit({ key: clientIp(request) });
  if (!allowed.success) return new Response("Too many requests", { status: 429 });

  const id = await verifyUnsubscribeToken(env.UNSUBSCRIBE_SIGNING_KEY, url.searchParams.get("t"));
  if (id === null) return invalidLinkPage();

  const done = await db.unsubscribeById(env.DB, id);
  if (!done) return invalidLinkPage();

  return htmlPage({
    title: "Unsubscribed",
    heading: "You're unsubscribed",
    body: `<p>No further digests will be sent to that address.</p>
<p><a href="${escapeHtml(env.SITE_ORIGIN)}">Back to the site</a></p>`,
  });
}

async function handleSendDigest(request: Request, env: Env): Promise<Response> {
  const authorization = request.headers.get("Authorization") ?? "";
  if (!authorization.startsWith("Bearer ")) {
    return json({ error: "unauthorized" }, { status: 401 });
  }

  const verified = await verifyGitHubOidc(authorization.slice("Bearer ".length).trim(), {
    audience: env.API_ORIGIN,
    repository: env.GITHUB_REPOSITORY,
    ref: env.GITHUB_REF,
  });
  if (!verified.ok) {
    // Log the reason for debugging, but return an undifferentiated 401.
    console.warn("oidc_rejected", { reason: verified.reason });
    return json({ error: "unauthorized" }, { status: 401 });
  }

  const body = await readJsonBody(request, MAX_DIGEST_BODY_BYTES);
  const parsed = parseDigestPayload(body);
  if (!parsed.ok) return json({ error: parsed.error }, { status: 400 });

  const payload = parsed.value;
  if (payload.bills.length === 0) {
    return json({ status: "skipped", reason: "no_bills" });
  }

  // Replay guard. A resent request for a date already mailed is a no-op, so a
  // retried or replayed workflow cannot blast the list twice.
  const claimed = await db.claimDigestDate(env.DB, payload.date, payload.bills.length);
  if (!claimed) {
    return json({ status: "already_sent", date: payload.date });
  }

  // The body is identical for every recipient apart from the unsubscribe link,
  // so render once and substitute per recipient. Rendering per recipient would
  // burn CPU time linearly for no benefit.
  const placeholder = "__UNSUBSCRIBE_URL__";
  const links = { siteUrl: env.SITE_ORIGIN, unsubscribeUrl: placeholder };
  const htmlTemplate = renderDigestHtml(payload, links);
  const textTemplate = renderDigestText(payload, links);
  const subject = digestSubject(payload);
  const budget = intVar(env.MAX_DIGEST_EMAILS_PER_DAY, 10000);

  let afterId = 0;
  let sent = 0;
  for (;;) {
    const page = await db.pageConfirmed(env.DB, afterId, BATCH_MAX);
    if (page.length === 0) break;

    const withinBudget = await db.consumeDailyBudget(
      env.DB,
      "digest_emails",
      budget,
      page.length,
    );
    if (!withinBudget) {
      console.error("digest_budget_exhausted", { sent });
      break;
    }

    const messages: OutboundEmail[] = await Promise.all(
      page.map(async (recipient): Promise<OutboundEmail> => {
        const token = await mintUnsubscribeToken(env.UNSUBSCRIBE_SIGNING_KEY, recipient.id);
        const unsubscribeUrl = `${env.API_ORIGIN}/unsubscribe?t=${encodeURIComponent(token)}`;
        return {
          to: recipient.email,
          subject,
          html: htmlTemplate.replaceAll(placeholder, escapeHtml(unsubscribeUrl)),
          text: textTemplate.replaceAll(placeholder, unsubscribeUrl),
          headers: unsubscribeHeaders(env.API_ORIGIN, token),
        };
      }),
    );

    if (await sendBatch(env, messages)) sent += page.length;
    afterId = page[page.length - 1]!.id;
  }

  await db.recordDigestRecipients(env.DB, payload.date, sent);
  return json({ status: "sent", date: payload.date, recipients: sent, bills: payload.bills.length });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    try {
      if (request.method === "OPTIONS") return preflight(request, env.SITE_ORIGIN);

      if (path === "/health" && request.method === "GET") {
        return json({ status: "ok" });
      }
      if (path === "/subscribe" && request.method === "POST") {
        return await handleSubscribe(request, env);
      }
      if (path === "/confirm" && request.method === "GET") {
        return await handleConfirm(request, env, url);
      }
      if (path === "/unsubscribe" && request.method === "GET") {
        return await handleUnsubscribeGet(request, env, url);
      }
      if (path === "/unsubscribe" && request.method === "POST") {
        return await handleUnsubscribePost(request, env, url);
      }
      if (path === "/admin/send-digest" && request.method === "POST") {
        return await handleSendDigest(request, env);
      }

      return json({ error: "not_found" }, { status: 404 });
    } catch (error) {
      // Never surface stack traces or messages: they leak table names, bindings
      // and library internals.
      console.error("unhandled_error", {
        name: (error as Error).name,
        path,
        method: request.method,
      });
      return json({ error: "internal_error" }, { status: 500 });
    }
  },
} satisfies ExportedHandler<Env>;
