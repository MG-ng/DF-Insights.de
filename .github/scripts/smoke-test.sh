#!/usr/bin/env bash
# Smoke test of the live site, used after each deploy and by the nightly check.
# Usage: smoke-test.sh <base-url> [expected-commit-sha]
# With a commit SHA it also checks that the footer shows that commit, i.e. that
# production really runs it. Missing security headers are reported as warnings
# until they are set up in nginx (review finding M2); then they can become errors.
set -uo pipefail

base_url="${1:?usage: smoke-test.sh <base-url> [expected-commit-sha]}"
expected_sha="${2:-}"
failures=0

fail() { echo "::error::$*"; failures=$((failures + 1)); }
pass() { echo "ok: $*"; }

check_status() {  # path, expected content type prefix
	local path="$1" type="$2" out code ctype
	out="$(curl -sS -o /dev/null --max-time 30 -w '%{http_code} %{content_type}' "${base_url}${path}")" \
		|| { fail "${path}: request failed"; return; }
	code="${out%% *}"; ctype="${out#* }"
	if [[ "$code" == "200" && "$ctype" == "$type"* ]]; then
		pass "${path} -> ${code} ${ctype}"
	else
		fail "${path}: expected 200 ${type}, got ${code} ${ctype}"
	fi
}

check_status "/" "text/html"
check_status "/api?region=DE&resolution=year" "application/json"
check_status "/static/css/style.css" "text/css"
check_status "/static/vendor/plotly/plotly-finance-4.3.0.min.js" ""
check_status "/robots.txt" "text/plain"

page="$(curl -sS --max-time 30 "${base_url}/about")" || page=""
deployed="$(grep -oE 'Version [0-9a-f]{7,40}' <<<"$page" | head -1 | cut -d' ' -f2)"
if [[ -z "$deployed" ]]; then
	fail "no version marker found in the page footer"
elif [[ -n "$expected_sha" ]]; then
	if [[ "$expected_sha" == "$deployed"* ]]; then
		pass "production runs ${deployed}"
	else
		fail "production runs ${deployed}, expected ${expected_sha:0:12}"
	fi
else
	pass "production runs ${deployed}"
fi

headers="$(curl -sSI --max-time 30 "${base_url}/" | tr -d '\r' | tr '[:upper:]' '[:lower:]')" || fail "could not read the response headers of /"
for header in strict-transport-security content-security-policy x-content-type-options referrer-policy; do
	if grep -q "^${header}:" <<<"$headers"; then
		pass "header ${header}"
	else
		if [[ "$header" == "content-security-policy" ]] && grep -q "^content-security-policy-report-only:" <<<"$headers"; then
			echo "::warning::content-security-policy is in report-only mode (set CSP_ENFORCE=true in .env to enforce it)"
		else
			echo "::warning::missing security header: ${header}"
		fi
	fi
done
if grep -qE '^server: nginx/[0-9]' <<<"$headers"; then
	echo "::warning::Server header discloses the nginx version (set server_tokens off)"
fi

if (( failures > 0 )); then
	echo "${failures} check(s) failed"
	exit 1
fi
echo "all checks passed"
