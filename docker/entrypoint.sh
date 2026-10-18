#!/bin/sh
# Create the demo database on the first start (it lives in the "state" volume).
set -e
if [ ! -f "$REFUND_DB_PATH" ]; then
    echo "First start: creating demo database at $REFUND_DB_PATH"
    python -m refund_agent.seed
fi
exec "$@"
