#!/bin/bash
# Daily push job for news-recap-site
# Triggered by ~/Library/LaunchAgents/com.tkiefhaber.news-recap-push.plist whenever
# files in the repo change (WatchPaths). Commits any new HTML files written by the
# Cowork scheduled task and pushes to GitHub, which triggers Cloudflare Pages to deploy.
# Repo lives outside ~/Documents so LaunchAgents can read/execute without Full Disk Access.
#
# FAILURE VISIBILITY (added 2026-08-20 after a 3-day silent outage):
#   - Every run writes its outcome to .push-status (gitignored) and appends to
#     ~/Library/Logs/news-recap-push.log. The Cowork daily task reads .push-status
#     and emails on failure, so nothing fails silently again.
#   - A stale .git/index.lock is now cleared automatically. That was the original
#     culprit: an empty lock left behind on Aug 17 made `git add` fail every
#     morning, and `set -e` exited before the commit. The feed step ran first, so
#     the repo still looked active while nothing was ever pushed.

set -euo pipefail

REPO="$HOME/Sites/news-recap-site"
STATUS_FILE="$REPO/.push-status"
LOG_FILE="$HOME/Library/Logs/news-recap-push.log"
LOCK="$REPO/.git/index.lock"
STALE_LOCK_MINUTES=10

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

mkdir -p "$(dirname "$LOG_FILE")"

# Record outcome in both the status file (machine-read by the Cowork task) and the
# rolling log (human-read). STATE is OK | NOOP | FAIL.
record() {
    local state="$1" msg="$2"
    printf 'state=%s\ntime=%s\nhead=%s\nmessage=%s\n' \
        "$state" "$(ts)" "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)" "$msg" \
        > "$STATUS_FILE"
    printf '[%s] %s: %s\n' "$(ts)" "$state" "$msg" | tee -a "$LOG_FILE"
}

fail() {
    record FAIL "$1"
    exit 1
}

# Any unhandled error lands here instead of exiting silently.
trap 'fail "unexpected error on line $LINENO (see $LOG_FILE)"' ERR

cd "$REPO"

# --- Clear a stale index.lock ---------------------------------------------
# No legitimate git operation holds index.lock for more than a few seconds, so a
# lock older than STALE_LOCK_MINUTES is debris from a crashed or interrupted run.
# Anything newer might be a real concurrent git process, so we bail loudly instead.
if [ -e "$LOCK" ]; then
    if [ -n "$(find "$LOCK" -mmin +"$STALE_LOCK_MINUTES" 2>/dev/null)" ]; then
        rm -f "$LOCK"
        printf '[%s] NOTE: removed stale index.lock (older than %s min)\n' \
            "$(ts)" "$STALE_LOCK_MINUTES" | tee -a "$LOG_FILE"
    else
        fail "index.lock exists and is recent; another git process may be running"
    fi
fi

# --- Regenerate the RSS feed ----------------------------------------------
# Also re-injects the feed autodiscovery <link> into index.html, which the daily
# task overwrites each morning. Non-fatal: a feed failure shouldn't block the push,
# but it does get logged rather than swallowed.
if ! python3 scripts/build-feed.py >>"$LOG_FILE" 2>&1; then
    printf '[%s] WARNING: feed build failed; pushing without feed update.\n' \
        "$(ts)" | tee -a "$LOG_FILE"
fi

# --- Stage, commit, push ---------------------------------------------------
git add -A || fail "git add failed"

if git diff --cached --quiet; then
    record NOOP "no changes to push"
    exit 0
fi

git commit -m "Daily recap $(date +%F)" >>"$LOG_FILE" 2>&1 || fail "git commit failed"
git push >>"$LOG_FILE" 2>&1 || fail "git push failed (check SSH key / network)"

# Confirm the remote actually advanced rather than trusting the exit code alone.
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse origin/main 2>/dev/null || echo none)"
if [ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]; then
    fail "push reported success but origin/main is $REMOTE_HEAD, not $LOCAL_HEAD"
fi

record OK "pushed $(git rev-parse --short HEAD)"
