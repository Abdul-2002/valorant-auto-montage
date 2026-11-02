#!/bin/bash
echo "=== api client json ==="
ls -la /app/client_secret*.json 2>&1 || true
echo "=== api YOUTUBE env (names only) ==="
printenv | grep '^YOUTUBE' | sed 's/=.*/=***/' || true
echo "=== worker ==="
# run from host via docker exec worker separately
