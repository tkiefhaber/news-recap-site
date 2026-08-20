#!/bin/bash
# Daily push job for news-recap-site
# Triggered by ~/Library/LaunchAgents/com.tkiefhaber.news-recap-push.plist whenever
# files in the repo change (WatchPaths). Commits any new HTML files written by the
# Cowork scheduled task and pushes to GitHub, which triggers Cloudflare Pages to deploy.
# Repo lives outside ~/Documents so LaunchAgents can read/execute without Full Disk Access.

set -euo pipefail

REPO="$HOME/Sites/news-recap-site"
LOG_TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"

cd "$REPO"

# Regenerate the RSS feed from whatever is in archive/ before staging. This also
# re-injects the feed autodiscovery <link> into index.html, which the daily task
# overwrites each morning. Non-fatal: a feed failure shouldn't block the push.
if ! python3 scripts/build-feed.py; then
    echo "[$LOG_TIMESTAMP] WARNING: feed build failed; pushing without feed update."
fi

# Stage everything
git add -A

# Bail early if nothing changed
if git diff --cached --quiet; then
    echo "[$LOG_TIMESTAMP] No changes to push."
    exit 0
fi

git commit -m "Daily recap $(date +%F)"
git push

echo "[$LOG_TIMESTAMP] Pushed."
