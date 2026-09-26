#!/usr/bin/env python3
"""
render_shorts.py — Deterministic YouTube Shorts assembler (no LLM calls)

    storyboard.json
        -> edge-tts Thai voiceover (per line, cached, word-timed)
        -> frame-exact scene timeline + cut allocation (1.5–3.0 s sub-cuts)
        -> Pexels portrait footage (cached, de-duplicated)
        -> FFmpeg: scale + center-crop 1080x1920, trim/loop per cut
        -> Thai word-level captions (pythainlp + Pillow) + ducked BGM
        -> output/final_shorts.mp4  (+ timeline.json, credits.txt)

Usage:
    python render_shorts.py storyboard.json --dry-run     # validate + plan, no network
    python render_shorts.py storyboard.json --tts-only    # voice + captions timing only
    python render_shorts.py storyboard.json               # full render
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass, field
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
AUDIO_SR = 48000
ROLE_ORDER = {"HOOK": 0, "CONFLICT": 1, "BODY": 2, "RESOLUTION": 3}
THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
EST_CHARS_PER_SEC = 13.0  # rough Thai TTS speed at +0% (visible chars only)

DEFAULTS = {
    "voice": {
        "engine": "edge-tts", "voice_id": "th-TH-PremwadeeNeural",
        "rate": "+10%", "pitch": "+0Hz", "volume": "+0%",
        "line_gap_sec": 0.12, "scene_gap_sec": 0.25, "pronunciations": {},
    },
    "render": {
        "width": 1080, "height": 1920, "fps": 30,
        "min_cut_sec": 1.5, "max_cut_sec": 3.0,
        "crf": 18, "preset": "medium", "seed": 42,
    },
    "subtitles": {
        "enabled": True, "font_path": None, "font_index": 0, "font_size": 92,
        "max_chars": 14, "min_chars": 5, "position_y": 0.68,
        "text_color": "#FFFFFF", "highlight_color": "#FFE14D",
        "stroke_color": "#000000", "stroke_width": 10,
        "pop_animation": True, "emphasis_words": [],
    },
    "bgm": {
        "enabled": True, "folder": "music", "file": None, "volume": 0.16,
        "duck": True, "fade_in_sec": 0.5, "fade_out_sec": 1.5,
    },
}

WARNINGS: list[str] = []


# ───────────────────────────── utilities ─────────────────────────────
def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  ⚠️  {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\n❌ {msg}", file=sys.stderr)
    sys.exit(1)


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def sha(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


def run(cmd: list[str], what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-15:])
        die(f"FFmpeg failed during: {what}\n{' '.join(cmd)}\n---\n{tail}")


def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def check_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if not shutil.which(b)]
    if missing:
        die(f"Missing {', '.join(missing)}. On macOS run:  brew install ffmpeg")


def visible_len(s: str) -> int:
    """Characters that occupy horizontal space (Thai upper/lower marks excluded)."""
    return sum(1 for ch in s if not ch.isspace() and unicodedata.category(ch) != "Mn")


def nospace(s: str) -> str:
    return re.sub(r"\s+", "", s)


def hex_rgba(h: str, a: int = 255) -> tuple:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


# ───────────────────────────── data model ─────────────────────────────
@dataclass
class Caption:
    start_f: int
    end_f: int
    text: str


@dataclass
class Line:
    display: str
    spoken: str
    start_f: int = 0          # absolute frame where this line's audio starts
    dur_s: float = 0.0
    words: list = field(default_factory=list)   # edge-tts WordBoundary events
    phrases: list = field(default_factory=list)  # display phrases
    timing_mode: str = ""


@dataclass
class CutPlan:
    scene_id: str
    cut_id: str
    variant: int
    query: str
    fallbacks: list
    shot_type: str
    intent: str
    pinned_id: int | None
    frames: int = 0
    start_f: int = 0
    # filled by footage stage
    video: dict | None = None
    file_url: str = ""
    local: str = ""
    src_start: float = 0.0
    query_used: str = ""


@dataclass
class ScenePlan:
    scene_id: str
    role: str
    lines: list
    cut_specs: list
    start_f: int = 0
    frames: int = 0
    audio_path: Path | None = None
    cuts: list = field(default_factory=list)


# ───────────────────────────── load & validate ─────────────────────────────
def load_storyboard(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")

    schema_path = SCRIPT_DIR / "storyboard.schema.json"
    try:
        import jsonschema
        if schema_path.exists():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                          key=lambda e: list(e.path))
            if errs:
                msgs = [f"  • {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errs[:20]]
                die("Storyboard does not match schema:\n" + "\n".join(msgs))
    except ImportError:
        warn("jsonschema not installed — skipping schema validation")

    errors = []
    sids, cids = set(), set()
    for sc in data.get("scenes", []):
        if sc["scene_id"] in sids:
            errors.append(f"duplicate scene_id {sc['scene_id']}")
        sids.add(sc["scene_id"])
        for c in sc["cuts"]:
            if c["cut_id"] in cids:
                errors.append(f"duplicate cut_id {c['cut_id']}")
            cids.add(c["cut_id"])
            for q in [c["pexels_query"], *c.get("fallback_queries", [])]:
                if THAI_RE.search(q):
                    errors.append(f"{c['cut_id']}: Pexels query must be English: '{q}'")
    if errors:
        die("Storyboard errors:\n" + "\n".join(f"  • {e}" for e in errors))

    roles = [s["role"] for s in data["scenes"]]
    if roles[0] != "HOOK":
        warn("First scene is not HOOK")
    if roles[-1] != "RESOLUTION":
        warn("Last scene is not RESOLUTION")
    if any(ROLE_ORDER[a] > ROLE_ORDER[b] for a, b in zip(roles, roles[1:])):
        warn(f"Role order is not H→C→B→R: {' → '.join(roles)}")
    return data


# ───────────────────────────── text / captions ─────────────────────────────
def apply_pronunciations(text: str, pron: dict) -> str:
    for k in sorted(pron, key=len, reverse=True):
        text = text.replace(k, pron[k])
    return text


_TRIE = None


def tokenizer(extra_words: list[str]):
    global _TRIE
    from pythainlp import word_tokenize
    from pythainlp.corpus.common import thai_words
    from pythainlp.util import Trie
    if _TRIE is None:
        _TRIE = Trie(set(thai_words()) | {w for w in extra_words if w.strip()})
    return lambda t: word_tokenize(t, custom_dict=_TRIE, engine="newmm", keep_whitespace=True)


def _is_attach(t: str) -> bool:
    return all(unicodedata.category(c)[0] in "PS" or c == "ๆ" for c in t)


def _balanced(tokens: list[str], max_chars: int) -> list[str]:
    total = visible_len("".join(tokens))
    if total <= max_chars:
        return ["".join(tokens)]
    k = -(-total // max_chars)
    target = total / k
    out, cur = [], ""
    for t in tokens:
        if cur and not _is_attach(t) and len(out) < k - 1:
            a, b = visible_len(cur), visible_len(cur + t)
            if b > max_chars or (b - target > target - a):
                out.append(cur)
                cur = ""
        cur += t
    if cur:
        out.append(cur)
    return out


def split_phrases(text: str, tok, max_chars: int, min_chars: int) -> list[str]:
    """Group Thai tokens into short, evenly sized Shorts-style caption phrases.
    Spaces in the narration are preferred break points; long runs are split evenly."""
    chunks, cur = [], []
    for t in tok(text):
        if t.isspace():
            if cur:
                chunks.append(cur)
                cur = []
        else:
            cur.append(t)
    if cur:
        chunks.append(cur)

    pieces: list[tuple[str, bool]] = []  # (text, space_before)
    for ch in chunks:
        for i, p in enumerate(_balanced(ch, max_chars)):
            pieces.append((p, i == 0 and bool(pieces)))

    out: list[str] = []
    for p, sp in pieces:
        if out and (visible_len(p) < min_chars or visible_len(out[-1]) < min_chars) \
                and visible_len(out[-1] + p) <= max_chars:
            out[-1] = out[-1] + (" " if sp else "") + p
        else:
            out.append(p)
    return out


def phrase_offsets(line: Line, pron: dict) -> list[float]:
    """Start time (s, relative to line audio) of each phrase.
    Uses edge-tts WordBoundary timings when they align; else proportional to text length."""
    spoken_ph = [nospace(apply_pronunciations(p, pron)) for p in line.phrases]
    joined = "".join(spoken_ph)
    ns = nospace(line.spoken)

    if line.words and joined == ns and ns:
        char_t = [None] * len(ns)
        cursor = 0
        for w in line.words:
            wt = nospace(w["text"])
            if not wt:
                continue
            pos = ns.find(wt, cursor)
            if pos < 0 or pos - cursor > 6:
                continue
            for j in range(len(wt)):
                char_t[pos + j] = w["start"] + w["dur"] * j / len(wt)
            cursor = pos + len(wt)
        covered = sum(t is not None for t in char_t) / len(ns)
        if covered >= 0.7:
            last = 0.0
            for i, t in enumerate(char_t):  # forward-fill gaps
                if t is None:
                    char_t[i] = last
                else:
                    last = t
            offs, idx = [], 0
            for p in spoken_ph:
                offs.append(char_t[idx] if idx < len(char_t) else last)
                idx += len(p)
            offs[0] = 0.0
            for i in range(1, len(offs)):  # keep monotonic
                offs[i] = max(offs[i], offs[i - 1] + 0.05)
            line.timing_mode = "word-boundary"
            return offs

    weights = [max(1, visible_len(p)) for p in spoken_ph]
    total = sum(weights)
    speak = max(0.1, line.dur_s - 0.15)
    offs, acc = [], 0.0
    for w in weights:
        offs.append(acc / total * speak)
        acc += w
    line.timing_mode = "proportional"
    return offs


# ───────────────────────────── TTS ─────────────────────────────
async def _tts_one(text: str, v: dict, mp3: Path, words_json: Path, sem: asyncio.Semaphore):
    import edge_tts
    async with sem:
        for attempt in range(1, 4):
            try:
                kw = dict(voice=v["voice_id"], rate=v["rate"], pitch=v["pitch"], volume=v["volume"])
                try:
                    comm = edge_tts.Communicate(text, boundary="WordBoundary", **kw)
                except TypeError:  # edge-tts < 7
                    comm = edge_tts.Communicate(text, **kw)
                words = []
                tmp = mp3.with_suffix(".part")
                with open(tmp, "wb") as f:
                    async for ch in comm.stream():
                        if ch["type"] == "audio":
                            f.write(ch["data"])
                        elif ch["type"] == "WordBoundary":
                            words.append({"start": ch["offset"] / 1e7,
                                          "dur": ch["duration"] / 1e7, "text": ch["text"]})
                if tmp.stat().st_size < 1000:
                    raise RuntimeError("empty audio returned")
                tmp.replace(mp3)
                words_json.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                return
            except Exception as e:  # network / service hiccup
                if attempt == 3:
                    raise RuntimeError(f"edge-tts failed for '{text[:40]}…': {e}") from e
                await asyncio.sleep(2 * attempt)


def synthesize_lines(lines: list[Line], v: dict, cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    jobs, sem = [], None
    targets = []
    for ln in lines:
        key = sha(ln.spoken, v["voice_id"], v["rate"], v["pitch"], v["volume"])
        mp3, wj = cache / f"{key}.mp3", cache / f"{key}.words.json"
        targets.append((ln, mp3, wj))
        if not (mp3.exists() and wj.exists()):
            jobs.append((ln.spoken, mp3, wj))

    if jobs:
        log(f"  generating {len(jobs)} line(s) with {v['voice_id']} (rate {v['rate']}) …")

        async def main():
            s = asyncio.Semaphore(4)
            await asyncio.gather(*[_tts_one(t, v, m, w, s) for t, m, w in jobs])
        try:
            asyncio.run(main())
        except RuntimeError as e:
            die(f"{e}\nTip: pip install -U edge-tts (Microsoft changes the endpoint occasionally).")
    else:
        log("  all lines cached ✓")

    for ln, mp3, wj in targets:
        ln.words = json.loads(wj.read_text(encoding="utf-8"))
        ln.mp3 = mp3  # type: ignore[attr-defined]


def decode_pcm(mp3: Path, out_wav: Path) -> bytes:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(AUDIO_SR),
         "-sample_fmt", "s16", str(out_wav)], "decode TTS")
    with wave.open(str(out_wav), "rb") as w:
        return w.readframes(w.getnframes())


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(AUDIO_SR)
        w.writeframes(pcm)


# ───────────────────────────── cut allocation ─────────────────────────────
def allocate_cuts(scene: ScenePlan, fps: int, min_s: float, max_s: float) -> list[CutPlan]:
    """Split scene duration into sub-cuts within [min_s, max_s], frame-exact."""
    D = scene.frames / fps
    specs = scene.cut_specs
    items = [(i, 0, float(c["duration_hint_sec"])) for i, c in enumerate(specs)]  # (spec idx, variant, weight)

    n = len(items)
    while D / n > max_s:
        n += 1
    while n > 1 and D / n < min_s:
        n -= 1

    while len(items) < n:  # split the heaviest cut → alternate clip, same keyword
        k = max(range(len(items)), key=lambda j: items[j][2])
        si, _, w = items[k]
        var = 1 + max(v for s2, v, _ in items if s2 == si)
        items[k:k + 1] = [(si, items[k][1], w / 2), (si, var, w / 2)]
    if len(items) > n:
        dropped = []
        while len(items) > n:  # drop lightest cut, give its weight to a neighbour
            k = min(range(len(items)), key=lambda j: items[j][2])
            nb = k - 1 if k > 0 else 1
            si, var, w = items[nb]
            items[nb] = (si, var, w + items[k][2])
            dropped.append(specs[items[k][0]]["cut_id"])
            items.pop(k)
        warn(f"{scene.scene_id}: scene is only {D:.2f}s → dropped cut(s) {', '.join(dropped)}")
    if len(items) != len(specs) and len(items) > len(specs):
        warn(f"{scene.scene_id}: {D:.2f}s of audio needs {len(items)} cuts "
             f"(storyboard has {len(specs)}) → extra cuts reuse keywords with different clips")
    if D < min_s:
        warn(f"{scene.scene_id}: scene is {D:.2f}s (< min cut {min_s}s) → single short cut")

    # proportional + clamp (water-filling)
    w = [it[2] for it in items]
    d = [x / sum(w) * D for x in w]
    lo, hi = (min_s, max_s) if D >= min_s else (0, D)
    for _ in range(50):
        d = [min(max(x, lo), hi) for x in d]
        diff = D - sum(d)
        if abs(diff) < 1e-6:
            break
        free = [j for j in range(len(d)) if (diff > 0 and d[j] < hi - 1e-9) or (diff < 0 and d[j] > lo + 1e-9)]
        if not free:
            break
        fw = sum(w[j] for j in free)
        for j in free:
            d[j] += diff * w[j] / fw

    # frame quantization with cumulative rounding
    cuts, acc, prev = [], 0.0, 0
    for j, (si, var, _) in enumerate(items):
        acc += d[j]
        edge = scene.frames if j == len(items) - 1 else round(acc * fps)
        frames = max(1, edge - prev)
        c = specs[si]
        cuts.append(CutPlan(
            scene_id=scene.scene_id, cut_id=c["cut_id"], variant=var,
            query=c["pexels_query"], fallbacks=c.get("fallback_queries", []),
            shot_type=c["shot_type"], intent=c.get("visual_intent", ""),
            pinned_id=c.get("pexels_video_id") if var == 0 else None,
            frames=frames, start_f=scene.start_f + prev))
        prev += frames
    return cuts


# ───────────────────────────── Pexels ─────────────────────────────
class Pexels:
    SEARCH = "https://api.pexels.com/videos/search"
    VIDEO = "https://api.pexels.com/videos/videos/{}"

    def __init__(self, key: str, cache: Path, refresh: bool):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": key, "User-Agent": "render-shorts/1.0"})
        self.cache = cache
        (cache / "search").mkdir(parents=True, exist_ok=True)
        (cache / "footage").mkdir(parents=True, exist_ok=True)
        self.refresh = refresh
        self.used: set[int] = set()

    def _get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(1, 5):
            try:
                r = self.s.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                if attempt == 4:
                    die(f"Pexels network error: {e}")
                time.sleep(2 * attempt)
                continue
            if r.status_code == 401:
                die("Pexels API key rejected (401). Check PEXELS_API_KEY.")
            if r.status_code == 429:
                wait = 60 * attempt
                warn(f"Pexels rate limit hit — waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return {}
            if r.ok:
                return r.json()
            time.sleep(2 * attempt)
        die(f"Pexels request failed repeatedly: {url}")
        return {}

    def search(self, query: str, orientation: str | None) -> list[dict]:
        cf = self.cache / "search" / f"{sha(query, orientation)}.json"
        if cf.exists() and not self.refresh:
            return json.loads(cf.read_text(encoding="utf-8"))
        params = {"query": query, "per_page": 40, "size": "medium"}
        if orientation:
            params["orientation"] = orientation
        vids = self._get(self.SEARCH, params).get("videos", [])
        cf.write_text(json.dumps(vids), encoding="utf-8")
        return vids

    def by_id(self, vid: int) -> dict | None:
        cf = self.cache / "search" / f"id_{vid}.json"
        if cf.exists():
            return json.loads(cf.read_text(encoding="utf-8"))
        v = self._get(self.VIDEO.format(vid)) or None
        if v:
            cf.write_text(json.dumps(v), encoding="utf-8")
        return v

    @staticmethod
    def best_file(video: dict, W: int, H: int) -> tuple[dict | None, float]:
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
        if not files:
            return None, 99.0

        def scale(f):
            return max(W / f["width"], H / f["height"])
        good = [f for f in files if scale(f) <= 1.0]
        if good:  # smallest file that needs no upscaling
            f = min(good, key=lambda f: f["width"] * f["height"])
        else:
            f = min(files, key=scale)
        return f, scale(f)

    def choose(self, cut: CutPlan, need_s: float, W: int, H: int) -> None:
        if cut.pinned_id:
            v = self.by_id(cut.pinned_id)
            if v:
                if v.get("duration", 0) < need_s:
                    warn(f"{cut.cut_id}: pinned clip is {v.get('duration')}s < {need_s:.2f}s → it will loop")
                self._accept(cut, v, f"pinned:{cut.pinned_id}", W, H)
                return
            warn(f"{cut.cut_id}: pinned Pexels id {cut.pinned_id} not found → searching")

        queries = [cut.query, *cut.fallbacks]
        backup = None
        # tiers: (orientation, max upscale). Sharp portrait first, landscape 4K crop last.
        for orientation, max_scale in (("portrait", 1.0), ("portrait", 1.5), (None, 1.5)):
            for q in queries:
                for v in self.search(q, orientation):
                    if v["id"] in self.used:
                        continue
                    if orientation is None and v.get("width", 0) > v.get("height", 1):
                        # landscape last resort: only if tall enough to crop 9:16 decently
                        if v.get("height", 0) < 2160:
                            continue
                    f, sc = self.best_file(v, W, H)
                    if not f or sc > max_scale:
                        continue
                    if v.get("duration", 0) >= need_s + 0.3:
                        self._accept(cut, v, q, W, H)
                        return
                    if backup is None:
                        backup = (v, q)
        if backup:
            warn(f"{cut.cut_id}: no clip long enough for '{cut.query}' → looping a shorter clip")
            self._accept(cut, *backup, W, H)
            return
        # absolute last resort: allow reuse of the primary query's first result
        for q in queries:
            vids = self.search(q, "portrait") or self.search(q, None)
            if vids:
                warn(f"{cut.cut_id}: all results already used → reusing a clip for '{q}'")
                self._accept(cut, vids[0], q, W, H)
                return
        die(f"{cut.cut_id}: Pexels returned nothing for {queries}. Use broader English queries.")

    def _accept(self, cut: CutPlan, v: dict, q: str, W: int, H: int) -> None:
        f, sc = self.best_file(v, W, H)
        if not f:
            die(f"{cut.cut_id}: Pexels video {v['id']} has no MP4 file")
        if sc > 1.25:
            warn(f"{cut.cut_id}: clip {v['id']} will be upscaled {sc:.2f}× (may look soft)")
        self.used.add(v["id"])
        cut.video, cut.file_url, cut.query_used = v, f["link"], q
        cut.local = str(self.cache / "footage" / f"pexels_{v['id']}_{f['id']}.mp4")

    def download(self, cut: CutPlan) -> None:
        dst = Path(cut.local)
        if dst.exists() and dst.stat().st_size > 10_000:
            return
        tmp = dst.with_suffix(".part")
        for attempt in range(1, 4):
            try:
                with self.s.get(cut.file_url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.replace(dst)
                return
            except requests.RequestException as e:
                if attempt == 3:
                    die(f"Download failed for {cut.cut_id}: {e}")
                time.sleep(3 * attempt)


# ───────────────────────────── video segments ─────────────────────────────
def render_segment(cut: CutPlan, out: Path, W: int, H: int, fps: int, rng: random.Random) -> None:
    src = Path(cut.local)
    dur = cut.frames / fps
    src_dur = ffprobe_duration(src)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H},setsar=1,fps={fps},format=yuv420p")
    common = ["-an", "-vf", vf, "-frames:v", str(cut.frames), "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)]
    if src_dur >= dur + 0.15:
        max_start = max(0.0, min(src_dur - dur - 0.1, src_dur * 0.5))
        start = round(rng.uniform(min(0.3, max_start), max_start), 2) if max_start > 0 else 0.0
        cut.src_start = start
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start}", "-i", str(src), *common]
    else:
        cut.src_start = 0.0
        cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), *common]
    run(cmd, f"segment {cut.cut_id}")


# ───────────────────────────── caption images ─────────────────────────────
def find_font(cfg: dict) -> tuple[str, int]:
    if cfg.get("font_path"):
        p = Path(cfg["font_path"]).expanduser()
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        if not p.exists():
            die(f"font_path not found: {p}")
        return str(p), cfg.get("font_index", 0)
    local = sorted((SCRIPT_DIR / "fonts").glob("*.[tToO][tT][fFcC]"))
    local.sort(key=lambda p: (0 if re.search("bold|black|heavy", p.name, re.I) else 1, p.name))
    candidates = [*local,
                  *map(Path, [
                      os.path.expanduser("~/Library/Fonts/Kanit-Bold.ttf"),
                      os.path.expanduser("~/Library/Fonts/Prompt-Bold.ttf"),
                      "/Library/Fonts/Kanit-Bold.ttf",
                      "/System/Library/Fonts/Supplemental/SukhumvitSet.ttc",
                      "/System/Library/Fonts/SukhumvitSet.ttc",
                      "/System/Library/Fonts/Thonburi.ttc",
                      "/System/Library/Fonts/Supplemental/Thonburi.ttc",
                      "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf",
                  ])]
    for p in candidates:
        if p.exists():
            idx = 1 if p.suffix.lower() == ".ttc" and "Thonburi" in p.name else 0  # Thonburi Bold
            return str(p), idx
    die("No Thai font found. Put a Thai font (e.g. Kanit-Bold.ttf from Google Fonts) into ./fonts/")
    return "", 0


class CaptionRenderer:
    def __init__(self, cfg: dict, W: int, H: int, out_dir: Path):
        from PIL import ImageFont, features
        self.cfg, self.W, self.H, self.dir = cfg, W, H, out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.font_path, self.font_index = find_font(cfg)
        self.raqm = features.check("raqm")
        if not self.raqm:
            warn("Pillow has no RAQM layout → Thai tone marks may overlap. "
                 "Fix: brew install libraqm && pip install --force-reinstall --no-binary :all: Pillow")
        self.layout = ImageFont.Layout.RAQM if self.raqm else ImageFont.Layout.BASIC
        self._fonts = {}
        self.emph = sorted({w for w in cfg.get("emphasis_words", []) if w}, key=len, reverse=True)
        log(f"  caption font: {self.font_path}")

    def font(self, size: int):
        from PIL import ImageFont
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size, index=self.font_index,
                                                   layout_engine=self.layout)
        return self._fonts[size]

    def _segments(self, text: str) -> list[tuple[str, bool]]:
        if not self.emph:
            return [(text, False)]
        pat = re.compile("|".join(map(re.escape, self.emph)))
        segs, pos = [], 0
        for m in pat.finditer(text):
            if m.start() > pos:
                segs.append((text[pos:m.start()], False))
            segs.append((m.group(0), True))
            pos = m.end()
        if pos < len(text):
            segs.append((text[pos:], False))
        return segs

    def blank(self) -> Path:
        from PIL import Image
        p = self.dir / "blank.png"
        if not p.exists():
            Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0)).save(p)
        return p

    def render(self, text: str, scale: float = 1.0) -> Path:
        from PIL import Image, ImageDraw
        c = self.cfg
        p = self.dir / f"cap_{sha(text, scale, c)}.png"
        if p.exists():
            return p
        size = int(c["font_size"] * scale)
        segs = self._segments(text)
        font = self.font(size)
        total = sum(font.getlength(s) for s, _ in segs)
        max_w = self.W * 0.88 * scale
        while total > max_w and size > 36:  # shrink long phrases to fit
            size -= 4
            font = self.font(size)
            total = sum(font.getlength(s) for s, _ in segs)
        sw = max(1, int(c["stroke_width"] * size / c["font_size"])) if c["stroke_width"] else 0
        img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = self.H * c["position_y"]
        # soft drop shadow
        x = (self.W - total) / 2
        for s, _ in segs:
            d.text((x + 5, y + 7), s, font=font, fill=(0, 0, 0, 120), anchor="lm",
                   stroke_width=sw, stroke_fill=(0, 0, 0, 120))
            x += font.getlength(s)
        x = (self.W - total) / 2
        for s, is_emph in segs:
            col = hex_rgba(c["highlight_color"] if is_emph else c["text_color"])
            d.text((x, y), s, font=font, fill=col, anchor="lm",
                   stroke_width=sw, stroke_fill=hex_rgba(c["stroke_color"]))
            x += font.getlength(s)
        img.save(p, optimize=True)
        return p


def build_caption_track(caps: list[Caption], total_f: int, fps: int, rend: CaptionRenderer,
                        work: Path) -> Path:
    """Timeline of PNGs -> transparent QuickTime (qtrle/argb) overlay track."""
    entries: list[tuple[Path, int]] = []  # (image, frames)
    cursor = 0
    pop = [0.86, 0.95] if rend.cfg.get("pop_animation", True) else []
    for cp in caps:
        if cp.start_f > cursor:
            entries.append((rend.blank(), cp.start_f - cursor))
        length = cp.end_f - cp.start_f
        used = 0
        for sc in pop:
            if length - used > len(pop) + 2:
                entries.append((rend.render(cp.text, sc), 1))
                used += 1
        entries.append((rend.render(cp.text), length - used))
        cursor = cp.end_f
    if cursor < total_f:
        entries.append((rend.blank(), total_f - cursor))

    lst = work / "captions.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for img, n in entries:
            f.write(f"file '{img.resolve()}'\nduration {n / fps:.6f}\n")
        f.write(f"file '{entries[-1][0].resolve()}'\n")
    out = work / "captions.mov"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-vf", f"fps={fps},format=argb", "-frames:v", str(total_f),
         "-c:v", "qtrle", str(out)], "caption track")
    return out


# ───────────────────────────── BGM ─────────────────────────────
def pick_bgm(cfg: dict, rng: random.Random) -> Path | None:
    folder = Path(cfg["folder"]).expanduser()
    if not folder.is_absolute():
        folder = SCRIPT_DIR / folder
    if cfg.get("file"):
        p = folder / cfg["file"]
        if p.exists():
            return p
        warn(f"BGM file not found: {p}")
        return None
    exts = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in exts) if folder.exists() else []
    if not files:
        warn(f"No music in {folder} → rendering without BGM")
        return None
    return rng.choice(files)


# ───────────────────────────── final mux ─────────────────────────────
def final_mux(video: Path, voice: Path, captions: Path | None, bgm: Path | None,
              bcfg: dict, rcfg: dict, total_f: int, out: Path) -> None:
    fps = rcfg["fps"]
    T = total_f / fps
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(voice)]
    idx = 2
    cap_i = bgm_i = None
    if captions:
        cmd += ["-i", str(captions)]
        cap_i, idx = idx, idx + 1
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
        bgm_i = idx

    fc = []
    if cap_i is not None:
        fc.append(f"[0:v][{cap_i}:v]overlay=0:0:format=auto,format=yuv420p[v]")
    else:
        fc.append("[0:v]format=yuv420p[v]")
    fc.append("[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000,"
              "aformat=sample_fmts=fltp:channel_layouts=stereo[vox]")
    if bgm_i is not None:
        fi, fo = bcfg["fade_in_sec"], min(bcfg["fade_out_sec"], T / 2)
        fc.append(f"[{bgm_i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"atrim=0:{T:.3f},asetpts=PTS-STARTPTS,volume={bcfg['volume']},"
                  f"afade=t=in:st=0:d={fi},afade=t=out:st={max(0, T - fo):.3f}:d={fo}[bg0]")
        if bcfg.get("duck", True):
            fc.append("[vox]asplit=2[vox1][vsc]")
            fc.append("[bg0][vsc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=450:makeup=1[bg]")
            fc.append("[vox1][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                      "alimiter=limit=0.95[a]")
        else:
            fc.append("[vox][bg0]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                      "alimiter=limit=0.95[a]")
    else:
        fc.append("[vox]alimiter=limit=0.95[a]")

    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", rcfg["preset"], "-crf", str(rcfg["crf"]),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{T:.3f}", "-movflags", "+faststart", str(out)]
    run(cmd, "final mux")


# ───────────────────────────── main pipeline ─────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Render a YouTube Short from storyboard.json")
    ap.add_argument("storyboard", nargs="?", default="storyboard.json")
    ap.add_argument("-o", "--out", default="output/final_shorts.mp4")
    ap.add_argument("--dry-run", action="store_true", help="validate + print plan, no network")
    ap.add_argument("--tts-only", action="store_true", help="generate voice + timing, skip footage")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--refresh-footage", action="store_true", help="ignore cached Pexels searches")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(SCRIPT_DIR / ".env")
        load_dotenv()
    except ImportError:
        pass

    sb_path = Path(args.storyboard)
    if not sb_path.exists():
        die(f"Storyboard not found: {sb_path}")
    log(f"📄 Loading {sb_path}")
    data = load_storyboard(sb_path)
    cfg = {k: deep_merge(DEFAULTS[k], data.get(k, {})) for k in DEFAULTS}
    v, r, s, b = cfg["voice"], cfg["render"], cfg["subtitles"], cfg["bgm"]
    if args.no_subs:
        s["enabled"] = False
    if args.no_bgm:
        b["enabled"] = False
    seed = args.seed if args.seed is not None else r["seed"]
    W, H, fps = r["width"], r["height"], r["fps"]
    if r["min_cut_sec"] >= r["max_cut_sec"]:
        die("render.min_cut_sec must be < max_cut_sec")

    scenes = [ScenePlan(sc["scene_id"], sc["role"],
                        [Line(t.strip(), apply_pronunciations(t.strip(), v["pronunciations"]))
                         for t in sc["narration_lines"]], sc["cuts"]) for sc in data["scenes"]]

    # ── dry run: estimates only ──
    rate = 1 + int(v["rate"].rstrip("%")) / 100
    est_total = 0.0
    log(f"\n🎬 {data['meta']['title']}  |  voice {v['voice_id']} {v['rate']}")
    for sc in scenes:
        chars = sum(visible_len(l.spoken) for l in sc.lines)
        est = chars / (EST_CHARS_PER_SEC * rate) + v["line_gap_sec"] * (len(sc.lines) - 1) + v["scene_gap_sec"]
        est_total += est
        need = max(1, round(est / ((r["min_cut_sec"] + r["max_cut_sec"]) / 2)))
        log(f"  [{sc.role:<10}] {sc.scene_id}: ~{est:4.1f}s  | {len(sc.cut_specs)} cuts (≈{need} needed)")
        for c in sc.cut_specs:
            log(f"      - {c['cut_id']:<6} {c['shot_type']:<17} '{c['pexels_query']}'")
    target = data["meta"].get("target_duration_sec", 45)
    log(f"  ≈ {est_total:.1f}s estimated (target {target}s; real length known after TTS)")
    if not 25 <= est_total <= 65:
        warn(f"Estimated length {est_total:.0f}s is outside the 30–60s sweet spot")
    if args.dry_run:
        log("\n✅ Dry run OK" + (f" ({len(WARNINGS)} warning(s))" if WARNINGS else ""))
        return

    check_binaries()
    rng = random.Random(seed)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = SCRIPT_DIR / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cache = SCRIPT_DIR / "cache"
    work = SCRIPT_DIR / "build" / sb_path.stem
    if work.exists() and not args.keep_temp:
        shutil.rmtree(work, ignore_errors=True)
    for d in ("audio", "segments", "captions"):
        (work / d).mkdir(parents=True, exist_ok=True)

    # ── 1. TTS ──
    log("\n🎙️  1/5 Voiceover (edge-tts)")
    all_lines = [ln for sc in scenes for ln in sc.lines]
    synthesize_lines(all_lines, v, cache / "tts")

    silence = lambda sec: b"\x00\x00" * int(round(sec * AUDIO_SR))
    spf = AUDIO_SR // fps if AUDIO_SR % fps == 0 else AUDIO_SR / fps
    voice_pcm = bytearray()
    frame_cursor = 0
    for sc in scenes:
        pcm = bytearray()
        sc.start_f = frame_cursor
        for i, ln in enumerate(sc.lines):
            if i:
                pcm += silence(v["line_gap_sec"])
            ln.start_f = frame_cursor + round(len(pcm) / 2 / spf)
            chunk = decode_pcm(ln.mp3, work / "audio" / f"{sc.scene_id}_{i}.wav")  # type: ignore[attr-defined]
            ln.dur_s = len(chunk) / 2 / AUDIO_SR
            pcm += chunk
        pcm += silence(v["scene_gap_sec"])
        sc.frames = max(1, round(len(pcm) / 2 / spf))
        target_bytes = int(round(sc.frames * spf)) * 2
        pcm = pcm[:target_bytes] + b"\x00" * max(0, target_bytes - len(pcm))  # frame-exact
        sc.audio_path = work / "audio" / f"{sc.scene_id}.wav"
        write_wav(sc.audio_path, bytes(pcm))
        voice_pcm += pcm
        frame_cursor += sc.frames
        log(f"  {sc.scene_id} [{sc.role}] {sc.frames / fps:5.2f}s  ({len(sc.lines)} line(s))")
    total_f = frame_cursor
    voice_wav = work / "audio" / "voice.wav"
    write_wav(voice_wav, bytes(voice_pcm))
    T = total_f / fps
    log(f"  total voice: {T:.2f}s")
    if T > 60:
        warn(f"Final length {T:.1f}s > 60s — trim narration or raise voice.rate")
    elif T < 30:
        warn(f"Final length {T:.1f}s < 30s")

    # ── 2. Captions timing ──
    captions: list[Caption] = []
    if s["enabled"]:
        log("\n💬 2/5 Caption timing (pythainlp)")
        tok = tokenizer(list(v["pronunciations"].keys()) + s["emphasis_words"])
        for sc in scenes:
            for ln in sc.lines:
                ln.phrases = split_phrases(ln.display, tok, s["max_chars"], s["min_chars"])
                offs = phrase_offsets(ln, v["pronunciations"])
                line_end_f = ln.start_f + round(ln.dur_s * fps)
                starts = [ln.start_f + round(o * fps) for o in offs]
                for j, ph in enumerate(ln.phrases):
                    st = max(starts[j], captions[-1].end_f if captions else 0)
                    en = starts[j + 1] if j + 1 < len(starts) else line_end_f
                    if en - st >= 2:
                        captions.append(Caption(st, min(en, total_f), ph))
        modes = {}
        for ln in all_lines:
            modes[ln.timing_mode] = modes.get(ln.timing_mode, 0) + 1
        log(f"  {len(captions)} phrases  |  timing: " + ", ".join(f"{k} ×{n}" for k, n in modes.items()))
    else:
        log("\n💬 2/5 Captions disabled")

    # ── 3. Cut allocation ──
    log("\n✂️  3/5 Cut plan")
    for sc in scenes:
        sc.cuts = allocate_cuts(sc, fps, r["min_cut_sec"], r["max_cut_sec"])
        log(f"  {sc.scene_id}: " + " | ".join(
            f"{c.cut_id}{'′' * c.variant} {c.frames / fps:.2f}s" for c in sc.cuts))
    all_cuts = [c for sc in scenes for c in sc.cuts]

    timeline = {
        "title": data["meta"]["title"], "fps": fps, "duration_sec": round(T, 3), "seed": seed,
        "voice": {k: v[k] for k in ("voice_id", "rate", "pitch", "volume")},
        "scenes": [{
            "scene_id": sc.scene_id, "role": sc.role,
            "start_sec": round(sc.start_f / fps, 3), "duration_sec": round(sc.frames / fps, 3),
            "lines": [{"text": ln.display, "start_sec": round(ln.start_f / fps, 3),
                       "dur_sec": round(ln.dur_s, 3), "phrases": ln.phrases,
                       "caption_timing": ln.timing_mode} for ln in sc.lines],
            "cuts": [{"cut_id": c.cut_id, "variant": c.variant, "shot_type": c.shot_type,
                      "start_sec": round(c.start_f / fps, 3), "duration_sec": round(c.frames / fps, 3),
                      "query": c.query} for c in sc.cuts],
        } for sc in scenes],
        "captions": [{"start": round(c.start_f / fps, 3), "end": round(c.end_f / fps, 3), "text": c.text}
                     for c in captions],
    }
    tl_path = out_path.parent / "timeline.json"

    if args.tts_only:
        preview = out_path.parent / "voice_preview.wav"
        shutil.copy(voice_wav, preview)
        tl_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"\n✅ TTS-only done → {preview}\n   timing → {tl_path}")
        return

    # ── 4. Footage ──
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        die("PEXELS_API_KEY is not set. Put it in .env or export it.")
    log("\n🎞️  4/5 Pexels footage")
    px = Pexels(key, cache / "pexels", args.refresh_footage)
    for c in all_cuts:
        px.choose(c, c.frames / fps, W, H)
    for i, c in enumerate(all_cuts, 1):
        px.download(c)
        log(f"  [{i:>2}/{len(all_cuts)}] {c.cut_id}{'′' * c.variant:<2} ← pexels #{c.video['id']} "
            f"({c.video.get('duration', '?')}s) via '{c.query_used}'")

    log("  normalizing clips → 1080x1920 …")
    seg_list = work / "segments.txt"
    with open(seg_list, "w", encoding="utf-8") as f:
        for i, c in enumerate(all_cuts):
            seg = work / "segments" / f"{i:03d}_{c.cut_id}_{c.variant}.mp4"
            render_segment(c, seg, W, H, fps, rng)
            f.write(f"file '{seg.resolve()}'\n")
    video_only = work / "video_only.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(seg_list),
         "-c", "copy", str(video_only)], "concat segments")

    # ── 5. Compose ──
    log("\n🎚️  5/5 Captions + BGM + final encode")
    cap_track = None
    if s["enabled"] and captions:
        rend = CaptionRenderer(s, W, H, work / "captions")
        cap_track = build_caption_track(captions, total_f, fps, rend, work)
    bgm = pick_bgm(b, rng) if b["enabled"] else None
    if bgm:
        log(f"  BGM: {bgm.name} (vol {b['volume']}, ducking {'on' if b['duck'] else 'off'})")
    final_mux(video_only, voice_wav, cap_track, bgm, b, r, total_f, out_path)

    # ── reports ──
    for sc_json, sc in zip(timeline["scenes"], scenes):
        for cj, c in zip(sc_json["cuts"], sc.cuts):
            cj.update({"pexels_video_id": c.video["id"], "pexels_url": c.video.get("url"),
                       "author": (c.video.get("user") or {}).get("name"),
                       "query_used": c.query_used, "source_start_sec": c.src_start})
    timeline["bgm"] = bgm.name if bgm else None
    timeline["warnings"] = WARNINGS
    tl_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    credits = out_path.parent / "credits.txt"
    seen, lines_out = set(), ["Stock footage from Pexels (https://www.pexels.com):"]
    for c in all_cuts:
        vid = c.video["id"]
        if vid not in seen:
            seen.add(vid)
            lines_out.append(f"- {(c.video.get('user') or {}).get('name', 'Unknown')} — {c.video.get('url')}")
    if bgm:
        lines_out += ["", f"Music: {bgm.name}"]
    credits.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    if not args.keep_temp:
        shutil.rmtree(work, ignore_errors=True)
    real = ffprobe_duration(out_path)
    log(f"\n✅ Done → {out_path}  ({real:.2f}s, {len(all_cuts)} cuts, {len(captions)} captions)")
    log(f"   timeline → {tl_path}\n   credits  → {credits}")
    if WARNINGS:
        log(f"   {len(WARNINGS)} warning(s) — see timeline.json")


if __name__ == "__main__":
    main()
