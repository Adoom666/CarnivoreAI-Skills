#!/bin/bash
# Usage: backup.sh FILE [FILE...]   (dest root: $SCROOGE_BACKUP_DIR or ${CLAUDE_CONFIG_DIR:-~/.claude}/scrooge-backups)
# Copies each file into <dest>/<timestamp>/ preserving its absolute path, then writes
# MANIFEST.sha256 and RESTORE.txt in that directory. Read-only on the originals.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 FILE [FILE...]" >&2; exit 2; }
DEST="${SCROOGE_BACKUP_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scrooge-backups}/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
for f in "$@"; do
  abs=$(cd "$(dirname "$f")" && printf '%s/%s' "$(pwd -P)" "$(basename "$f")")
  [ -f "$abs" ] || { echo "skip (not a file): $f" >&2; continue; }
  mkdir -p "$DEST$(dirname "$abs")"
  cp -p "$abs" "$DEST$abs"
done
( cd "$DEST" && find . -type f ! -name MANIFEST.sha256 ! -name RESTORE.txt | sort | while read -r p; do
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$p"; else shasum -a 256 "$p"; fi
  done > MANIFEST.sha256 )
cat > "$DEST/RESTORE.txt" <<EOF
Backup made $(date) by scrooge backup.sh.
Files are stored under this directory at their original absolute paths.
Verify:   cd "$DEST" && shasum -a 256 -c MANIFEST.sha256
Restore one file:   cp -p "$DEST/<absolute path>" "/<absolute path>"
Restore all:        cd "$DEST" && find . -type f ! -name MANIFEST.sha256 ! -name RESTORE.txt | while read -r p; do cp -p "\$p" "\${p#.}"; done
EOF
echo "$DEST"
