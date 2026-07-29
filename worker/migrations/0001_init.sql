-- Subscriber list for the daily Michigan bills digest.
--
-- Security notes:
--   * Confirm tokens are stored as SHA-256 hex, never in plaintext. A dump of
--     this database therefore does not let an attacker confirm a pending
--     signup: the raw token only ever exists in the email we sent and in the
--     recipient's URL bar.
--   * Unsubscribe tokens are NOT stored at all -- they are derived on demand as
--     `id.HMAC(signing_key, id)`. Storing a hash would not work (the digest
--     sender needs the raw token to build each recipient's link, and a hash
--     cannot be reversed), and storing plaintext would mean a leaked dump lets
--     an attacker unsubscribe every reader. Deriving them keeps the secret in
--     Worker secrets rather than in the database, and rotating the key
--     invalidates every outstanding link at once.
--   * `email` is stored normalized (trimmed, lowercased) so the UNIQUE
--     constraint is the authoritative, cross-datacenter defence against
--     signup floods aimed at one victim. The Workers rate limiter is
--     per-colo and approximate; this is not.

CREATE TABLE subscribers (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    email                  TEXT    NOT NULL UNIQUE,
    -- 'pending' -> 'confirmed' -> 'unsubscribed'. Rows are never deleted, so a
    -- resubscribe reuses the row and we keep the unsubscribe audit trail.
    status                 TEXT    NOT NULL CHECK (
                               status IN ('pending', 'confirmed', 'unsubscribed')
                           ),

    -- Single-use, expiring. Cleared the moment it is redeemed.
    confirm_token_hash     TEXT,
    confirm_expires_at     INTEGER,

    created_at             INTEGER NOT NULL,
    confirmed_at           INTEGER,
    unsubscribed_at        INTEGER,

    -- Authoritative cooldown: throttles repeat confirmation sends to the same
    -- address regardless of which datacenter the request lands in.
    last_confirm_sent_at   INTEGER,

    -- Incremented by the bounce webhook; hard bounces get suppressed so one
    -- dead address cannot drag down domain reputation.
    bounce_count           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_subscribers_status ON subscribers (status);

-- Partial index: only one live confirm token can exist per value, but the many
-- rows with a redeemed (NULL) token do not collide.
CREATE UNIQUE INDEX idx_subscribers_confirm_token
    ON subscribers (confirm_token_hash)
    WHERE confirm_token_hash IS NOT NULL;

-- Replay guard for POST /admin/send-digest. The date is the primary key, so a
-- replayed request for a date we already mailed is a no-op rather than a
-- second blast to the whole list.
CREATE TABLE sent_digests (
    digest_date     TEXT    PRIMARY KEY,  -- YYYY-MM-DD, America/Detroit
    sent_at         INTEGER NOT NULL,
    recipient_count INTEGER NOT NULL,
    bill_count      INTEGER NOT NULL
);

-- Circuit breaker. If an abuse path ever gets past Turnstile and the rate
-- limiter, this caps the blast radius at a fixed number of outbound messages
-- per day instead of the whole Resend quota (and the domain's reputation).
CREATE TABLE daily_counters (
    day   TEXT    NOT NULL,  -- YYYY-MM-DD, UTC
    name  TEXT    NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, name)
);
