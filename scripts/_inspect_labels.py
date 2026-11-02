import json
from pathlib import Path

for p in (Path("outputs/run1/play_labels.json"), Path("outputs/run2/play_labels.json")):
    print("===", p, "exists", p.exists())
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(d, dict):
        vals = list(d.values()) if d and not isinstance(next(iter(d.values()), None), dict) else d
        if isinstance(d, dict) and all(isinstance(v, str) for v in d.values()):
            from collections import Counter

            print("n", len(d), Counter(d.values()))
            print("sample", list(d.items())[:12])
        else:
            print(type(d), str(d)[:500])
    else:
        print(type(d), str(d)[:500])
