from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as audio:
        return round(audio.getnframes() * 1000 / audio.getframerate())


def silence_wav(duration_seconds: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    frames = max(1, round(duration_seconds * sample_rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(CHANNELS)
        out.setsampwidth(SAMPLE_WIDTH)
        out.setframerate(sample_rate)
        out.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def tone_wav(duration_seconds: float, frequency: float = 220.0, sample_rate: int = SAMPLE_RATE) -> bytes:
    frames = max(1, round(duration_seconds * sample_rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(CHANNELS)
        out.setsampwidth(SAMPLE_WIDTH)
        out.setframerate(sample_rate)
        pcm = bytearray()
        amplitude = 2000
        for i in range(frames):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
            pcm.extend(struct.pack("<h", sample))
        out.writeframes(bytes(pcm))
    return buf.getvalue()


def _decode_wav_bytes(data: bytes) -> tuple[bytes, int, int, int]:
    with wave.open(io.BytesIO(data), "rb") as src:
        return src.readframes(src.getnframes()), src.getnchannels(), src.getsampwidth(), src.getframerate()


def concatenate_wavs(chunks: list[bytes]) -> bytes:
    if not chunks:
        return silence_wav(0.05)
    decoded = [_decode_wav_bytes(chunk) for chunk in chunks]
    channels, width, rate = decoded[0][1:]
    for _, ch, sw, fr in decoded:
        if (ch, sw, fr) != (channels, width, rate):
            raise ValueError("Cannot concatenate WAVs with different PCM formats.")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"".join(pcm for pcm, *_ in decoded))
    return buf.getvalue()
