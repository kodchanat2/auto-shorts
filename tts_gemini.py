"""Gemini voice engine for render_shorts.py, using the Live model as a script reader.

One Live session per emotion (scene mood); each narration line is one turn. The model is told to read the text
verbatim, and its own transcript is compared with the line to catch ad-libs.
Gemini returns no word timings, so captions fall back to proportional timing.
There is no speed control either; `rate` is applied afterwards with ffmpeg atempo (pitch kept).
"""
from __future__ import annotations

import asyncio
import difflib
import subprocess
import wave
from pathlib import Path
from typing import Awaitable, Callable

GEMINI_LIVE_MODEL = "gemini-3.8-live"
DEFAULT_VOICE = "Puck"
GEMINI_VOICES = ["Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Aoede", "Autonoe", "Callirrhoe",
                 "Charon", "Despina", "Enceladus", "Erinome", "Fenrir", "Gacrux", "Iapetus", "Kore",
                 "Laomedeia", "Leda", "Orus", "Puck", "Pulcherrima", "Rasalgethi", "Sadachbia",
                 "Sadaltager", "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr", "Zubenelgenubi"]
OUTPUT_SR = 24000               # Live API returns 16-bit mono PCM at 24 kHz
MIN_SIMILARITY = 0.85           # transcript vs. script; below this the line is read again once
TURN_TIMEOUT_SEC = 60
MAX_SESSIONS = 3                # reconnect attempts when a session drops mid-way
RECONNECT_WAIT_SEC = 3
SYSTEM_PROMPT = ("คุณคือนักพากย์เสียงภาษาไทยสำหรับคลิปสั้น หน้าที่เดียวของคุณคืออ่านข้อความที่ผู้ใช้ส่งมาออกเสียง"
                 "ให้ตรงตามบททุกคำ ห้ามตอบ ห้ามทัก ห้ามอธิบาย ห้ามเพิ่มหรือตัดคำใดๆ")


class QuotaExhausted(RuntimeError):
    """Quota used up — retrying cannot help until it resets."""


def _is_quota(err: Exception) -> bool:
    msg = str(err).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def tempo_factor(rate: str) -> float:
    return 1 + int(rate.rstrip("%")) / 100


def resolve_voice(voice_id: str) -> str:
    """Gemini prebuilt voice name; edge-tts names (th-TH-…Neural) fall back to the default."""
    if not voice_id or voice_id.endswith("Neural") or "-" in voice_id:
        return DEFAULT_VOICE
    return voice_id


def live_config(voice: str, style: str, emotion: str = "") -> dict:
    """The scene's emotion goes into the session instruction, never into the spoken text,
    so the model acts it out instead of reading it aloud."""
    system = SYSTEM_PROMPT + (f" น้ำเสียง: {style}" if style else "")
    if emotion:
        system += f" อารมณ์ของช่วงนี้: {emotion} — ถ่ายทอดอารมณ์นี้ผ่านน้ำเสียง จังหวะ และการเน้นคำ"
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": system,
        "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}},
        "output_audio_transcription": {},
    }


def _norm(s: str) -> str:
    return "".join(ch for ch in s if not ch.isspace() and ch not in ".,!?\"'“”…")


def similarity(script: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, _norm(script), _norm(heard)).ratio()


def make_client(api_key: str):
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Put it in .env (free key: https://aistudio.google.com/apikey)")
    from google import genai
    return genai.Client(api_key=api_key)


def _write_line(pcm: bytes, out_wav: Path, factor: float) -> None:
    raw = out_wav.with_suffix(".part.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(OUTPUT_SR)
        w.writeframes(pcm)
    if abs(factor - 1.0) < 1e-6:
        raw.replace(out_wav)
        return
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-filter:a", f"atempo={factor:.4f}",
                    str(out_wav)], check=True, capture_output=True)
    raw.unlink(missing_ok=True)


async def _read_turn(session, text: str) -> tuple[bytes, str]:
    await session.send_client_content(turns={"role": "user", "parts": [{"text": text}]}, turn_complete=True)
    pcm, heard = bytearray(), []
    async for r in session.receive():
        sc = r.server_content
        if sc is None:
            continue
        if sc.model_turn:
            for p in sc.model_turn.parts:
                if p.inline_data and p.inline_data.data:
                    pcm += p.inline_data.data
        if sc.output_transcription and sc.output_transcription.text:
            heard.append(sc.output_transcription.text)
        if sc.turn_complete:
            break
    if len(pcm) < OUTPUT_SR // 10:
        raise RuntimeError("empty audio returned")
    return bytes(pcm), "".join(heard)


async def _read_verified(session, text: str) -> tuple[bytes, str | None]:
    """Audio for one line plus a warning if the model still did not read it verbatim."""
    pcm, heard = await asyncio.wait_for(_read_turn(session, text), TURN_TIMEOUT_SEC)
    if not heard or similarity(text, heard) >= MIN_SIMILARITY:
        return pcm, None
    pcm, heard = await asyncio.wait_for(_read_turn(session, text), TURN_TIMEOUT_SEC)
    sim = similarity(text, heard) if heard else 1.0
    if sim >= MIN_SIMILARITY:
        return pcm, None
    return pcm, f"Gemini read a line differently ({sim:.0%} match): script '{text}' / heard '{heard}'"


def _groups(jobs: list[tuple]) -> list[tuple[str, list[tuple[str, Path]]]]:
    """Consecutive jobs sharing an emotion -> one session each, order preserved."""
    out: list[tuple[str, list[tuple[str, Path]]]] = []
    for job in jobs:
        text, path, emotion = job if len(job) == 3 else (*job, "")
        if out and out[-1][0] == emotion:
            out[-1][1].append((text, path))
        else:
            out.append((emotion, [(text, path)]))
    return out


async def _run(jobs: list[tuple], voice: str, style: str, rate: str, client,
               sleep: Callable[[float], Awaitable[None]]) -> list[str]:
    warnings: list[str] = []
    for emotion, group in _groups(jobs):
        warnings += await _run_group(group, voice, style, emotion, tempo_factor(rate), client, sleep)
    return warnings


async def _run_group(jobs: list[tuple[str, Path]], voice: str, style: str, emotion: str, factor: float,
                     client, sleep: Callable[[float], Awaitable[None]]) -> list[str]:
    todo, warnings, last_err = list(jobs), [], None
    config = live_config(voice, style, emotion)
    for _ in range(MAX_SESSIONS):
        try:
            async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=config) as session:
                while todo:
                    text, out = todo[0]
                    pcm, warning = await _read_verified(session, text)
                    _write_line(pcm, out, factor)
                    if warning:
                        warnings.append(warning)
                    todo.pop(0)
            return warnings
        except Exception as e:  # dropped socket / timeout / service hiccup
            if _is_quota(e):
                raise QuotaExhausted(f"Gemini Live quota used up ({str(e)[:160]}). Lines already made are "
                                     "cached; retry later, switch voice.engine to edge-tts, or enable billing.") from e
            last_err = e
            await sleep(RECONNECT_WAIT_SEC)
    raise RuntimeError(f"Gemini Live failed after {MAX_SESSIONS} sessions: {last_err}") from last_err


def synthesize_all(jobs: list[tuple], voice: str, style: str, rate: str, client,
                   sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> list[str]:
    """Read every (text, out_wav[, emotion]) job; returns warnings for lines that did not match the script."""
    return asyncio.run(_run(jobs, voice, style, rate, client, sleep))
