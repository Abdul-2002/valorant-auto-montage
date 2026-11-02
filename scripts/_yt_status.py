import json
import sqlite3
import urllib.request

print("=== last upload API ===")
uid = "5e527cf9048a4e5587213ff92030a9f6"
with urllib.request.urlopen(f"http://127.0.0.1:8000/youtube/uploads/{uid}", timeout=30) as r:
    print(json.dumps(json.load(r), indent=2))

print("=== db recent ===")
conn = sqlite3.connect("/data/library.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "select id,status,title,youtube_video_id,error,created_at from youtube_uploads order by created_at desc limit 5"
).fetchall()
for row in rows:
    print(dict(row))
