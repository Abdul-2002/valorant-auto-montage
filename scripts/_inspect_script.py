import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
clips = json.loads(path.read_text(encoding="utf-8"))["clips"]
print("n", len(clips))
for i, c in enumerate(clips):
    s = float(c.get("output_start_sec") or 0)
    e = float(c.get("output_end_sec") or 0)
    print(i, round(s, 2), round(e, 2), round(e - s, 2), "kills", len(c.get("kill_timestamps_sec") or []))
starts = [float(c.get("output_start_sec") or 0) for c in clips]
ends = [float(c.get("output_end_sec") or 0) for c in clips]
print("min_start", min(starts), "max_end", max(ends), "sum_dur", sum(e - s for s, e in zip(starts, ends)))
