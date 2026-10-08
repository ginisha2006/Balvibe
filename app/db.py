from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    instruction TEXT NOT NULL,
    age_band TEXT NOT NULL,
    target_duration_seconds INTEGER NOT NULL,
    target_language TEXT NOT NULL,
    status TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    storyline_flow_approved INTEGER NOT NULL DEFAULT 0,
    storyline_flow_json TEXT,
    tts_provider TEXT,
    voice TEXT,
    fps INTEGER NOT NULL DEFAULT 30,
    english_storyline_json TEXT,
    translated_storyline_json TEXT,
    dataset_json TEXT,
    combined_audio_file TEXT
);
CREATE TABLE IF NOT EXISTS scenes (
    run_id TEXT NOT NULL,
    scene_order INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    audio_script TEXT NOT NULL,
    translated_text TEXT,
    character_type TEXT NOT NULL,
    character_name TEXT NOT NULL,
    character_state TEXT NOT NULL,
    visual_asset_tag TEXT NOT NULL,
    planned_duration_seconds REAL NOT NULL,
    trial_json TEXT,
    tts_provider TEXT,
    voice TEXT,
    audio_file_name TEXT,
    audio_duration_ms INTEGER,
    start_time_ms INTEGER,
    end_time_ms INTEGER,
    start_frame INTEGER,
    total_frames INTEGER,
    end_frame_exclusive INTEGER,
    fps INTEGER,
    PRIMARY KEY (run_id, scene_order),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(runs)")
        cols = {row["name"] for row in cursor.fetchall()}
        if "storyline_flow_json" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN storyline_flow_json TEXT")
        if "storyline_flow_approved" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN storyline_flow_approved INTEGER NOT NULL DEFAULT 0")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection and always close it, including on Windows."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_run(self, payload: dict[str, Any]) -> None:
        keys = list(payload.keys())
        placeholders = ",".join("?" for _ in keys)
        updates = ",".join(f"{key}=excluded.{key}" for key in keys if key != "id")
        with self.connection() as conn:
            conn.execute(
                f"INSERT INTO runs ({','.join(keys)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                [self._encode(payload[key]) for key in keys],
            )

    def patch_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ",".join(f"{key}=?" for key in fields)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE runs SET {assignments} WHERE id=?",
                [self._encode(value) for value in fields.values()] + [run_id],
            )

    def replace_scenes(self, run_id: str, scenes: list[dict[str, Any]]) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM scenes WHERE run_id=?", (run_id,))
            for scene in scenes:
                conn.execute(
                    """
                    INSERT INTO scenes (
                      run_id, scene_order, source_text, audio_script, translated_text,
                      character_type, character_name, character_state, visual_asset_tag,
                      planned_duration_seconds, trial_json, tts_provider, voice,
                      audio_file_name, audio_duration_ms, start_time_ms, end_time_ms,
                      start_frame, total_frames, end_frame_exclusive, fps
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        scene["sceneOrder"],
                        scene.get("sourceText", ""),
                        scene.get("audioScript", ""),
                        scene.get("translatedText"),
                        scene.get("characterType", "creature"),
                        scene.get("characterName", "Pico"),
                        scene.get("characterState", "neutral"),
                        scene.get("visualAssetTag", "scene"),
                        scene.get("durationSeconds", 0),
                        json.dumps(scene.get("trial"), ensure_ascii=False) if scene.get("trial") else None,
                        scene.get("ttsProvider"),
                        scene.get("voice"),
                        scene.get("audioFileName"),
                        scene.get("audioDurationMs"),
                        scene.get("startTimeMs"),
                        scene.get("endTimeMs"),
                        scene.get("startFrame"),
                        scene.get("totalFrames"),
                        scene.get("endFrameExclusive"),
                        scene.get("fps"),
                    ),
                )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None
            payload = dict(row)
            for key in ("english_storyline_json", "translated_storyline_json", "dataset_json", "storyline_flow_json"):
                if payload.get(key):
                    try:
                        payload[key] = json.loads(payload[key])
                    except Exception:
                        pass
            payload["approved"] = bool(payload["approved"])
            payload["storyline_flow_approved"] = bool(payload.get("storyline_flow_approved", 0))
            return payload

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id,created_at,updated_at,instruction,age_band,target_duration_seconds,"
                "target_language,status,approved,storyline_flow_approved,tts_provider,voice,fps FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                dict(row)
                | {
                    "approved": bool(row["approved"]),
                    "storyline_flow_approved": bool(row.get("storyline_flow_approved", 0)),
                }
                for row in rows
            ]

    @staticmethod
    def _encode(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return int(value)
        return value
