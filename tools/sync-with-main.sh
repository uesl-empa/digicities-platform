#!/bin/sh
# Bring a long-lived branch up to date with origin/main.
#
# Git has no branch that follows another one by itself, so this is the one
# command that does it: fetch, then MERGE main in (never rebase — this branch
# is pushed, and a rebase would mean force-pushing it).
#
#   tools/sync-with-main.sh            merge origin/main into the current branch
#   tools/sync-with-main.sh --check    only say how far behind it is, change nothing
#
# It refuses to touch a dirty tree: a merge on top of uncommitted test edits is
# how you lose them.
set -e

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" = "main" ]; then
    echo "already on main — nothing to sync into"
    exit 0
fi

git fetch --quiet origin main
behind=$(git rev-list --count HEAD..origin/main)
ahead=$(git rev-list --count origin/main..HEAD)

if [ "$behind" = "0" ]; then
    echo "$branch is up to date with main (its own commits: $ahead)"
    exit 0
fi

echo "$branch is $behind commit(s) behind main, $ahead of its own:"
git --no-pager log --oneline --no-merges HEAD..origin/main | head -20

[ "$1" = "--check" ] && exit 0

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo
    echo "the working tree has uncommitted changes — commit or stash them first:"
    git --no-pager status --short --untracked-files=no
    exit 1
fi

# The api container bind-mounts this directory, so a merge changes the code a
# running test is executing. Say so; the caller decides.
if command -v docker >/dev/null 2>&1 && \
   [ -n "$(docker ps --quiet --filter name=digicities 2>/dev/null)" ]; then
    echo
    echo "note: a digicities container is running on this checkout — restart it"
    echo "      after the merge, and do not sync while a test run is in flight."
fi

echo
git merge --no-edit origin/main
echo "$branch is now level with main"
