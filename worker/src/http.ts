/** Response construction, security headers, and CORS. */

/**
 * `Referrer-Policy: no-referrer` matters more than it looks: confirm and
 * unsubscribe tokens travel in the query string, and without this any resource
 * those pages load would receive the token in the Referer header.
 *
 * `Cache-Control: no-store` keeps token-bearing pages out of shared caches and
 * the browser's back/forward cache.
 */
const SECURITY_HEADERS: Record<string, string> = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
  "Cache-Control": "no-store",
};

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function clientIp(request: Request): string {
  return request.headers.get("CF-Connecting-IP") ?? "unknown";
}

/** Exact-match origin check. `Vary: Origin` keeps caches from crossing them. */
function corsHeaders(request: Request, siteOrigin: string): Record<string, string> {
  const headers: Record<string, string> = { Vary: "Origin" };
  if (request.headers.get("Origin") === siteOrigin) {
    headers["Access-Control-Allow-Origin"] = siteOrigin;
    headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
    headers["Access-Control-Allow-Headers"] = "Content-Type";
    headers["Access-Control-Max-Age"] = "86400";
    // Deliberately no Access-Control-Allow-Credentials: the API is stateless
    // and must never be reachable with a browser's ambient cookies.
  }
  return headers;
}

export function json(
  body: unknown,
  init: { status?: number; request?: Request; siteOrigin?: string } = {},
): Response {
  const headers: Record<string, string> = {
    "Content-Type": "application/json; charset=utf-8",
    ...SECURITY_HEADERS,
  };
  if (init.request && init.siteOrigin) {
    Object.assign(headers, corsHeaders(init.request, init.siteOrigin));
  }
  return new Response(JSON.stringify(body), { status: init.status ?? 200, headers });
}

export function preflight(request: Request, siteOrigin: string): Response {
  return new Response(null, {
    status: 204,
    headers: { ...SECURITY_HEADERS, ...corsHeaders(request, siteOrigin) },
  });
}

/**
 * A minimal styled page. The stylesheet is inline but nonce-pinned, so the CSP
 * can stay at `default-src 'none'` with no `unsafe-inline` anywhere: injected
 * markup cannot execute or exfiltrate, because it cannot guess the nonce.
 */
export function htmlPage(
  opts: { title: string; heading: string; body: string; status?: number },
): Response {
  const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16))));
  const csp = [
    "default-src 'none'",
    `style-src 'nonce-${nonce}'`,
    "form-action 'self'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
  ].join("; ");

  const document = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>${escapeHtml(opts.title)}</title>
<style nonce="${nonce}">
  body { font-family: Georgia, serif; max-width: 34rem; margin: 4rem auto;
         padding: 0 1rem; line-height: 1.6; color: #222; }
  h1 { font-size: 1.4rem; }
  button { font: inherit; padding: 0.5rem 1.1rem; border: 1px solid #444;
           border-radius: 6px; background: #f7f7f4; cursor: pointer; }
  .muted { color: #666; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>${escapeHtml(opts.heading)}</h1>
${opts.body}
</body>
</html>
`;

  return new Response(document, {
    status: opts.status ?? 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": csp,
      ...SECURITY_HEADERS,
    },
  });
}
