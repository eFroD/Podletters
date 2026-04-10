# Reference Audio & Cover Art

This directory holds the voice reference clips and podcast cover art used by
the Podletters pipeline.

## Voice References

F5-TTS uses 10–15 second WAV clips as a "voice fingerprint" for zero-shot
cloning. Better references → better output quality.

### Option A: Bootstrap with Piper TTS (no microphone)

```bash
make bootstrap-voices
# or manually:
./scripts/bootstrap_voices.sh refs/
```

This generates `host1.wav` (de_DE-thorsten-medium) and `host2.wav`
(de_DE-eva_k-x_low) using Piper TTS. Quick and automated but lower quality
than recorded clips.

### Option B: Record your own (recommended for Phase 4+)

Record two German speakers reading 2–3 natural sentences each:

| File | Speaker | Example text |
|------|---------|-------------|
| `host1.wav` | Kai (calm, analytical) | "Hallo und willkommen zu unserem Podcast. Heute schauen wir uns die neuesten Entwicklungen im Bereich der künstlichen Intelligenz an." |
| `host2.wav` | Mia (warm, curious) | "Genau, das finde ich wirklich spannend! Lass uns direkt einsteigen und schauen, was es Neues gibt." |

Requirements:
- **Format:** WAV, mono, 22050 or 44100 Hz, 16-bit or float32
- **Duration:** 10–15 seconds per clip
- **Quality:** Quiet room, close mic, no background noise or reverb
- **Content:** Natural spoken German (not read-aloud style)

### Option C: Curate from public domain audio

Find CC0/public domain German speech recordings (e.g. LibriVox DE) and trim
a representative 10–15 second segment per speaker. Ensure distinct timbres.

## Cover Art

`cover.png` is served at `/cover.png` by the API and referenced in the RSS
feed's `<itunes:image>` tag. Replace the placeholder with your own artwork.

Requirements:
- **Format:** PNG or JPEG
- **Size:** 3000×3000 px (Apple Podcasts requirement), min 1400×1400
- **Content:** Square, no transparency for JPEG
