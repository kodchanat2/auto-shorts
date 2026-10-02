# YouTube Shorts Automation Engine

`projects/<ชื่อ>/storyboard.json` → Thai voiceover (edge-tts หรือ Gemini Live) → Pexels real footage → FFmpeg → `projects/<ชื่อ>/final.mp4`

Claude คือ Story Director ส่วน Python เป็น worker ที่ไม่ได้ใช้ LLM ตัดสินใจอะไรเอง (ถ้าเลือกเสียง Gemini จะเรียก Gemini แค่เพื่อพากย์เสียงตามบท) ถ้าใช้ storyboard, seed และ cache ชุดเดิม ผลลัพธ์จะออกมาเหมือนเดิมทุกครั้ง

## โครงสร้างโปรเจกต์

```
auto-shorts/
├── render_shorts.py          # worker engine
├── tts_gemini.py             # engine เสียง Gemini Live (ใช้เมื่อ voice.engine = "gemini")
├── app.py + gui/             # GUI (Gradio) — python app.py
├── tests/                    # pytest
├── storyboard.schema.json    # data contract (validate อัตโนมัติ)
├── examples/storyboard.json  # ตัวอย่าง 5 scenes (H-C-B-R) ใช้เป็นแม่แบบ
├── requirements.txt          # + requirements-dev.txt สำหรับ pytest
├── .env.example              # → คัดลอกเป็น .env แล้วใส่ PEXELS_API_KEY (และ GEMINI_API_KEY ถ้าใช้เสียง Gemini)
├── fonts/Kanit-Bold.ttf      # ฟอนต์ไทยสำหรับซับ (OFL, ใช้เชิงพาณิชย์ได้) — ใช้ร่วมทุก project
├── music/                    # วาง BGM ของคุณที่นี่ — ใช้ร่วมทุก project
├── overlays/                 # รูป UI ของแอปโซเชียล (PNG 9:16) ไว้วางทับ Preview ใน GUI
├── docs/pipeline.md          # แผนภาพ pipeline + คู่มือสร้างคลิปใหม่
├── docs/storyboard-prompt.md # prompt ให้ Claude เขียน storyboard
└── projects/<ชื่อ>/           # 1 คลิป = 1 โฟลเดอร์ (ไม่อยู่ใน git)
    ├── storyboard.json
    ├── final.mp4, timeline.json, credits.txt, voice_preview.wav
    ├── cache/                # (auto) TTS + Pexels cache ของ project นี้ รันซ้ำได้เร็วและได้ผลเดิม
    └── build/                # (auto) ไฟล์ชั่วคราว ถูกลบเมื่อเรนเดอร์สำเร็จ
```

ทุกอย่างของคลิปหนึ่งอยู่ใน `projects/<ชื่อ>/` เสร็จงานแล้วลบโฟลเดอร์นั้นทิ้งได้เลย (ข้อแลก: cache ไม่แชร์ข้าม project คลิป Pexels ที่ซ้ำกันจะถูกโหลดใหม่)

## ติดตั้ง (macOS)

```bash
brew install ffmpeg python@3.12 libraqm   # libraqm: ให้สระ/วรรณยุกต์ในซับวางถูกที่
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ใส่ key จาก https://www.pexels.com/api/ (ฟรี) และ GEMINI_API_KEY ถ้าจะใช้เสียง Gemini
```

จากนั้นวางไฟล์เพลงที่ไม่ติดลิขสิทธิ์ไว้ใน `music/` (แนะนำ YouTube Studio Audio Library) ถ้าไม่มีเพลง ระบบจะเตือนแล้วเรนเดอร์ต่อโดยไม่มี BGM

> **ทุกครั้งที่เปิด terminal ใหม่** ให้ `cd` เข้าโฟลเดอร์โปรเจกต์แล้วรัน `source .venv/bin/activate` ก่อน คำสั่ง `python` ในเอกสารนี้หมายถึง Python ใน `.venv` — macOS ไม่มีคำสั่ง `python` ให้ใช้ตรงๆ (ถ้าเจอ `command not found: python` แปลว่ายังไม่ได้ activate) หรือจะเรียก `.venv/bin/python` แทน `python` เลยก็ได้โดยไม่ต้อง activate

## ใช้ผ่าน GUI (แนะนำ)

```bash
source .venv/bin/activate     # ถ้ายังไม่ได้ activate ใน terminal นี้
python app.py                 # เปิด http://127.0.0.1:7860 ในเบราว์เซอร์ให้อัตโนมัติ
```

- **แท็บ "สร้างใหม่"** มี 3 ขั้น: (1) ใส่ชื่อ project เนื้อหา โทน และความยาว → (2) copy prompt ไปวางในแชต Claude → (3) วางคำตอบของ Claude (ทั้งข้อความก็ได้ ระบบดึง JSON ให้) ระบบตรวจด้วย `--dry-run` ถ้าไม่ผ่านจะสร้างข้อความแจ้งแก้ให้ copy กลับไปให้ Claude
- **แท็บ "Project"** แบ่งเป็น 2 ฝั่ง
  - ซ้าย **Storyboard**: แก้ JSON, ปุ่ม **บันทึก** และ **ตรวจ Storyboard** (ตรวจ schema + ประมาณความยาว + แผนคัต ไม่ใช้เน็ต)
  - ซ้าย **Output**: ชื่อไฟล์ (ว่าง = `final.mp4`, พิมพ์ `v2` ได้ `v2.mp4`), ปุ่ม TTS only / Render / ยกเลิก, progress bar, วิดีโอ, เสียงพากย์, warnings และ log — TTS/Render เสร็จแล้วจะเปิดแท็บนี้ให้เอง
  - ขวา **Configuration**: เสียงพากย์ (engine edge-tts / gemini, เลือกเสียง, สไตล์การพูดสำหรับ Gemini, ความเร็ว %), เลือกเพลง, slider วินาทีเริ่มเพลง (หัวเล่นของ player ย้ายไปที่จุดเริ่ม ช่วงก่อนหน้าเป็นสีเทา, สูงสุด = ความยาวเพลง, เปลี่ยนเพลงแล้วรีเซ็ตเป็น 0), BGM volume, duck ratio (1–2), footage speed — ค่าเหล่านี้บันทึกลง storyboard ตอนกด TTS/Render
  - ขวา **คัต**: แกลเลอรีคลิปของ render ล่าสุด
- **แกลเลอรีคัต** กดที่รูปแล้วกด 🎲 สุ่มคลิปใหม่ (ใส่ id ปัจจุบันลง `exclude_video_ids` ของคัตนั้น) แล้วกด Render อีกครั้ง คัตอื่นได้คลิปเดิมจาก cache ถ้าอยากใช้คลิปเจาะจงให้ใส่ `pexels_video_id` ในแท็บ Storyboard
- **Overlay บน Preview**: วางรูป PNG/WebP พื้นโปร่งใส 9:16 (เช่นเทมเพลต UI ของ Shorts/TikTok/Reels) ใน `overlays/` แล้วเลือกใต้ Preview และติ๊ก "แสดง overlay" เพื่อเช็กว่าซับหรือภาพสำคัญโดน UI ของแอปบังไหม — มีผลแค่ในหน้าจอ ไม่ถูกใส่ลงวิดีโอ
- เปิดให้เข้าได้เฉพาะเครื่องตัวเอง (`127.0.0.1`) และ render ซ้อนกันใน project เดียวกันไม่ได้

## Workflow ต่อคลิป (command line)

```bash
# 1) ให้ Claude สร้าง storyboard (ใช้ prompt ด้านล่าง) แล้วบันทึกเป็น projects/my_clip/storyboard.json
mkdir -p projects/my_clip        # วาง JSON ลงไฟล์ projects/my_clip/storyboard.json

# 2) ตรวจโครงสร้างและดูแผนโดยประมาณ (ไม่ใช้เน็ต)
python render_shorts.py my_clip --dry-run

# 3) เจนเฉพาะเสียงเพื่อฟังก่อน → projects/my_clip/voice_preview.wav + timeline.json
python render_shorts.py my_clip --tts-only

# 4) เรนเดอร์จริง → projects/my_clip/final.mp4
python render_shorts.py my_clip
```

Flags อื่นๆ ได้แก่ `--no-subs`, `--no-bgm`, `--seed 7` (เปลี่ยนจุดเริ่มคลิปและเพลง), `--refresh-footage` (ค้น Pexels ใหม่ ไม่ใช้ cache) `--keep-temp` (เก็บ `projects/<ชื่อ>/build/` ไว้ debug) และ `-o` (ตั้งชื่อไฟล์วิดีโอเอง เช่น `-o v2.mp4` จะได้ `projects/<ชื่อ>/v2.mp4`)

นอกจากชื่อ project แล้ว ยังชี้เป็น path ของโฟลเดอร์หรือไฟล์ `.json` ได้ด้วย โฟลเดอร์ที่ไฟล์อยู่จะถือเป็นโฟลเดอร์ project

**การตรวจแบบ Human-in-the-loop:** หลังเรนเดอร์ ให้เปิด `projects/<ชื่อ>/timeline.json` เพื่อดูว่าแต่ละคัตใช้ Pexels video id อะไร ถ้าคัตไหนไม่ถูกใจ ให้แก้ `pexels_query`, ใส่ `"pexels_video_id": 1234567` เพื่อปักคลิปที่ต้องการ หรือใส่ `"exclude_video_ids": [1234567]` เพื่อห้ามใช้คลิปนั้นแล้วให้ระบบเลือกคลิปถัดไป แล้วรันใหม่ คัตอื่นที่มาจาก cache จะได้ผลเดิม

## ทดสอบ

```bash
pip install -r requirements-dev.txt
pytest --cov=gui --cov=tts_gemini --cov-report=term-missing
```

## ระบบทำงานอย่างไร

1. **เสียงพากย์:** แต่ละบรรทัดใน `narration_lines` จะเป็น 1 ไฟล์เสียง (edge-tts ได้ word-boundary timing มาด้วย ส่วน Gemini Live ไม่มี) ระบบตัดช่วงเงียบหัว/ท้ายของทุกไฟล์ (edge-tts ใส่มา ≈0.17s + 0.8s, ปิดได้ด้วย `voice.trim_silence: false`) แล้วนำมาต่อเป็น scene พร้อมเว้นช่วงเงียบตาม `line_gap_sec`/`scene_gap_sec` จากนั้นปัดความยาว scene ให้ลงตัวกับจำนวนเฟรมพอดี ภาพกับเสียงจึงไม่ drift
2. **Sub-cuts:** `duration_hint_sec` เป็นแค่ "น้ำหนัก" ระบบจะสเกลให้ผลรวมเท่ากับเสียงจริงของ scene และบังคับให้แต่ละคัตอยู่ในช่วง 1.5–3.0 วินาที ถ้าเสียงยาวเกินกว่าจำนวนคัตจะรองรับ ระบบจะแตกคัตที่หนักที่สุดเป็น 2 คัต (คีย์เวิร์ดเดิมแต่คนละคลิป) ถ้าสั้นเกินจะรวมคัตที่เบาที่สุดเข้ากับคัตข้างเคียง
3. **Footage:** ระบบค้นหาตามลำดับนี้ คือ portrait ที่ไม่ต้องขยายภาพก่อน รองลงมาคือ portrait ที่ขยายไม่เกิน 1.5× และสุดท้ายคือ landscape 4K ที่ crop กลางได้ โดยไล่จาก `pexels_query` ไปจนถึง `fallback_queries` คลิปจะไม่ซ้ำกันในวิดีโอเดียว ถ้าคลิปสั้นกว่าคัตจะ loop ให้
4. **ภาพ:** ทุกคัตผ่าน `speed (render.footage_speed) → scale → center-crop 1080x1920 → fps 30` และตัดด้วยจำนวนเฟรมที่แม่นยำ ถ้าตั้ง `footage_speed: 2.0` แต่ละคัตจะใช้ฟุตเทจยาวเป็น 2 เท่า
5. **ซับไทย:** pythainlp ตัดคำ แล้วจัดกลุ่มเป็นวลีสั้นๆ ขนาดใกล้เคียงกัน (≤14 ตัวอักษรที่มองเห็น) ใช้ช่องว่างในบทเป็นจุดตัดหลัก จังหวะมาจาก word-boundary ของ edge-tts และถ้าจับคู่ไม่ได้ (หรือใช้เสียง Gemini) จะเฉลี่ยตามความยาวข้อความ คำใน `emphasis_words` จะเป็นสีเหลือง และมี pop animation สั้นๆ
6. **เสียง:** เสียงพากย์ผ่าน loudnorm ที่ −15 LUFS ส่วน BGM ถูก sidechain-duck อัตโนมัติขณะมีเสียงพูด พร้อม fade in/out ปรับได้ 3 ค่า: `bgm.volume` (ความดังเพลง, ค่าเริ่มต้น 0.5), `bgm.duck_ratio` (ความแรงของการกดเพลงตอนมีเสียงพูด ค่าต่ำ = เพลงดังใต้เสียงพูดมากขึ้น, ค่าเริ่มต้น 1.2) และ `bgm.start_sec` (วินาทีที่เริ่มเล่นเพลง ใช้ข้ามช่วง intro ที่ไม่เข้ากับเนื้อหา) เสียงผสมเสร็จใน pass แยกก่อนรวมกับภาพ และหลังเรนเดอร์ระบบตรวจว่าเสียงไม่มีช่วงหาย

## ตั้งค่าเสียงพากย์ (`voice` ใน storyboard)

| ค่า | แนะนำ | หมายเหตุ |
|---|---|---|
| `engine` | `edge-tts` (ค่าเริ่มต้น) หรือ `gemini` | ดูหัวข้อ "ใช้เสียง Gemini แทน edge-tts" ด้านล่าง |
| `voice_id` | `th-TH-NiwatNeural` (ชาย), `th-TH-PremwadeeNeural` (หญิง — ณ ก.ย. 2026 ฝั่ง Microsoft ไม่ส่งเสียงกลับ) | ดูรายชื่อทั้งหมดด้วย `edge-tts --list-voices \| grep th-TH` |
| `rate` | edge-tts `+8%` ถึง `+15%`, Gemini ราว `+35%` | edge-tts ถ้าเกิน +20% จะเริ่มฟังไม่เป็นธรรมชาติ ส่วน Gemini พูดช้ากว่าจึงต้องเร่งมากกว่า |
| `style` | เช่น `ผู้บรรยายคลิปสั้นไวรัล พูดเร็ว น้ำเสียงมั่นใจ` | เฉพาะ Gemini — สั่งน้ำเสียงของทั้งคลิป (อารมณ์ราย scene ใช้ `emotion` ของแต่ละ scene) |
| `pitch` | `+0Hz` ถึง `+5Hz` | เสียงผู้หญิงที่ `+3Hz` จะสดใสขึ้น |
| `line_gap_sec` | `0.03`–`0.08` | เว้นช่วงระหว่างประโยค ยิ่งน้อยยิ่งกระชับ |
| `scene_gap_sec` | `0.1`–`0.2` | ช่วงหายใจระหว่าง scene |
| `pronunciations` | `{"AI": "เอไอ", "80%": "แปดสิบเปอร์เซ็นต์"}` | แก้เฉพาะเสียงที่อ่าน ส่วนซับยังแสดงข้อความเดิม |

### ใช้เสียง Gemini แทน edge-tts

```json
"voice": { "engine": "gemini", "voice_id": "Puck", "style": "ผู้บรรยายคลิปสั้นไวรัล พูดเร็ว น้ำเสียงมั่นใจ มีพลัง", "rate": "+35%" }
```

- ต้องใส่ `GEMINI_API_KEY` ใน `.env` (สร้างฟรีที่ https://aistudio.google.com/apikey) 
- `voice_id` คือชื่อเสียงของ Gemini เช่น Puck, Rasalgethi, Kore, Charon ถ้าไม่ใส่หรือใส่ชื่อเสียงของ edge-tts ระบบจะใช้ Puck, `style` คือคำสั่งน้ำเสียง, `rate` ปรับด้วย ffmpeg หลังได้เสียง (pitch/volume ไม่มีผล)
- Gemini ไม่ส่งเวลารายคำกลับมา ซับจะใช้เวลาแบบเฉลี่ยตามความยาวข้อความ (ตรงน้อยกว่า edge-tts)
- ใช้รุ่น **`gemini-3.8-live`** เปิด session ต่อ 1 อารมณ์ (scene ที่ `emotion` เหมือนกันติดกันใช้ session เดียว) แล้วส่งบททีละบรรทัด ระบบสั่งให้อ่านตรงบทและเทียบกับข้อความที่ถอดจากเสียง ถ้าไม่ตรงจะอ่านใหม่ 1 ครั้ง ถ้ายังไม่ตรงจะขึ้น warning
- เพดาน free tier ของรุ่น Live ไม่ได้ประกาศไว้ (ดูได้ใน AI Studio) ถ้าโควตาหมด ระบบจะหยุดพร้อมบอกสาเหตุ บรรทัดที่สร้างแล้วถูก cache ไว้ รันต่อทีหลังได้
- **อารมณ์เสียงพากย์**: ใส่ `emotion` ในแต่ละ scene เช่น `"emotion": "ตึงเครียด กดดัน"` Gemini จะพากย์ด้วยอารมณ์นั้น (ระบบเปิด 1 session ต่ออารมณ์ และส่งอารมณ์เป็นคำสั่ง ไม่ใช่ข้อความที่อ่าน) — เปลี่ยน emotion แล้วเฉพาะบรรทัดของ scene นั้นที่ถูกสร้างใหม่
- Gemini พูดช้ากว่า edge-tts (≈8.6 ตัวอักษร/วินาทีเมื่อสั่ง style ให้พูดเร็ว) ตั้ง `rate` ราว `+35%` จะได้คลิป 45 วิจากบทราว 520 ตัวอักษร — การเปลี่ยน `rate` ไม่เรียก API ใหม่ (cache เก็บเสียงดิบ แล้วเร่งตอนประกอบเสียง)

ทดลองฟังเสียงเร็วๆ ได้ด้วยคำสั่ง `edge-tts --voice th-TH-NiwatNeural --rate=+10% --text "ทดสอบเสียง" --write-media test.mp3`

เคล็ดลับการเขียนบท: ให้แต่ละบรรทัดเป็น 1 ประโยคสั้น และเว้นวรรคตรงจุดที่อยากให้ซับขึ้นบรรทัดใหม่ ควรเขียนตัวเลขและคำภาษาอังกฤษให้ TTS อ่านถูก หรือใส่ไว้ใน `pronunciations`

## Prompt สำหรับให้ Claude สร้าง Storyboard

ใช้ prompt ชุดเดียวใน [`docs/storyboard-prompt.md`](docs/storyboard-prompt.md) คัดลอกไปวางในแชต Claude แล้วแก้หัวข้อ ความยาว และโทน ไม่ต้องแนบไฟล์ schema เพราะกฎทั้งหมดอยู่ในข้อความแล้ว

## Troubleshooting

- **`edge-tts failed` / 403:** ให้รัน `pip install -U edge-tts` ก่อน เพราะ Microsoft เปลี่ยน endpoint เป็นระยะ และตัวนี้ไม่ใช่ API ทางการ ถ้ายังใช้ไม่ได้ เปลี่ยนไปใช้ `"engine": "gemini"` ได้
- **`No audio was received`:** มักเป็นที่ voice นั้นๆ ฝั่ง Microsoft ไม่ใช่โค้ด ทดสอบด้วย `edge-tts --voice <voice_id> --text "ทดสอบ" --write-media test.mp3` ถ้า voice อื่นใช้ได้ให้เปลี่ยน `voice_id` ชั่วคราว (ดู [edge-tts#473](https://github.com/rany2/edge-tts/issues/473))
- **`GEMINI_API_KEY is not set`:** ใส่ key ใน `.env` (สร้างฟรีที่ https://aistudio.google.com/apikey)
- **`Gemini Live quota used up`:** โควตาของ Gemini หมด บรรทัดที่สร้างแล้วถูก cache ไว้ รอโควตารีเซ็ตแล้วรันต่อ เปลี่ยนกลับไปใช้ edge-tts หรือเปิด billing ใน AI Studio
- **`Gemini read a line differently`:** Gemini อ่านไม่ตรงบทแม้อ่านใหม่แล้ว ให้ฟังบรรทัดนั้น ถ้าผิดจริงให้แก้ประโยคให้อ่านง่ายขึ้นหรือปรับ `style` แล้วรันใหม่
- **สระหรือวรรณยุกต์ในซับซ้อนทับกัน:** Pillow ไม่มี RAQM ให้รัน `brew install libraqm` แล้วติดตั้ง Pillow ใหม่
- **`Pexels rate limit`:** โควตาฟรีคือ 200 requests/ชม. ระบบรอให้เองอัตโนมัติ และ cache ช่วยลดการเรียกซ้ำได้มาก
- **คลิปดูแตก (upscaled warning):** ให้ปักคลิปใหม่ด้วย `pexels_video_id` หรือเปลี่ยนคีย์เวิร์ด
- **ความยาวเกิน 60 วิ:** ตัดบรรทัดออก หรือเพิ่ม `rate`

## ลิขสิทธิ์

ฟุตเทจจาก Pexels ใช้ได้ฟรีรวมถึงเชิงพาณิชย์ และระบบสร้าง `credits.txt` ไว้ให้ copy ไปใส่คำอธิบายคลิป ส่วน BGM ต้องใช้เพลงที่คุณมีสิทธิ์ใช้เท่านั้น ฟอนต์ Kanit อยู่ภายใต้ SIL OFL 1.1
