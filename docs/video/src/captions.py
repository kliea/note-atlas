"""Write captions.srt: each narration line split into sentence-sized cues, timed by character share."""
import json, re
from timing import scene_frames, FPS, LEAD

def ts(x):
    h, r = divmod(x, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"

dur = json.load(open("dur.json")); lines = json.load(open("lines.json"))
start = 0.0; n = 1; out = []
for nf, d, line in zip(scene_frames(), dur, lines):
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", line) if p.strip()]
    chunks = []
    for p in parts:                       # keep cues under ~90 characters
        while len(p) > 90:
            cut = p.rfind(", ", 0, 90); cut = cut + 1 if cut > 30 else p.rfind(" ", 0, 90)
            chunks.append(p[:cut].strip()); p = p[cut:].strip()
        chunks.append(p)
    total = sum(len(c) for c in chunks); t = start + LEAD
    for c in chunks:
        dt = d * len(c) / total
        out.append(f"{n}\n{ts(t)} --> {ts(t + dt)}\n{c.replace('Chroma D B', 'ChromaDB')}\n"); n += 1; t += dt
    start += nf / FPS
open("captions.srt", "w").write("\n".join(out)); print(f"{n - 1} cues")
