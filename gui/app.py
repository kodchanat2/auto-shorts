"""Gradio layout and event wiring. Logic lives in handlers/projects/prompt/settings/cuts/runner."""
from __future__ import annotations

import time

import gradio as gr

from render_shorts import PROJECTS_DIR

from . import handlers as H
from . import overlays as O
from . import projects as P
from . import prompt as PR
from . import runner as RU
from . import settings as S
from . import waveform as W
from .theme import CSS, HEAD, THEME, progress_bar

RANDOM_MUSIC = "(สุ่มตาม seed)"
DUCK_MIN, DUCK_MAX = 1.0, 2.0
CUT_HINT = "กดที่รูปแล้วกด 🎲 สุ่มคลิปใหม่ ถ้าคลิปของคัตนั้นไม่ถูกใจ"
WAVE_USED = "#e4572e"      # from the playhead (= start offset) onward: what the clip plays
WAVE_SKIPPED = "#6f675c"   # before the playhead: skipped intro
LOG_LINES = 300
UI_REFRESH_SEC = 0.25
JOBS = RU.JobRegistry()


# ───────────────────────── wizard ─────────────────────────
def wizard_step1(name, topic, tone, duration, wiz_name):
    name = (name or "").strip()
    err = None if name and name == wiz_name else P.validate_new_name(name)
    if not err and not (topic or "").strip():
        err = "กรุณาใส่เนื้อหาของคลิป"
    if not err and not (tone or "").strip():
        err = "กรุณาใส่โทนของคลิป"
    if err:
        return {step1_msg: f"❌ {err}"}
    brief = P.Brief(topic=topic.strip(), tone=tone.strip(), duration=int(duration))
    P.save_brief(H.project_dir(name), brief)
    return {step1_msg: "", prompt_box: PR.build_prompt(PR.load_template(), brief),
            wizard: gr.Walkthrough(selected=2), wiz_state: name}


def wizard_step3(wiz_name, pasted):
    if not wiz_name:
        return {step3_msg: "❌ ยังไม่ได้ทำขั้นที่ 1"}
    res = H.check_and_save(wiz_name, pasted or "")
    if not res.ok:
        return {step3_msg: res.report, fix_box: gr.Textbox(value=res.fix_prompt, visible=True)}
    # reset the wizard so the next project starts clean (and can't overwrite this one's brief)
    return {step3_msg: "", fix_box: gr.Textbox(value="", visible=False),
            name_in: "", topic_in: "", tone_in: "", paste_in: "", prompt_box: "", step1_msg: "",
            wizard: gr.Walkthrough(selected=1), wiz_state: "",
            tabs: gr.Tabs(selected="project"),
            project_dd: gr.Dropdown(choices=P.list_projects(), value=wiz_name)}


# ───────────────────────── project page ─────────────────────────
def _outputs_for(name):
    vids = P.list_videos(H.project_dir(name))
    items, infos = H.gallery(name)
    warns = H.timeline_warnings(name)
    return {
        voice: H.voice_preview(name),
        video_dd: gr.Dropdown(choices=[v.name for v in vids], value=vids[0].name if vids else None),
        video: str(vids[0]) if vids else None,
        warnings_md: ("**Warnings**\n" + "\n".join(f"- {w}" for w in warns)) if warns else "",
        cut_gallery: items, cuts_state: infos, selected_state: None,
        cut_md: CUT_HINT if items else "ยังไม่มีคัต — กด **Render** แล้วคลิปของแต่ละคัตจะขึ้นที่นี่",
    }


def _music_path(music):
    return S.MUSIC_DIR / music if music and music != RANDOM_MUSIC else None


def _music_view(name, music, start):
    """Player parked at the start offset (its waveform greys out the skipped intro),
    start slider (max = track length) and a caption with the span the clip will use."""
    path = _music_path(music)
    if path is None or not path.exists():
        return {music_audio: gr.Audio(value=None, playback_position=0),
                start_sl: gr.Slider(value=0, maximum=1, interactive=False),
                wave_md: "สุ่มเพลงตาม seed — เลือกเพลงเพื่อกำหนดจุดเริ่ม"}
    total = W.duration(path)
    start = max(0.0, min(float(start or 0), total))
    clip = H.clip_length(name) if name else P.DEFAULT_DURATION
    return {music_audio: gr.Audio(value=str(path), playback_position=start),
            start_sl: gr.Slider(value=start, maximum=round(total, 1), interactive=True),
            wave_md: W.caption(start, clip, total)}


def _voice_view(vs):
    choices = S.voices_for(vs.engine)
    voice = vs.voice_id if vs.voice_id in choices else S.default_voice(vs.engine)
    return {engine_dd: vs.engine, voice_dd: gr.Dropdown(choices=choices, value=voice),
            style_tb: gr.Textbox(value=vs.style, visible=vs.engine == "gemini"), rate_sl: vs.rate_pct}


def change_engine(engine, style):
    """User switched engine: offer that engine's voices, starting from its default."""
    view = _voice_view(S.VoiceSettings(engine, S.default_voice(engine), style or "", 10))
    view.pop(rate_sl)
    return view


def change_music(name, music):
    """User picked another track: its intro may differ, so start from 0 again."""
    return _music_view(name, music, 0)


def move_start(name, music, start):
    """Only move the playhead + caption; reloading the file would restart the player."""
    path = _music_path(music)
    if path is None or not path.exists():
        return {music_audio: gr.skip(), wave_md: gr.skip()}
    total = W.duration(path)
    start = max(0.0, min(float(start or 0), total))
    clip = H.clip_length(name) if name else P.DEFAULT_DURATION
    return {music_audio: gr.Audio(playback_position=start), wave_md: W.caption(start, clip, total)}


def load_project(name):
    if not name:
        return {editor: "", prompt_again: ""}
    data = H.read_storyboard(name)
    s = S.read_settings(data or {})
    music_choices = [RANDOM_MUSIC, *S.list_music()]
    music = s.music if s.music in music_choices else RANDOM_MUSIC
    return {
        editor: H.storyboard_text(name),
        save_msg: "" if data else "ยังไม่มี storyboard — วาง JSON จาก Claude ในช่องนี้แล้วกด **บันทึก**",
        prompt_again: H.prompt_for(name),
        **_voice_view(S.read_voice(data or {})),
        music_dd: gr.Dropdown(choices=music_choices, value=music),
        **_music_view(name, music, s.start_sec),
        volume_sl: s.volume, duck_sl: min(max(s.duck_ratio, DUCK_MIN), DUCK_MAX), speed_sl: s.footage_speed,
        version_in: "",
        status: progress_bar(0, "พร้อม"), log_box: "",
        **_outputs_for(name),
    }


def save_editor(name, text):
    if not name:
        return {save_msg: "❌ เลือก project ก่อน"}
    res = H.check_and_save(name, text or "")
    out = {save_msg: res.report + (f"\n\n**Copy ไปให้ Claude แก้:**\n```\n{res.fix_prompt}```" if res.fix_prompt else "")}
    if res.ok:
        out[editor] = H.storyboard_text(name)
    return out


def check_storyboard(name, text):
    if not name:
        return {save_msg: "❌ เลือก project ก่อน"}
    res = H.check_and_save(name, text or "")
    if not res.ok:
        return {save_msg: res.report + f"\n\n**Copy ไปให้ Claude แก้:**\n```\n{res.fix_prompt}```"}
    return {save_msg: res.report + f"\n\n```\n{res.plan}\n```", editor: H.storyboard_text(name)}


def _settings(music, start, vol, duck, speed):
    return S.RenderSettings(None if music in (None, RANDOM_MUSIC) else music,
                            float(start or 0), float(vol), float(duck), float(speed))


def _prepare(name, text, settings, voice=None):
    """Save pending editor edits + GUI settings. Returns (storyboard_text, error)."""
    if (text or "").strip() != H.storyboard_text(name).strip():
        res = H.check_and_save(name, text or "")
        if not res.ok:
            return None, res.report
    sb_text = H.save_settings(name, settings)
    return (H.save_voice(name, voice) if voice else sb_text), None


def run_job(mode, name, text, music, start, vol, duck, speed, version,
            engine=None, voice_id=None, style="", rate=10):
    if not name:
        yield {status: progress_bar(0, "เลือก project ก่อน", "error")}
        return
    try:
        video_name = P.video_filename(version or "") if mode == "render" else None
        vs = S.VoiceSettings(engine, voice_id or S.default_voice(engine), (style or "").strip(),
                             int(rate)) if engine else None
        sb_text, err = _prepare(name, text, _settings(music, start, vol, duck, speed), vs)
    except (ValueError, FileNotFoundError) as e:
        sb_text, err = None, str(e)
    if err:
        yield {status: progress_bar(0, "storyboard ไม่ผ่าน — แก้ในแท็บ Storyboard", "error"), warnings_md: err}
        return
    try:
        proc = JOBS.start(name, RU.build_command(name, mode, video_name))
    except RU.JobRunning:
        yield {status: progress_bar(0, f"'{name}' กำลังทำงานอยู่ — รอให้เสร็จหรือกดยกเลิก", "error")}
        return

    frac, label, lines, last = 0.0, "เริ่มต้น…", [], 0.0
    yield {editor: sb_text, status: progress_bar(frac, label), log_box: ""}
    for line in RU.stream_lines(proc):
        ev = RU.parse_line(line)
        if ev:
            frac = ev.fraction
            label = f"{ev.stage}/{ev.stages} {ev.label}" + (f" ({ev.done}/{ev.total})" if ev.total else "")
        else:
            lines.append(line.rstrip())
        if time.monotonic() - last >= UI_REFRESH_SEC:
            last = time.monotonic()
            yield {status: progress_bar(frac, label), log_box: "\n".join(lines[-LOG_LINES:])}
    JOBS.finish(name)

    code = proc.returncode
    if code == 0:
        final = progress_bar(1.0, "เสร็จแล้ว", "ok")
    elif code < 0:
        final = progress_bar(frac, "ยกเลิกแล้ว", "error")
    else:
        final = progress_bar(frac, f"ล้มเหลว (exit {code}) — ดู log", "error")
    done = {status: final, log_box: "\n".join(lines[-LOG_LINES:]), **_outputs_for(name)}
    if code == 0:
        done[left_tabs] = gr.Tabs(selected="output")
    yield done


def _job_handler(mode):
    def handler(*args):
        yield from run_job(mode, *args)
    return handler


def cancel_job(name):
    # on success the running job's own final update shows "ยกเลิกแล้ว"; writing here would race it
    if name and JOBS.cancel(name):
        return gr.skip()
    return progress_bar(0, "ไม่มีงานที่กำลังทำ", "error")


def pick_video(name, filename):
    return str(H.project_dir(name) / filename) if name and filename else None


def select_cut(infos, evt: gr.SelectData):
    cut = infos[evt.index]
    link = f" · [เปิดใน Pexels]({cut.url})" if cut.url else ""
    return {selected_state: cut, cut_md: f"**{cut.label}** · #{cut.video_id} · `{cut.query}`{link}"}


def reroll(name, cut):
    if not name or cut is None:
        return {cut_md: "❌ เลือกคัตในแกลเลอรีก่อน"}
    return {editor: H.reroll_cut(name, cut),
            cut_md: f"🎲 {cut.label}: จะไม่ใช้คลิป #{cut.video_id} อีก — กด **Render** เพื่อได้คลิปใหม่"}


# ───────────────────────── layout ─────────────────────────
with gr.Blocks(title="Auto Shorts") as demo:
    wiz_state = gr.State("")
    cuts_state = gr.State([])
    selected_state = gr.State(None)

    gr.Markdown("# Auto Shorts\nstoryboard → เสียงพากย์ → ฟุตเทจ → คลิป Shorts", elem_classes="as-title")
    with gr.Tabs(selected="project") as tabs:
        with gr.Tab("สร้างใหม่", id="new"):
            with gr.Walkthrough(selected=1) as wizard:
                with gr.Step("1 · ข้อมูลคลิป", id=1):
                    name_in = gr.Textbox(label="ชื่อ project", placeholder="เช่น cat_box (a–z, 0–9, - และ _)")
                    topic_in = gr.Textbox(label="เนื้อหา / หัวข้อ", lines=3,
                                          placeholder="เช่น ทำไมแมวถึงชอบนั่งในกล่อง")
                    with gr.Row():
                        tone_in = gr.Textbox(label="โทน", placeholder="เช่น ตลก / อบอุ่น / ลึกลับ", scale=3)
                        duration_in = gr.Slider(15, 90, value=P.DEFAULT_DURATION, step=5,
                                                label="ความยาวเป้าหมาย (วินาที)", scale=2)
                    step1_msg = gr.Markdown()
                    next1 = gr.Button("สร้าง prompt →", variant="primary")
                with gr.Step("2 · Copy prompt", id=2):
                    gr.Markdown("กดปุ่ม copy มุมขวาบนของกล่อง แล้ววางในแชต Claude")
                    prompt_box = gr.Textbox(label="Prompt สำหรับ Claude", lines=20, max_lines=30,
                                            buttons=["copy"], interactive=False)
                    with gr.Row():
                        back2 = gr.Button("← แก้ข้อมูล")
                        next2 = gr.Button("ได้ JSON แล้ว →", variant="primary")
                with gr.Step("3 · วาง storyboard", id=3):
                    paste_in = gr.Textbox(label="วางคำตอบจาก Claude (ทั้งข้อความก็ได้ ระบบดึง JSON ให้)",
                                          lines=20, max_lines=40)
                    with gr.Row():
                        back3 = gr.Button("← กลับไปดู prompt")
                        check_btn = gr.Button("ตรวจและบันทึก", variant="primary")
                    step3_msg = gr.Markdown()
                    fix_box = gr.Textbox(label="ไม่ผ่าน — copy ข้อความนี้ไปให้ Claude แก้", lines=8,
                                         buttons=["copy"], interactive=False, visible=False)

        with gr.Tab("Project", id="project"):
            with gr.Row():
                project_dd = gr.Dropdown(choices=P.list_projects(), label="Project", scale=4)
                refresh_btn = gr.Button("↻ รีเฟรชรายชื่อ", scale=1)
            with gr.Row(equal_height=False):
                with gr.Column(scale=3):
                    with gr.Tabs(selected="storyboard") as left_tabs:
                        with gr.Tab("Storyboard", id="storyboard"):
                            editor = gr.Code(language="json", show_label=False, lines=26, max_lines=40)
                            with gr.Row():
                                save_btn = gr.Button("บันทึก storyboard")
                                check_sb_btn = gr.Button("ตรวจ Storyboard")
                            save_msg = gr.Markdown()
                        with gr.Tab("Output", id="output"):
                            with gr.Row(equal_height=False):
                                with gr.Column(scale=3):
                                    with gr.Row(equal_height=True):
                                        voice = gr.Audio(label="เสียงพากย์ (TTS)", interactive=False, scale=4)
                                        tts_btn = gr.Button("TTS only", scale=1, min_width=80)
                                    with gr.Row(equal_height=True):
                                        version_in = gr.Textbox(label="ชื่อไฟล์ (ว่าง = final.mp4)",
                                                                placeholder="เช่น v2", scale=2, min_width=120)
                                        render_btn = gr.Button("Render", variant="primary", scale=1, min_width=80)
                                        cancel_btn = gr.Button("ยกเลิก", variant="stop", scale=1, min_width=80)
                                    status = gr.HTML(progress_bar(0, "พร้อม"))
                                    warnings_md = gr.Markdown()
                                    log_box = gr.Textbox(label="Log", lines=10, max_lines=10, autoscroll=True,
                                                         interactive=False)
                                with gr.Column(scale=2):
                                    video_dd = gr.Dropdown(label="วิดีโอ", choices=[])
                                    with gr.Group(elem_classes="as-preview"):
                                        video = gr.Video(label="Preview", interactive=False, height=520)
                                        overlay_view = gr.HTML("", container=False, padding=False,
                                                               elem_classes="as-overlay-slot")
                                    with gr.Row(equal_height=True):
                                        overlay_dd = gr.Dropdown(label="Overlay (overlays/)", scale=3,
                                                                 choices=O.list_overlays(),
                                                                 value=next(iter(O.list_overlays()), None))
                                        overlay_tg = gr.Checkbox(label="แสดง overlay", value=False, scale=1,
                                                                 min_width=100)
                with gr.Column(scale=2):
                    with gr.Tabs():
                        with gr.Tab("Configuration"):
                            with gr.Group():
                                with gr.Row(equal_height=True):
                                    engine_dd = gr.Dropdown(S.ENGINES, value="edge-tts", label="เสียงพากย์ (engine)",
                                                            scale=1, min_width=120)
                                    voice_dd = gr.Dropdown(S.EDGE_VOICES, label="เสียง", scale=2, min_width=160)
                                style_tb = gr.Textbox(label="สไตล์การพูด (Gemini)", lines=2, visible=False,
                                                      placeholder="เช่น ผู้บรรยายคลิปสั้นไวรัล พูดเร็ว น้ำเสียงมั่นใจ")
                                rate_sl = gr.Slider(-20, 80, step=5, value=10, label="ความเร็วเสียงพากย์ (%)")
                            music_dd = gr.Dropdown(label="เพลง (music/)", choices=[RANDOM_MUSIC])
                            music_audio = gr.Audio(label="ฟังเพลง", interactive=False,
                                                   waveform_options=gr.WaveformOptions(
                                                       waveform_color=WAVE_USED,
                                                       waveform_progress_color=WAVE_SKIPPED))
                            start_sl = gr.Slider(0, 1, step=0.5, value=0, label="เริ่มเพลงที่วินาที")
                            wave_md = gr.Markdown()
                            volume_sl = gr.Slider(0, 1, step=0.05, label="BGM volume")
                            duck_sl = gr.Slider(DUCK_MIN, DUCK_MAX, step=0.05,
                                                label="Duck ratio (ต่ำ = เพลงดังใต้เสียงพูด)")
                            speed_sl = gr.Slider(0.25, 4, step=0.25, label="Footage speed")
                        with gr.Tab("คัต"):
                            cut_gallery = gr.Gallery(columns=3, height="auto", object_fit="cover",
                                                     allow_preview=False, show_label=False)
                            cut_md = gr.Markdown(CUT_HINT)
                            reroll_btn = gr.Button("🎲 สุ่มคลิปใหม่")
            with gr.Accordion("Prompt ของ project นี้", open=False):
                prompt_again = gr.Textbox(show_label=False, lines=10, buttons=["copy"], interactive=False)

    # wizard
    next1.click(wizard_step1, [name_in, topic_in, tone_in, duration_in, wiz_state],
                [step1_msg, prompt_box, wizard, wiz_state])
    back2.click(lambda: gr.Walkthrough(selected=1), outputs=wizard)
    next2.click(lambda: gr.Walkthrough(selected=3), outputs=wizard)
    back3.click(lambda: gr.Walkthrough(selected=2), outputs=wizard)
    check_btn.click(wizard_step3, [wiz_state, paste_in],
                    [step3_msg, fix_box, name_in, topic_in, tone_in, paste_in, prompt_box, step1_msg,
                     wizard, wiz_state, tabs, project_dd])

    # project
    settings_in = [music_dd, start_sl, volume_sl, duck_sl, speed_sl]
    music_out = [music_audio, start_sl, wave_md]
    result_out = [voice, video_dd, video, warnings_md, cut_gallery, cuts_state, selected_state, cut_md]
    voice_out = [engine_dd, voice_dd, style_tb, rate_sl]
    project_out = [editor, save_msg, prompt_again, *voice_out, music_dd, *music_out, volume_sl, duck_sl, speed_sl,
                   version_in, status, log_box, *result_out]
    project_dd.change(load_project, project_dd, project_out)
    demo.load(load_project, project_dd, project_out)
    refresh_btn.click(lambda n: gr.Dropdown(choices=P.list_projects(), value=n), project_dd, project_dd)
    save_btn.click(save_editor, [project_dd, editor], [save_msg, editor])
    check_sb_btn.click(check_storyboard, [project_dd, editor], [save_msg, editor])
    music_dd.input(change_music, [project_dd, music_dd], music_out)   # user pick only, not programmatic
    start_sl.change(move_start, [project_dd, music_dd, start_sl], [music_audio, wave_md])
    video_dd.change(pick_video, [project_dd, video_dd], video)
    engine_dd.input(change_engine, [engine_dd, style_tb], [engine_dd, voice_dd, style_tb])
    run_in = [project_dd, editor, *settings_in, version_in, *voice_out]
    run_out = [editor, status, log_box, warnings_md, left_tabs, *result_out[:3], *result_out[4:]]
    for btn, mode in ((tts_btn, "tts"), (render_btn, "render")):
        btn.click(_job_handler(mode), run_in, run_out)
    cancel_btn.click(cancel_job, project_dd, status)
    cut_gallery.select(select_cut, cuts_state, [selected_state, cut_md])
    overlay_in = [overlay_dd, overlay_tg]
    overlay_dd.change(O.overlay_html, overlay_in, overlay_view)
    overlay_tg.change(O.overlay_html, overlay_in, overlay_view)
    overlay_dd.focus(lambda n: gr.Dropdown(choices=O.list_overlays(), value=n), overlay_dd, overlay_dd)
    reroll_btn.click(reroll, [project_dd, selected_state], [editor, cut_md])

def main() -> None:
    PROJECTS_DIR.mkdir(exist_ok=True)
    O.OVERLAY_DIR.mkdir(exist_ok=True)
    demo.queue().launch(server_name="127.0.0.1", inbrowser=True, theme=THEME, css=CSS, head=HEAD + O.SYNC_JS,
                        allowed_paths=[str(PROJECTS_DIR), str(S.MUSIC_DIR), str(O.OVERLAY_DIR)])
