/**
 * Verifies a GitHub Actions OIDC token.
 *
 * Why not a shared secret: the digest endpoint can mail every subscriber from
 * a domain we own, so it has the worst blast radius in the system. A static
 * bearer token in GitHub secrets is a standing credential -- it leaks through
 * a careless `echo`, a fork's workflow, or a compromised third-party action,
 * and stays valid until somebody notices. OIDC tokens are minted per-run,
 * expire in minutes, and carry claims we can pin to this exact repository and
 * branch, so a token stolen from any other repo is useless here.
 *
 * The Cloudflare API token in CI stays long-lived because Cloudflare has no
 * OIDC support -- but it is scoped to Pages deploys and cannot send email.
 */

const ISSUER = "https://token.actions.githubusercontent.com";
const JWKS_URL = `${ISSUER}/.well-known/jwks`;

const JWKS_TTL_MS = 10 * 60 * 1000;
// Floor between refetches. Without it, forged tokens carrying random `kid`
// values would each trigger a JWKS fetch -- a free amplification vector.
const JWKS_MIN_REFETCH_MS = 60 * 1000;
const CLOCK_SKEW_SECONDS = 60;
const MAX_TOKEN_LIFETIME_SECONDS = 900;

interface Jwk extends JsonWebKey {
  kid?: string;
  alg?: string;
}

interface GitHubClaims {
  iss?: string;
  aud?: string | string[];
  exp?: number;
  nbf?: number;
  iat?: number;
  repository?: string;
  repository_owner?: string;
  ref?: string;
  workflow_ref?: string;
}

let jwksCache: { keys: Jwk[]; fetchedAt: number } | null = null;
let lastFetchAttempt = 0;

function base64UrlDecode(input: string): Uint8Array {
  const normalized = input.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function decodeJson(segment: string): unknown {
  return JSON.parse(new TextDecoder().decode(base64UrlDecode(segment)));
}

async function getKey(kid: string): Promise<Jwk | null> {
  const now = Date.now();
  const fresh = jwksCache !== null && now - jwksCache.fetchedAt < JWKS_TTL_MS;

  if (fresh) {
    const hit = jwksCache!.keys.find((key) => key.kid === kid);
    if (hit) return hit;
    // Unknown kid against a fresh cache means either key rotation or a forged
    // token. Allow a refetch, but not more often than the floor.
    if (now - lastFetchAttempt < JWKS_MIN_REFETCH_MS) return null;
  }

  lastFetchAttempt = now;
  const response = await fetch(JWKS_URL, { cf: { cacheTtl: 600 } });
  if (!response.ok) return null;
  const body = (await response.json()) as { keys?: Jwk[] };
  if (!Array.isArray(body.keys)) return null;

  jwksCache = { keys: body.keys, fetchedAt: now };
  return body.keys.find((key) => key.kid === kid) ?? null;
}

export interface OidcResult {
  ok: boolean;
  reason?: string;
  claims?: GitHubClaims;
}

export async function verifyGitHubOidc(
  token: string,
  expected: { audience: string; repository: string; ref: string },
): Promise<OidcResult> {
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };
  const [headerB64, payloadB64, signatureB64] = parts as [string, string, string];

  let header: { alg?: string; kid?: string };
  let claims: GitHubClaims;
  try {
    header = decodeJson(headerB64) as { alg?: string; kid?: string };
    claims = decodeJson(payloadB64) as GitHubClaims;
  } catch {
    return { ok: false, reason: "undecodable" };
  }

  // Pin the algorithm before touching any key material. Accepting the token's
  // own `alg` is the classic JWT break (alg=none, or RS256 verified as HS256
  // with the public key as the HMAC secret).
  if (header.alg !== "RS256") return { ok: false, reason: "bad_alg" };
  if (typeof header.kid !== "string") return { ok: false, reason: "no_kid" };

  const jwk = await getKey(header.kid);
  if (!jwk) return { ok: false, reason: "unknown_kid" };

  const key = await crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );

  const signed = new TextEncoder().encode(`${headerB64}.${payloadB64}`);
  const verified = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    base64UrlDecode(signatureB64),
    signed,
  );
  if (!verified) return { ok: false, reason: "bad_signature" };

  // Signature is good; now the claims decide whether this run may send mail.
  const nowSeconds = Math.floor(Date.now() / 1000);

  if (claims.iss !== ISSUER) return { ok: false, reason: "bad_issuer" };

  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!audiences.includes(expected.audience)) return { ok: false, reason: "bad_audience" };

  if (typeof claims.exp !== "number" || nowSeconds > claims.exp + CLOCK_SKEW_SECONDS) {
    return { ok: false, reason: "expired" };
  }
  if (typeof claims.nbf === "number" && nowSeconds < claims.nbf - CLOCK_SKEW_SECONDS) {
    return { ok: false, reason: "not_yet_valid" };
  }
  if (
    typeof claims.iat === "number" &&
    claims.exp - claims.iat > MAX_TOKEN_LIFETIME_SECONDS
  ) {
    return { ok: false, reason: "lifetime_too_long" };
  }

  // The claims that actually scope this down: any other repository, or a
  // branch/PR ref in this repository, is rejected. Without the `ref` check a
  // pull request from a fork could mint a token for this repo.
  if (claims.repository !== expected.repository) return { ok: false, reason: "bad_repository" };
  if (claims.ref !== expected.ref) return { ok: false, reason: "bad_ref" };

  return { ok: true, claims };
}
