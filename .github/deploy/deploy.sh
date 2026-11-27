#!/usr/bin/env bash
# Server-side deploy script for df-insights.de.
#
# GitHub Actions connects over SSH with a key that may only run this script
# (forced command in ~/.ssh/authorized_keys, see .github/deploy/SETUP.md) and
# passes the commit to deploy as the SSH command, e.g. `ssh ubuntu@server <sha>`.
#
# Install a copy OUTSIDE the app checkout, so a deploy never rewrites the script
# while it runs:  install -m 755 .github/deploy/deploy.sh ~/bin/df-insights-deploy
#
# Steps: validate the commit, make sure it is on origin/main, check it out,
# install the requirements, restart the service and check that the app answers
# with the new version. If any step after the checkout fails, it rolls back to
# the previous commit and exits non-zero, so the GitHub job fails.
set -euo pipefail

# Settings. Override them in ~/.config/df-insights-deploy.env instead of editing this file.
APP_ROOT="${HOME}/work"                     # git checkout; holds .env and work/app.py
VENV="${APP_ROOT}/.venv"                    # virtualenv the service runs with
SERVICE="webapp"                            # Gunicorn systemd unit
HEALTH_URL="http://127.0.0.1:5000/about"    # page served by Gunicorn directly, bypassing nginx
BRANCH="main"
RESTART_CMD=""                              # default: sudo -n systemctl restart $SERVICE
CONFIG_FILE="${HOME}/.config/df-insights-deploy.env"
# shellcheck source=/dev/null
[[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"
restart_service() {
	if [[ -n "$RESTART_CMD" ]]; then bash -c "$RESTART_CMD"; else sudo -n systemctl restart "$SERVICE"; fi
}

log() { printf '[deploy %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# With a forced command, the requested command arrives in SSH_ORIGINAL_COMMAND.
# Accept exactly one full 40-character commit SHA and nothing else.
requested="${SSH_ORIGINAL_COMMAND:-${1:-}}"
[[ "$requested" =~ ^[0-9a-f]{40}$ ]] || die "expected a full commit SHA, got: ${requested:0:80}"
target="$requested"

# One deploy at a time
exec 9>"${HOME}/.df-insights-deploy.lock"
flock -n 9 || die "another deploy is running"

cd "$APP_ROOT"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$APP_ROOT is not a git checkout (see SETUP.md)"

log "fetching origin/${BRANCH}"
git fetch --quiet origin "$BRANCH"
git cat-file -e "${target}^{commit}" 2>/dev/null || die "commit $target not found on origin"
git merge-base --is-ancestor "$target" "origin/${BRANCH}" || die "commit $target is not on origin/${BRANCH}"

previous="$(git rev-parse HEAD)"
if [[ "$previous" == "$target" ]]; then
	log "already at $target, restarting anyway"
fi

rolled_back=0
rollback() {
	local status=$?
	[[ $status -eq 0 || $rolled_back -eq 1 ]] && return
	rolled_back=1
	log "deploy failed (exit $status), rolling back to $previous"
	git checkout --quiet --force --detach "$previous" || true
	"$VENV/bin/pip" install --quiet --disable-pip-version-check -r work/requirements.txt || true
	restart_service 9>&- || true
	log "rolled back to $(git log -1 --format='%h %cs')"
	exit "$status"
}
trap rollback EXIT

log "checking out $target (was $previous)"
# Tracked files only; .env, .venv and work/.cache are untracked and ignored, so they stay.
git checkout --quiet --force --detach "$target"

log "installing requirements"
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r work/requirements.txt

log "restarting $SERVICE"
restart_service 9>&-  # the lock must not leak into the app process

# The footer shows "Version <short sha> <date>" (config.APP_VERSION, read from git).
expected_version="$(git log -1 --format='%h %cs')"
log "waiting for $HEALTH_URL to report version $expected_version"
last_status="no response"
seen_version="none"
for attempt in $(seq 1 30); do
	if page="$(curl -sS --max-time 5 -w '\n%{http_code}' "$HEALTH_URL" 2>&1)"; then
		last_status="HTTP ${page##*$'\n'}"
		seen_version="$(grep -oE 'Version [^<]*' <<<"$page" | head -1 | sed 's/^Version //')"
		seen_version="${seen_version:-none}"
		if [[ "$last_status" == "HTTP 200" && "$seen_version" == "$expected_version" ]]; then
			log "deployed $expected_version (attempt $attempt)"
			trap - EXIT
			exit 0
		fi
	else
		last_status="no response: $(head -1 <<<"${page#curl: }")"
	fi
	sleep 2
done
# Say what the app answered, so the GitHub log shows why the check failed
log "last answer from $HEALTH_URL: ${last_status}, footer version: ${seen_version}"
[[ "$seen_version" == "unknown" ]] && log "hint: the app could not read git. Does the $SERVICE service run as the owner of $APP_ROOT?"
die "app did not come up with version $expected_version"
