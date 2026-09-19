#!/bin/bash
# Runs the API and the web server in one container; if either dies, the container
# exits so Azure restarts it.
(cd /app/backend && exec uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API=$!
(cd /app/frontend && exec node server.js) &
WEB=$!

trap 'kill $API $WEB 2>/dev/null' TERM INT
wait -n
kill $API $WEB 2>/dev/null
exit 1
