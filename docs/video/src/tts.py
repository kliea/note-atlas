"""Narrate each scene with Kokoro (voice bm_george, British English). Writes nNN.wav, dur.json, lines.json."""
import json, sys, soundfile as sf
from kokoro_onnx import Kokoro
from lines import LINES

speed = float(sys.argv[1]) if len(sys.argv) > 1 else 1.06
k = Kokoro("kokoro.onnx", "voices.bin"); d = []
for i, t in enumerate(LINES):
    a, sr = k.create(t, voice="bm_george", speed=speed, lang="en-gb")
    sf.write(f"n{i:02d}.wav", a, sr); d.append(len(a) / sr)
json.dump(d, open("dur.json", "w")); json.dump(LINES, open("lines.json", "w"))
print(f"{len(d)} lines, {sum(d):.1f}s of speech")
