"""Scene timing shared by the mixer and caption writer (must match render_full.nframes)."""
import json
FPS, LEAD, PAD, END_HOLD = 30, 0.25, 0.55, 2.0

def scene_frames():
    dur = json.load(open("dur.json"))
    return [round((d + LEAD + PAD + (END_HOLD if i == len(dur) - 1 else 0)) * FPS) for i, d in enumerate(dur)]
