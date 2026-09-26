import sys
import time

import pytest

import render_shorts as R
from gui import runner as RU


def test_parse_line_reads_progress_events():
    line = R.PROGRESS_PREFIX + '{"stage": 4, "stages": 5, "label": "x", "done": 5, "total": 10}\n'
    ev = RU.parse_line(line)
    assert ev == RU.Progress(stage=4, stages=5, label="x", done=5, total=10)
    assert ev.fraction == pytest.approx((3 + 0.5) / 5)


def test_parse_line_ignores_normal_log_and_garbage():
    assert RU.parse_line("  S1 [HOOK] 3.10s\n") is None
    assert RU.parse_line(R.PROGRESS_PREFIX + "{broken\n") is None


def test_fraction_without_total_counts_stage_start():
    assert RU.Progress(1, 5, "Voiceover", 0, 0).fraction == 0.0
    assert RU.Progress(5, 5, "Done", 3, 3).fraction == 1.0


def test_build_command():
    cmd = RU.build_command("my_clip", "render", video="final_v2.mp4")
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("render_shorts.py")
    assert cmd[2:] == ["my_clip", "--progress", "-o", "final_v2.mp4"]
    assert RU.build_command("x", "dry")[2:] == ["x", "--progress", "--dry-run"]
    assert RU.build_command("x", "tts")[2:] == ["x", "--progress", "--tts-only"]
    with pytest.raises(ValueError):
        RU.build_command("x", "nope")


def test_registry_blocks_second_job_and_cancels():
    reg = RU.JobRegistry()
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    proc = reg.start("p", sleeper)
    with pytest.raises(RU.JobRunning):
        reg.start("p", sleeper)
    assert reg.cancel("p") is True
    proc.wait(timeout=5)
    assert proc.returncode != 0
    reg.finish("p")
    reg.start("p", [sys.executable, "-c", "pass"]).wait(timeout=5)


def test_stream_lines_yields_output():
    reg = RU.JobRegistry()
    proc = reg.start("q", [sys.executable, "-c", "print('a'); print('b')"])
    assert [l.strip() for l in RU.stream_lines(proc)] == ["a", "b"]
    reg.finish("q")
