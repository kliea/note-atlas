"""Lay narration on the scene grid, generate the music bed, duck it under the voice. Writes final_audio.wav."""
import subprocess, numpy as np, soundfile as sf, json
from scipy.signal import resample_poly, lfilter
from timing import scene_frames, FPS, LEAD

SR = 48000; out = []
for i, n in enumerate(scene_frames()):
    a, sr = sf.read(f"n{i:02d}.wav"); a = resample_poly(a, SR // sr, 1)
    seg = np.zeros(n * SR // FPS); s = int(LEAD * SR); seg[s:s + len(a)] = a[:len(seg) - s]; out.append(seg)
v = np.concatenate(out); v = v / np.abs(v).max() * 0.89
subprocess.run(["python3", "music.py", str(len(v) / SR), "music.wav"], check=True)
m, _ = sf.read("music.wav"); m = m[:len(v)]
if len(m) < len(v): m = np.pad(m, ((0, len(v) - len(m)), (0, 0)))

# voice envelope (10 ms blocks, 50 ms attack, 600 ms release) drives the ducking
blk = SR // 100; xb = np.abs(v[:len(v) // blk * blk]).reshape(-1, blk).max(1)
aa, ar = np.exp(-1 / 5), np.exp(-1 / 60); z = 0.0; yb = np.empty_like(xb)
for k, val in enumerate(xb):
    c = aa if val > z else ar; z = c * z + (1 - c) * val; yb[k] = z
e = np.repeat(yb, blk); e = np.pad(e, (0, len(v) - len(e)), "edge")
duck = np.clip(e / np.percentile(e[e > 1e-4], 90), 0, 1)
vr = np.sqrt(np.mean(v[np.abs(v) > 0.01] ** 2)); mr = np.sqrt(np.mean(m ** 2))
lo, hi = vr / mr * 10 ** (-21 / 20), vr / mr * 10 ** (-14 / 20)   # music: -21 dB under speech, -14 dB in pauses
g = lfilter([1 - 0.9995], [1, -0.9995], hi + (lo - hi) * duck)
mix = np.stack([v, v], 1) + m * g[:, None]
sf.write("final_audio.wav", mix / np.abs(mix).max() * 0.94, SR)
print(f"audio {len(v) / SR:.1f}s")
