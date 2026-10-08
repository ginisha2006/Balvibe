# BalVibe Studio 

A working BalVibe MVP through the **voiceover stage**

The pipeline is now consistent end to end:

```text
Researcher instructions
  -> Groq storyline generation
  -> researcher review / edit / approval lock
  -> choose Sarvam Translate OR BHASHINI / ULCA
  -> choose Azure Speech OR Sarvam Bulbul v3
  -> per-scene WAV files
  -> combined WAV
  -> complete timing-ready JSON dataset
  -> persisted run + scene metadata
```

## What changed from the earlier BalVibe work

The previous Azure starter proved native WAV generation, while the upstream integrated repo had two divergent TTS paths: the CLI used Azure and the web path used Sarvam. This version puts both providers behind one contract.

Both providers produce the same scene metadata, including:

- `slideNumber` and `slideId`
- `sceneOrder`
- one consistent story setting and experiment task across all scenes
- source and translated narration
- character state and visual asset tag
- trial metadata when applicable
- `ttsProvider` and `voice`
- native `.wav` filename and URL
- measured `audioDurationMs`
- `startTimeMs` / `endTimeMs`
- `startTimeSeconds` / `endTimeSeconds`
- cumulative timeline start/end
- configurable FPS
- `startFrame`, `totalFrames`, `endFrameExclusive`

Every voiceover run also generates a combined WAV plus a machine-readable dataset JSON ready for the later visual/Remotion stage.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`.

### Run without any API keys

For a full UI/backend/database/audio contract demo:

```env
BALVIBE_DEMO_MODE=true
```

Demo mode runs the entire flow, writes valid 24 kHz mono WAV files, persists runs, and verifies the exact Azure/Sarvam-neutral output contract without calling paid APIs.

### Live provider mode

Set:

```env
BALVIBE_DEMO_MODE=false
GROQ_API_KEY=...
SARVAM_API_KEY=...
BHASHINI_USER_ID=...
BHASHINI_API_KEY=...
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=centralindia
```

Do **not** place API keys in frontend code or commit `.env`.

## Database and media storage

For this voiceover-stage MVP, persistence is deliberately simple and reproducible:

```text
BALVIBE_DATA_DIR/
  balvibe.db                 # SQLite metadata database
  runs/
    run-xxxxxxxxxxxx/
      dataset_azure.json
      dataset_sarvam.json
      audio/
        azure/
          scene_001_hi_azure.wav
          ...
          combined_hi_azure.wav
        sarvam/
          scene_001_hi_sarvam.wav
          ...
          combined_hi_sarvam.wav
```

SQLite stores experiment/run status, approval state, storylines, scene metadata, provider choice, voice choice and the latest timing dataset. WAV and dataset artifacts live beside the database under the same persistent data directory.

### On Render

The current demo deployment uses Render's free web-service plan and stores runtime data under `/tmp/balvibe`. This keeps the hosted prototype free, but SQLite rows and generated WAV files are ephemeral and may disappear when the service restarts or spins down.

For durable storage, move relational metadata to PostgreSQL and media to object storage, or use a paid persistent disk, while keeping the API contract unchanged.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | backend/provider/database status |
| `GET /api/config` | supported languages, providers and voices |
| `POST /api/generate-script` | create draft storyline |
| `PUT /api/runs/{id}/storyline` | save researcher edits |
| `POST /api/runs/{id}/approve` | lock approved source storyline |
| `POST /api/runs/{id}/translate` | Sarvam or BHASHINI translation |
| `POST /api/runs/{id}/voiceover` | Azure or Sarvam TTS + timing dataset |
| `GET /api/runs/{id}` | full persisted run |
| `GET /api/runs/{id}/dataset` | downloadable dataset JSON |
| `GET /api/runs/{id}/audio/{provider}/{file}` | generated WAV |

## Checks performed

Offline/static check:

```bash
python -m compileall -q app tests
```

Unit/integration tests:

```bash
python -m unittest discover -s tests -v
```

The tests run both provider paths in deterministic demo mode and verify that Azure and Sarvam produce the same timing contract.

A real HTTP end-to-end smoke test was also run locally through:

1. generate storyline
2. approve
3. translate
4. Azure voiceover
5. fetch combined Azure WAV
6. Sarvam voiceover
7. fetch combined Sarvam WAV
8. fetch persisted dataset

Both WAV outputs were verified as valid **24 kHz, mono, 16-bit PCM** files.

## Provider implementation notes

- Groq uses `qwen/qwen3.8-27b` and JSON Object Mode.
- Sarvam translation uses `sarvam-translate:v1` with conservative 1,800-character chunks.
- BHASHINI translation uses the official two-step ULCA/Dhruva flow: Pipeline Config resolves the translation service and short-lived inference credentials, then Pipeline Compute performs the translation. BalVibe maps locales such as `hi-IN` to BHASHINI's ISO-639 code `hi` and preserves pause markers outside translated text.
- Sarvam TTS uses `bulbul:v3`, native WAV output at 24 kHz, and preserves `[PAUSE N seconds]` by inserting PCM silence between TTS segments.
- Azure TTS uses the REST `cognitiveservices/v1` endpoint, RIFF 24 kHz 16-bit mono PCM output, and preserves pauses using SSML `<break>` tags.
- Azure Hindi choices included: `hi-IN-SwaraNeural`, `hi-IN-MadhurNeural`.
- Azure Indian English choices included: `en-IN-NeerjaNeural`, `en-IN-PrabhatNeural`.
- Sarvam starter voice choices included: `shubh`, `ritu`, `priya`, `aditya`.

## Security improvements over the initial integrated repo

- no permissive cross-origin API requirement because frontend and API are served same-origin
- no API keys exposed to the browser
- run IDs are validated server-side
- audio filenames are validated and constrained to each run/provider directory
- storyline payload is validated before approval
- researcher approval is stored instead of hard-coded
- downstream translation/TTS is blocked before approval
- model-generated frontend text is escaped before insertion

## Source inspiration

This is a fresh implementation derived from the BalVibe project architecture and workflow, not a direct deploy of either reference repository.
