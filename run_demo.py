from __future__ import annotations
import os
os.environ.setdefault("BALVIBE_DEMO_MODE", "false")
os.environ.setdefault("BALVIBE_DATA_DIR", "./data")
import uvicorn
uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
