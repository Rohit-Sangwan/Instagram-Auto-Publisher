#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
mkdir -p backups
name="${1:-backups/publisher-$(date -u +%Y%m%dT%H%M%SZ).sqlite3}"
if [[ -e $name ]]; then echo "Backup path already exists." >&2; exit 1; fi
temporary=$(mktemp -- "${name}.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT
docker compose exec -T api python -c '
import pathlib, sqlite3, sys, tempfile
with tempfile.TemporaryDirectory() as folder:
    filename = pathlib.Path(folder) / "snapshot"
    with sqlite3.connect("/data/publisher.sqlite3") as source, sqlite3.connect(filename) as target:
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with filename.open("rb") as source:
        import shutil
        shutil.copyfileobj(source, sys.stdout.buffer)
' > "$temporary"
mv -n -- "$temporary" "$name"
printf 'Saved database backup to %s\n' "$name"
