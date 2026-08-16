#!/bin/bash
# Snapshot of prismind's local state -- the files that are not in git and
# not reproducible from it.
#
# What is here, and how bad losing each one would be:
#
#   config.toml                  the host's actual configuration. Not in
#                                git (gitignored), so a loss means
#                                reconstructing it from memory.
#   credentials.json             Google OAuth client secret. Recoverable
#                                from the Cloud console, but only by
#                                someone who knows which project.
#   token.json                   the refresh token. Recoverable only by
#                                re-running scripts/init_google_auth.py
#                                interactively, which needs a human and a
#                                browser -- so losing it takes the
#                                service down until someone is available.
#   .prismind_projects.json      project registry.
#   .prismind_memory_cache.json  cache. Rebuildable, included because it
#                                is small and skipping it would make the
#                                restore incomplete in a confusing way.
#
# The deploy runner runs this before it touches anything. A deploy does
# not write any of these files -- they are all gitignored, so pinning
# leaves them alone -- but "the deploy did not break it" is a weaker
# statement than "we have a copy", and until now there was no copy.
#
# Usage:
#   ./scripts/backup.sh
#   BACKUP_DIR=/path/to/dest ./scripts/backup.sh
#
# Env (optional overrides):
#   BACKUP_DIR      (default: <repo>/backups)
#   RETENTION_DAYS  (default: 30)
set -euo pipefail

# Overridable so the script can be exercised against a tree other than the
# one it lives in; defaults to its own repo, which is what the deploy
# runner wants.
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

ITEMS=(
    config.toml
    credentials.json
    token.json
    .prismind_projects.json
    .prismind_memory_cache.json
)

present=()
for item in "${ITEMS[@]}"; do
    [[ -e "$REPO_DIR/$item" ]] && present+=("$item")
done

if [[ ${#present[@]} -eq 0 ]]; then
    # A checkout that has never been configured has nothing to lose, and
    # a deploy must not be blocked by that.
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup skipped: no local state in $REPO_DIR"
    exit 0
fi

# 700 before anything lands in it: two of these files are credentials,
# and a world-readable directory would be a worse problem than the one
# this script solves.
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/prismind-state-${TS}.tar.gz"

# umask before tar, so the archive is never briefly group-readable.
(umask 077 && tar -czf "$OUT" -C "$REPO_DIR" "${present[@]}")
chmod 600 "$OUT"

find "$BACKUP_DIR" -maxdepth 1 -name 'prismind-state-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup ok: $OUT ($(stat -c%s "$OUT") bytes, ${#present[@]} items)"
