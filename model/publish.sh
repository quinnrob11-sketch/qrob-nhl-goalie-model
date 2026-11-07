#!/usr/bin/env bash
# Commit the generated site after every successful build and push it, so Vercel deploys every build.
# Commits even when only timestamps changed (--allow-empty as a backstop): a build that produced the same
# lines still publishes its new fetch times. PUBLISH_NO_PUSH=1 commits without pushing (tests).
set -euo pipefail
git config user.email >/dev/null || git config user.email "github-actions[bot]@users.noreply.github.com"
git config user.name >/dev/null || git config user.name "github-actions[bot]"
git add index.html
for p in model/data/calls model/data/real_line_log.csv model/data/dk_prices.csv model/output/tracking.json \
         model/output/calibration.json model/data/legs.csv model/data/rosters.json model/data/odds_cache.json \
         model/data/pick6_cache.json model/data/pp_cache.json model/data/moneypuck; do
  [ -e "$p" ] && git add "$p"
done
git add -A model/data/pick6_failed.html 2>/dev/null || true
git commit -q --allow-empty -m "auto: rebuild $(date -u +'%Y-%m-%d %H:%M UTC')"
echo "committed $(git rev-parse --short HEAD)"
[ "${PUBLISH_NO_PUSH:-}" = 1 ] && exit 0
for i in 1 2 3; do
  git push && exit 0
  git pull --rebase origin "${GITHUB_REF_NAME:-main}"; sleep $((i * 3))
done
exit 1
