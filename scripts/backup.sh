#!/usr/bin/env sh
set -eu

if [ "$#" -eq 0 ]; then
    set -- backup
fi
exec python3 "$(dirname "$0")/backup_restore.py" "$@"
