#!/bin/bash
set -e
echo "=== task 1f94 ==="
ls -la /data/tasks/1f942c2f-8d2b-4639-aaa2-7ae47d60f476/ || true
echo "=== task 2fc1 ==="
ls -la /data/tasks/2fc1e74f-e816-4f26-97a9-7cfc9acc43e9/ || true
echo "=== processes ==="
for d in /proc/[0-9]*; do
  if [ -r "$d/cmdline" ]; then
    cmd=$(tr '\0' ' ' < "$d/cmdline")
    case "$cmd" in
      *mood*|*finish*|*uvicorn*|*python*)
        echo "$d: $cmd"
        ;;
    esac
  fi
done
echo "=== finish log ==="
tail -5 /data/mood_finish.log 2>/dev/null || true
echo "=== mood render log ==="
tail -5 /data/mood_render.log 2>/dev/null || true
echo "=== api recent ==="
# nothing
