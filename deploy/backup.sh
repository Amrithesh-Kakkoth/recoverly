#!/usr/bin/env bash
# Runs on the server from cron. Dumps Postgres to a dated, verified file, optionally copies it to S3
# (set BACKUP_S3_URI), then removes local dumps older than BACKUP_KEEP_DAYS. Old dumps are only removed
# after a good new one exists, so a failing backup never eats the last good copy.
set -euo pipefail

repo="${BACKUP_REPO:-$HOME/recoverly}"
dir="${BACKUP_DIR:-$HOME/backups}"
keep_days="${BACKUP_KEEP_DAYS:-7}"

umask 077
mkdir -p "$dir"
cd "$repo"

file="$dir/recoverly-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
partial="$file.partial"
trap 'rm -f "$partial"' EXIT

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec -T db pg_dump -U recoverly --clean --if-exists recoverly | gzip > "$partial"

# pg_dump writes this line last, so its absence means the dump was cut short.
gzip -t "$partial"
gzip -dc "$partial" | tail -n 5 | grep -q 'PostgreSQL database dump complete' \
  || { echo "backup is incomplete: $file" >&2; exit 1; }
mv "$partial" "$file"
echo "Backed up to $file ($(du -h "$file" | cut -f1))"

if [[ -n "${BACKUP_S3_URI:-}" ]]; then
  aws s3 cp --only-show-errors "$file" "${BACKUP_S3_URI%/}/$(basename "$file")"
  echo "Copied to $BACKUP_S3_URI"
fi

find "$dir" -name 'recoverly-*.sql.gz' -mtime "+$keep_days" -delete
