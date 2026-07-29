#!/usr/bin/env bash
# Validates the shape of the credentials Terraform needs, without printing them.
#
#     source env.sh && ./check-env.sh
#
# Exists because every credential failure so far has been a value in the wrong
# variable, and the resulting errors point somewhere unhelpful: an R2 token
# value in AWS_ACCESS_KEY_ID reports a length complaint from S3, and a missing
# Cloudflare token reports a missing-header error from the Pages API.

set -uo pipefail
fail=0

check() {
  local name="$1" pattern="$2" want="$3"
  local value="${!name:-}"

  if [ -z "$value" ]; then
    printf '  %-22s MISSING          want %s\n' "$name" "$want"
    fail=1
  elif [[ "$value" =~ $pattern ]]; then
    printf '  %-22s ok (%d chars)\n' "$name" "${#value}"
  else
    printf '  %-22s WRONG SHAPE (%d chars)   want %s\n' "$name" "${#value}" "$want"
    fail=1
  fi
}

echo "Terraform credentials:"
check AWS_ACCESS_KEY_ID     '^[0-9a-f]{32}$' "32 hex chars (R2 Access Key ID, not the Token value)"
check AWS_SECRET_ACCESS_KEY '^[0-9a-f]{64}$' "64 hex chars (R2 Secret Access Key)"
check CLOUDFLARE_API_TOKEN  '^[A-Za-z0-9_-]{30,}$' "Cloudflare API token from My Profile > API Tokens"

if [ -n "${AWS_PROFILE:-}" ]; then
  echo "  NOTE  AWS_PROFILE is set; your AWS SSO profile may override these."
  fail=1
fi
if [ -n "${AWS_SESSION_TOKEN:-}" ]; then
  echo "  NOTE  AWS_SESSION_TOKEN is set; R2 does not use session tokens."
  fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "Looks right. Run: terraform apply"
else
  echo "Fix the above, then re-source env.sh."
fi
exit "$fail"
