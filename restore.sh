#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $# -ne 1 || ! -f $1 ]]; then echo "Usage: bash restore.sh backups/file.sqlite3" >&2; exit 1; fi
read -rp "Replace the database with $1 and pause automation? Type RESTORE: " answer
[[ $answer == RESTORE ]] || exit 1
bash backup.sh "backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
services=(api)
if grep -Fxq proxy <<< "$(docker compose config --services)"; then
  services=(proxy api)
fi
docker compose stop "${services[@]}"
trap 'docker compose up -d --wait' EXIT
docker compose run --rm --no-deps -T api python -c '
import pathlib, shutil, sqlite3, sys
current = pathlib.Path("/data/publisher.sqlite3")
staged = current.with_suffix(".restore")
try:
    with staged.open("wb") as target:
        shutil.copyfileobj(sys.stdin.buffer, target)
    with sqlite3.connect(staged) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("UPDATE automation_settings SET paused=1, automatic=0 WHERE id=1")
        db.execute("DELETE FROM admin_sessions")
    with sqlite3.connect(current) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("PRAGMA journal_mode=DELETE")
    staged.replace(current)
finally:
    staged.unlink(missing_ok=True)
' < "$1"
echo "Database restored with automation paused. Reconcile Instagram publishing history before resuming."
