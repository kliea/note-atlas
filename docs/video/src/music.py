"""Original ambient underscore: soft felt-piano arpeggios over a warm pad and sub bass.
Generated from scratch (no samples). Usage: python3 music.py <seconds> out.wav"""
import sys, numpy as np, soundfile as sf

SR = 48000
dur = float(sys.argv[1]); out = sys.argv[2]
N = int(dur * SR) + SR
rng = np.random.default_rng(3)
BPM = 68; beat = 60 / BPM; bar = 4 * beat

def hz(m): return 440 * 2 ** ((m - 69) / 12)

# I - vi - IV - V-ish in D major, voiced softly (MIDI notes)
chords = [
    [50, 57, 62, 64, 66, 69],   # Dadd9
    [47, 54, 59, 62, 66, 69],   # Bm7(add11-ish)
    [43, 50, 55, 59, 62, 66],   # Gmaj7
    [45, 52, 57, 61, 64, 69],   # A(add9)
    [50, 57, 62, 64, 66, 69],
    [42, 54, 57, 61, 64, 66],   # F#m7
    [43, 50, 55, 59, 62, 69],   # Gmaj9
    [45, 52, 55, 57, 62, 64],   # Asus
]
mix = np.zeros(N); padL = np.zeros(N); padR = np.zeros(N)

def piano(f, length, vel):
    n = int(length * SR); t = np.arange(n) / SR
    env = np.exp(-t * (1.6 + f / 900)) * (1 - np.exp(-t * 400))
    s = np.zeros(n)
    for k, a in [(1, 1), (2, .38), (3, .14), (4, .06), (5, .03)]:
        s += a * np.sin(2 * np.pi * f * k * 1.0004 ** (k - 1) * t + rng.random() * 6)
    return s * env * vel

def pad(f, length):
    n = int(length * SR); t = np.arange(n) / SR
    att = np.minimum(1, t / 1.8); rel = np.minimum(1, (length - t) / 1.8)
    env = np.clip(att * rel, 0, 1) ** 1.5
    l = sum(np.sin(2 * np.pi * f * d * t + ph) for d, ph in [(0.997, 0), (1.003, 1.1), (2.0, 2.2)]) / 3
    r = sum(np.sin(2 * np.pi * f * d * t + ph) for d, ph in [(1.002, .5), (0.998, 1.7), (2.001, .3)]) / 3
    return l * env, r * env

i = 0; t0 = 0.0
pattern = [0, 2, 3, 4, 5, 4, 3, 2]  # indices into chord voicing (eighth notes)
while t0 < dur:
    ch = chords[i % len(chords)]
    s0 = int(t0 * SR)
    # pad: upper chord tones
    for m in ch[1:5]:
        l, r = pad(hz(m), bar + 1.8)
        e = min(N, s0 + len(l)); padL[s0:e] += l[:e - s0] * .055; padR[s0:e] += r[:e - s0] * .055
    # sub bass
    b = pad(hz(ch[0] - 12), bar + .6)[0]; e = min(N, s0 + len(b)); mix[s0:e] += b[:e - s0] * .10
    # piano arpeggio, enters after 2 bars, sparser in odd sections
    if i >= 1:
        for j, pi in enumerate(pattern):
            if (i // 8) % 2 == 1 or j % 2 == 0 or i > 2:
                st = s0 + int(j * beat / 2 * SR) + int(rng.normal(0, .006) * SR)
                vel = .16 * (1.0 if j == 0 else .7) * (.85 + .3 * rng.random())
                note = piano(hz(ch[pi] + 12), 3.5, vel)
                e = min(N, st + len(note)); mix[max(st, 0):e] += note[:e - max(st, 0)]
    i += 1; t0 += bar

L = mix + padL; R = mix + padR
# simple stereo reverb: exponentially decaying noise IR
ir_n = int(2.6 * SR); tt = np.arange(ir_n) / SR
irL = rng.normal(0, 1, ir_n) * np.exp(-tt * 2.4); irR = rng.normal(0, 1, ir_n) * np.exp(-tt * 2.4)
irL /= np.sqrt((irL ** 2).sum()); irR /= np.sqrt((irR ** 2).sum())
from numpy.fft import rfft, irfft
def conv(x, h):
    n = len(x) + len(h); m = 1 << (n - 1).bit_length()
    return irfft(rfft(x, m) * rfft(h, m), m)[:len(x)]
L = L * .7 + conv(L, irL) * .45; R = R * .7 + conv(R, irR) * .45
# gentle low-pass (one-pole) for warmth
def lp(x, fc=3500):
    a = np.exp(-2 * np.pi * fc / SR); y = np.empty_like(x); z = 0.0
    from scipy.signal import lfilter
    return lfilter([1 - a], [1, -a], x)
L, R = lp(L), lp(R)
st = np.stack([L, R], 1)[:int(dur * SR)]
fi, fo = int(3 * SR), int(5 * SR)
st[:fi] *= np.linspace(0, 1, fi)[:, None]; st[-fo:] *= np.linspace(1, 0, fo)[:, None]
st /= np.abs(st).max(); st *= .9
sf.write(out, st, SR)
print('music', st.shape[0] / SR)
