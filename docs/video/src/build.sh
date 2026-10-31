#!/usr/bin/env bash
# Rebuild docs/video/note-atlas-explainer.mp4 from source. Needs Python 3.11+, ffmpeg, Inter + DejaVu Sans Mono fonts.
# Fonts elsewhere? export INTER_DIR=/path/to/inter MONO_FONT=/path/to/DejaVuSansMono.ttf
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SRC/.."; BUILD="$SRC/build"; JOBS="${JOBS:-2}"
mkdir -p "$BUILD"; cd "$BUILD"

# 1. Voice model (Kokoro v1.0, Apache-2.0), downloaded once
[ -f kokoro.onnx ] || curl -fsSL -o kokoro.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
[ -f voices.bin ]  || curl -fsSL -o voices.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

# 2. Narration -> per-scene durations (all animation cues key off these)
PYTHONPATH="$SRC" python3 "$SRC/tts.py" 1.06

# 3. Scenes: one encoded file each, JOBS at a time
N=$(python3 -c "import json;print(len(json.load(open('dur.json'))))")
seq 0 $((N - 1)) | xargs -P "$JOBS" -I{} python3 "$SRC/render_full.py" scene {}

# 4. Music bed + ducked mix, captions
cp "$SRC/music.py" .; PYTHONPATH="$SRC" python3 "$SRC/mix.py"; PYTHONPATH="$SRC" python3 "$SRC/captions.py"

# 5. Join and mux
for i in $(seq -w 0 $((N - 1))); do echo "file 'scene$i.mp4'"; done > list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i list.txt -c copy video.mp4
ffmpeg -y -loglevel error -i video.mp4 -i final_audio.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT/note-atlas-explainer.tmp.mp4"
mv "$OUT/note-atlas-explainer.tmp.mp4" "$OUT/note-atlas-explainer.mp4"; cp captions.srt "$OUT/note-atlas-explainer.srt"
echo "done: $OUT/note-atlas-explainer.mp4"
