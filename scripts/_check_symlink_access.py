from pathlib import Path

p = Path("/data/tasks/40083a97-1e09-473e-b295-2089cf4f882e/inputs")
for f in sorted(p.iterdir())[:3]:
    print(f.name, "exists", f.exists(), "is_file", f.is_file(), "resolve", f.resolve())
v = Path("/videos")
print("videos dir", v.exists(), [x.name for x in list(v.glob("*.mp4"))[:2]])
