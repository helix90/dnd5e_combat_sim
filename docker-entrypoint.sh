#!/bin/sh
# Starts the app as appuser. A volume mounted for the database, as Fly.io mounts one, arrives
# owned by root, so while still root, hand its folder to appuser first.
set -e

if [ "$(id -u)" = 0 ]; then
    db_path="${DATABASE_URL#sqlite:///}"
    case "$db_path" in
        /*) ;;
        *) db_path="/app/${db_path:-data/app.db}" ;;
    esac
    db_dir="$(dirname "$db_path")"
    mkdir -p "$db_dir"
    if [ "$(stat -c %u "$db_dir")" = 0 ]; then
        chown -R appuser:appuser "$db_dir"
    fi
    exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi

exec "$@"
