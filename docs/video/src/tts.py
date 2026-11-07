"""Narrate each scene with Kokoro. VOICE/LANG env vars pick the voice (default am_michael, American English).
Writes nNN.wav, dur.json, lines.json."""
import json, os, sys, soundfile as sf
from kokoro_onnx import Kokoro
from lines import LINES

speed = float(sys.argv[1]) if len(sys.argv) > 1 else 1.06
k = Kokoro("kokoro.onnx", "voices.bin"); d = []
for i, t in enumerate(LINES):
    a, sr = k.create(t, voice=os.environ.get("VOICE", "am_michael"), speed=speed, lang=os.environ.get("LANG_CODE", "en-us"))
    sf.write(f"n{i:02d}.wav", a, sr); d.append(len(a) / sr)
json.dump(d, open("dur.json", "w")); json.dump(LINES, open("lines.json", "w"))
print(f"{len(d)} lines, {sum(d):.1f}s of speech")
