#!/usr/bin/env bash
# This fork: bring upstream's main (weslocke/ED-Outrider, the remote `upstream`) into this branch and verify the
# result. An ordinary merge, never a rebase or a force-push; nothing is pushed: with a PASS, `git push` yourself.
# docs/FORK.md says what to expect from a merge. Usage: bash scripts/merge-upstream.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "no remote named upstream: git remote add upstream https://github.com/weslocke/ED-Outrider" >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "there are uncommitted changes: commit or stash them first" >&2
  exit 1
fi

git fetch upstream
new=$(git rev-list --count HEAD..upstream/main)
if [ "$new" -eq 0 ]; then
  echo "nothing new upstream"
  exit 0
fi
echo "$new new upstream commit(s):"
git log --oneline HEAD..upstream/main | head -40

if ! git merge --no-edit upstream/main; then
  echo
  echo "conflicts, in:" >&2
  git diff --name-only --diff-filter=U >&2
  echo "resolve them keeping both sides (docs/FORK.md), git add, git commit, then: bash scripts/verify.sh" >&2
  exit 1
fi

bash scripts/verify.sh
echo
echo "merged and verified. To publish: git push"
