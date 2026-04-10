#!/usr/bin/env bash
# Bootstrap reference WAV files for F5-TTS using Piper TTS (PRD §11).
#
# Piper runs on CPU so this does NOT need a GPU. The generated clips serve
# as the zero-shot reference for each host voice. Replace them with
# higher-quality recordings in Phase 4.
#
# Usage:
#   ./scripts/bootstrap_voices.sh            # writes to refs/
#   ./scripts/bootstrap_voices.sh /out/dir   # custom output directory
#
# Prerequisites:
#   pip install piper-tts
#   Piper voice models are downloaded automatically on first run.

set -euo pipefail

OUT_DIR="${1:-refs}"
mkdir -p "$OUT_DIR"

HOST1_TEXT="Hallo und willkommen, schön dass du dabei bist."
HOST2_TEXT="Genau, das finde ich auch sehr interessant, lass uns das anschauen."

# Piper voice models for German. Using two distinct voices for timbre contrast.
HOST1_MODEL="de_DE-thorsten-medium"
HOST2_MODEL="de_DE-eva_k-x_low"

echo "==> Generating HOST1 reference (${HOST1_MODEL}) …"
echo "$HOST1_TEXT" | piper --model "$HOST1_MODEL" --output_file "$OUT_DIR/host1.wav"
echo "    Wrote $OUT_DIR/host1.wav"

echo "==> Generating HOST2 reference (${HOST2_MODEL}) …"
echo "$HOST2_TEXT" | piper --model "$HOST2_MODEL" --output_file "$OUT_DIR/host2.wav"
echo "    Wrote $OUT_DIR/host2.wav"

echo "==> Done. Reference clips:"
ls -lh "$OUT_DIR"/host{1,2}.wav
