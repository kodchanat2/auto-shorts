# YouTube Shorts Automation Engine

`storyboard.json` → Thai voiceover (edge-tts) → Pexels real footage → FFmpeg → `output/final_shorts.mp4`

Claude คือ Story Director ส่วน Python เป็น worker แบบ deterministic ที่ไม่มีการเรียก LLM เลย ถ้าใช้ storyboard, seed และ cache ชุดเดิม ผลลัพธ์จะออกมาเหมือนเดิมทุกครั้ง

## โครงสร้างโปรเจกต์

```
shorts-engine/
├── render_shorts.py          # worker engine
├── storyboard.schema.json    # data contract (validate อัตโนมัติ)
├── storyboard.json           # ตัวอย่าง 5 scenes (H-C-B-R)
├── requirements.txt
├── .env.example              # → คัดลอกเป็น .env แล้วใส่ PEXELS_API_KEY
├── fonts/Kanit-Bold.ttf      # ฟอนต์ไทยสำหรับซับ (OFL, ใช้เชิงพาณิชย์ได้)
├── music/                    # วาง BGM ของคุณที่นี่
├── cache/                    # (auto) TTS + Pexels cache เพื่อรันซ้ำได้เร็วและได้ผลเดิม
└── output/                   # final_shorts.mp4, timeline.json, credits.txt
```

## ติดตั้ง (macOS)

```bash
brew install ffmpeg python@3.12
cd shorts-engine
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # แล้วใส่ key จาก https://www.pexels.com/api/ (ฟรี)
```

จากนั้นวางไฟล์เพลงที่ไม่ติดลิขสิทธิ์ไว้ใน `music/` (แนะนำ YouTube Studio Audio Library) ถ้าไม่มีเพลง ระบบจะเตือนแล้วเรนเดอร์ต่อโดยไม่มี BGM

## Workflow ต่อคลิป

```bash
# 1) ให้ Claude สร้าง storyboard (ใช้ prompt ด้านล่าง) แล้วบันทึกเป็น my_clip.json

# 2) ตรวจโครงสร้างและดูแผนโดยประมาณ (ไม่ใช้เน็ต)
python render_shorts.py my_clip.json --dry-run

# 3) เจนเฉพาะเสียงเพื่อฟังก่อน → output/voice_preview.wav + timeline.json
python render_shorts.py my_clip.json --tts-only

# 4) เรนเดอร์จริง
python render_shorts.py my_clip.json -o output/my_clip.mp4
```

Flags อื่นๆ ได้แก่ `--no-subs`, `--no-bgm`, `--seed 7` (เปลี่ยนจุดเริ่มคลิปและเพลง), `--refresh-footage` (ค้น Pexels ใหม่ ไม่ใช้ cache) และ `--keep-temp` (เก็บไฟล์ใน `build/` ไว้ debug)

**การตรวจแบบ Human-in-the-loop:** หลังเรนเดอร์ ให้เปิด `output/timeline.json` เพื่อดูว่าแต่ละคัตใช้ Pexels video id อะไร ถ้าคัตไหนไม่ถูกใจ ให้ทำอย่างใดอย่างหนึ่ง คือแก้ `pexels_query` หรือใส่ `"pexels_video_id": 1234567` เพื่อปักคลิปที่ต้องการ แล้วรันใหม่ คัตอื่นที่มาจาก cache จะได้ผลเดิม

## ระบบทำงานอย่างไร

1. **เสียงพากย์:** แต่ละบรรทัดใน `narration_lines` จะเป็น 1 utterance ของ edge-tts ระบบเก็บ word-boundary timing มาด้วย แล้วนำมาต่อเป็น scene พร้อมเว้นช่วงเงียบ จากนั้นปัดความยาว scene ให้ลงตัวกับจำนวนเฟรมพอดี ภาพกับเสียงจึงไม่ drift
2. **Sub-cuts:** `duration_hint_sec` เป็นแค่ "น้ำหนัก" ระบบจะสเกลให้ผลรวมเท่ากับเสียงจริงของ scene และบังคับให้แต่ละคัตอยู่ในช่วง 1.5–3.0 วินาที ถ้าเสียงยาวเกินกว่าจำนวนคัตจะรองรับ ระบบจะแตกคัตที่หนักที่สุดเป็น 2 คัต (คีย์เวิร์ดเดิมแต่คนละคลิป) ถ้าสั้นเกินจะรวมคัตที่เบาที่สุดเข้ากับคัตข้างเคียง
3. **Footage:** ระบบค้นหาตามลำดับนี้ คือ portrait ที่ไม่ต้องขยายภาพก่อน รองลงมาคือ portrait ที่ขยายไม่เกิน 1.5× และสุดท้ายคือ landscape 4K ที่ crop กลางได้ โดยไล่จาก `pexels_query` ไปจนถึง `fallback_queries` คลิปจะไม่ซ้ำกันในวิดีโอเดียว ถ้าคลิปสั้นกว่าคัตจะ loop ให้
4. **ภาพ:** ทุกคัตผ่าน `scale → center-crop 1080x1920 → fps 30` และตัดด้วยจำนวนเฟรมที่แม่นยำ
5. **ซับไทย:** pythainlp ตัดคำ แล้วจัดกลุ่มเป็นวลีสั้นๆ ขนาดใกล้เคียงกัน (≤14 ตัวอักษรที่มองเห็น) ใช้ช่องว่างในบทเป็นจุดตัดหลัก จังหวะมาจาก word-boundary ของ TTS และถ้าจับคู่ไม่ได้จะเฉลี่ยตามความยาวข้อความ คำใน `emphasis_words` จะเป็นสีเหลือง และมี pop animation สั้นๆ
6. **เสียง:** เสียงพากย์ผ่าน loudnorm ที่ −15 LUFS ส่วน BGM ถูก sidechain-duck อัตโนมัติขณะมีเสียงพูด พร้อม fade in/out

## ตั้งค่าเสียงพากย์ (`voice` ใน storyboard)

| ค่า | แนะนำ | หมายเหตุ |
|---|---|---|
| `voice_id` | `th-TH-PremwadeeNeural` (หญิง), `th-TH-NiwatNeural` (ชาย) | ดูรายชื่อทั้งหมดด้วย `edge-tts --list-voices \| grep th-TH` |
| `rate` | `+8%` ถึง `+15%` | Shorts ควรเร็วกว่าปกติเล็กน้อย ถ้าเกิน +20% จะเริ่มฟังไม่เป็นธรรมชาติ |
| `pitch` | `+0Hz` ถึง `+5Hz` | เสียงผู้หญิงที่ `+3Hz` จะสดใสขึ้น |
| `line_gap_sec` | `0.08`–`0.15` | เว้นช่วงระหว่างประโยค ยิ่งน้อยยิ่งกระชับ |
| `scene_gap_sec` | `0.2`–`0.3` | ช่วงหายใจระหว่าง scene |
| `pronunciations` | `{"AI": "เอไอ", "80%": "แปดสิบเปอร์เซ็นต์"}` | แก้เฉพาะเสียงที่อ่าน ส่วนซับยังแสดงข้อความเดิม |

ทดลองฟังเสียงเร็วๆ ได้ด้วยคำสั่ง `edge-tts --voice th-TH-NiwatNeural --rate=+10% --text "ทดสอบเสียง" --write-media test.mp3`

เคล็ดลับการเขียนบท: ให้แต่ละบรรทัดเป็น 1 ประโยคสั้น และเว้นวรรคตรงจุดที่อยากให้ซับขึ้นบรรทัดใหม่ ควรเขียนตัวเลขและคำภาษาอังกฤษให้ TTS อ่านถูก หรือใส่ไว้ใน `pronunciations`

## Prompt สำหรับให้ Claude สร้าง Storyboard

แนบไฟล์ `storyboard.schema.json` แล้วใช้ prompt นี้:

```
คุณคือ Story Director ของช่อง YouTube Shorts ภาษาไทย
หัวข้อ: <หัวข้อ>   ความยาวเป้าหมาย: 40–50 วินาที   โทน: <เช่น ตื่นเต้น/อบอุ่น>

สร้าง storyboard.json ตาม schema ที่แนบ (schema_version "1.0") โดย:
- โครงสร้าง H-C-B-R: HOOK (≤4 วิ, ประโยคแรกต้องหยุดนิ้ว) → CONFLICT → BODY 1–2 scene → RESOLUTION + CTA
- narration_lines: ภาษาไทยพูดธรรมชาติ บรรทัดละ 1 ประโยค เว้นวรรคตรงจุดหายใจ
  รวมทั้งคลิปประมาณ 13 ตัวอักษร/วินาที (≈ 550–650 ตัวอักษรสำหรับ 45 วิ)
- cuts: 1 คัตต่อเสียงพูดประมาณ 2–2.5 วินาที, duration_hint_sec 1.5–3.0
- pexels_query: ภาษาอังกฤษ รูปธรรม "subject + action/object (+ setting)" 3–7 คำ
  ห้ามคำนามธรรม (success, motivation, idea) ห้าม AI/cartoon/3D/illustration
  ใส่ fallback_queries 1–2 อันที่กว้างขึ้น
- สลับ shot_type ระหว่างคัตติดกัน (close_up ↔ wide ↔ overhead ...) เพื่อ visual rhythm
- ใส่ emphasis_words 3–5 คำสำคัญ
ส่งเฉพาะ JSON ที่ valid เท่านั้น
```

## Troubleshooting

- **`edge-tts failed` / 403:** ให้รัน `pip install -U edge-tts` ก่อน เพราะ Microsoft เปลี่ยน endpoint เป็นระยะ และตัวนี้ไม่ใช่ API ทางการ ถ้าใช้ไม่ได้ในอนาคต ให้แทนที่ฟังก์ชัน `_tts_one` ด้วย engine อื่นที่ส่งไฟล์ mp3 ออกมาเหมือนกัน
- **สระหรือวรรณยุกต์ในซับซ้อนทับกัน:** Pillow ไม่มี RAQM ให้รัน `brew install libraqm` แล้วติดตั้ง Pillow ใหม่
- **`Pexels rate limit`:** โควตาฟรีคือ 200 requests/ชม. ระบบรอให้เองอัตโนมัติ และ cache ช่วยลดการเรียกซ้ำได้มาก
- **คลิปดูแตก (upscaled warning):** ให้ปักคลิปใหม่ด้วย `pexels_video_id` หรือเปลี่ยนคีย์เวิร์ด
- **ความยาวเกิน 60 วิ:** ตัดบรรทัดออก หรือเพิ่ม `rate`

## ลิขสิทธิ์

ฟุตเทจจาก Pexels ใช้ได้ฟรีรวมถึงเชิงพาณิชย์ และระบบสร้าง `credits.txt` ไว้ให้ copy ไปใส่คำอธิบายคลิป ส่วน BGM ต้องใช้เพลงที่คุณมีสิทธิ์ใช้เท่านั้น ฟอนต์ Kanit อยู่ภายใต้ SIL OFL 1.1
