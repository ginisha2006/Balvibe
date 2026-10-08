from __future__ import annotations

import json
import sys
import requests

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"

def check(response: requests.Response):
    if not response.ok:
        raise SystemExit(f"{response.request.method} {response.url} -> {response.status_code}: {response.text}")
    return response.json()

print("health", check(requests.get(f"{BASE}/api/health", timeout=10)))
created = check(requests.post(f"{BASE}/api/generate-script", json={
    "instruction": "Show six numbers for exactly 2 seconds. Hide one number and ask which number disappeared. Include one practice round and three formal trials, then close without correctness feedback.",
    "ageBand": "6-8",
    "duration": 120,
    "targetLanguage": "hi-IN",
}, timeout=120))
run_id = created["runId"]
print("run", run_id)
check(requests.post(f"{BASE}/api/runs/{run_id}/approve", json={"storyline": created["storyline"]}, timeout=30))
check(requests.post(f"{BASE}/api/runs/{run_id}/translate", json={"targetLanguage": "hi-IN"}, timeout=120))
for provider, voice in (("azure", "hi-IN-SwaraNeural"), ("sarvam", "ritu")):
    dataset = check(requests.post(f"{BASE}/api/runs/{run_id}/voiceover", json={"provider": provider, "voice": voice, "fps": 30}, timeout=300))
    assert dataset["ttsProvider"] == provider
    assert dataset["sceneCount"] == len(dataset["scenes"])
    assert all(scene["audioDurationMs"] > 0 for scene in dataset["scenes"])
    print(provider, dataset["audioTimelineDurationMs"], "ms", dataset["combinedAudioUrl"])
print("OK")
