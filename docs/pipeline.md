# Pipeline และคู่มือสร้างวิดีโอใหม่

เอกสารนี้อธิบายว่า `render_shorts.py` เปลี่ยน `storyboard.json` เป็นคลิป Shorts อย่างไร และขั้นตอนทำคลิปใหม่ตั้งแต่ให้ Claude เขียน storyboard จนได้ไฟล์ mp4

## ภาพรวม Pipeline

```mermaid
flowchart TD
    A["Claude (Story Director)<br/>เขียน projects/&lt;ชื่อ&gt;/storyboard.json"] --> B{"validate กับ<br/>storyboard.schema.json"}
    B -- ไม่ผ่าน --> A
    B -- ผ่าน --> DRY["--dry-run<br/>ประมาณความยาว + แผนคัต<br/>(ไม่ใช้เน็ต)"]
    B -- ผ่าน --> TTS

    subgraph S1["1/5 Voiceover"]
        TTS["edge-tts ทีละบรรทัด<br/>mp3 + WordBoundary"] --> TRIM["ตัดช่วงเงียบหัว/ท้าย<br/>+ เลื่อน word timing"]
        TRIM --> JOIN["ต่อเป็น scene<br/>+ line_gap / scene_gap<br/>ปัดให้ลงเฟรมพอดี"]
    end

    subgraph S2["2/5 Caption timing"]
        CAP["pythainlp ตัดคำ<br/>จัดเป็นวลี ≤ max_chars<br/>จับเวลาจาก WordBoundary"]
    end

    subgraph S3["3/5 Cut plan"]
        CUT["สเกล duration_hint_sec<br/>ให้เท่าเสียงจริง<br/>บังคับ 1.5–3.0s ต่อคัต<br/>แตก/รวมคัตอัตโนมัติ"]
    end

    subgraph S4["4/5 Pexels footage"]
        PX["ค้น pexels_query → fallback_queries<br/>ต้องยาว ≥ คัต × footage_speed<br/>ไม่ซ้ำคลิปในวิดีโอเดียว"] --> SEG["FFmpeg ต่อคัต<br/>setpts (speed) → scale → crop<br/>1080x1920 @ 30fps"]
    end

    subgraph S5["5/5 Compose"]
        MUX["overlay ซับ PNG<br/>loudnorm เสียงพากย์ −15 LUFS<br/>BGM + sidechain duck + fade"]
    end

    JOIN --> PREV["--tts-only จบที่นี่<br/>voice_preview.wav + timeline.json"]
    JOIN --> CAP --> CUT --> PX
    SEG --> MUX
    MUX --> OUT["projects/&lt;ชื่อ&gt;/<br/>final.mp4<br/>timeline.json<br/>credits.txt"]

    C1[("project/cache/tts")] -.-> TTS
    C2[("project/cache/pexels")] -.-> PX
    M[("music/")] -.-> MUX
    OUT --> REVIEW["ตรวจ timeline.json<br/>ไม่ถูกใจ → แก้ query / ปัก pexels_video_id<br/>แล้วรันใหม่ (คัตเดิมมาจาก cache)"]
```

### แต่ละขั้นทำอะไร

| ขั้น | Input | Output | จุดที่ปรับได้ |
|---|---|---|---|
| Validate | `storyboard.json` | storyboard ที่ผ่าน schema | `storyboard.schema.json` |
| 1. Voiceover | `narration_lines`, `voice` | เสียงแต่ละ scene (ลงเฟรมพอดี) | `voice.rate`, `line_gap_sec`, `scene_gap_sec`, `trim_silence`, `pronunciations` |
| 2. Caption timing | ข้อความ + word timing | วลีซับพร้อมเวลา | `subtitles.max_chars`, `min_chars`, `emphasis_words` |
| 3. Cut plan | `cuts[].duration_hint_sec` + ความยาวเสียงจริง | ความยาวจริงของแต่ละคัต | `render.min_cut_sec`, `max_cut_sec` |
| 4. Footage | `pexels_query`, `fallback_queries`, `pexels_video_id` | คลิป 1080x1920 ต่อคัต | `render.footage_speed`, `--refresh-footage`, `--seed` |
| 5. Compose | วิดีโอ + เสียง + ซับ + เพลง | `final_shorts.mp4` | `bgm.volume`, `bgm.duck_ratio`, `--no-subs`, `--no-bgm` |

ค่า default ของตัวปรับหลักอยู่เป็น constant ที่หัว `render_shorts.py` (`TTS_*`, `FOOTAGE_SPEED`, `BGM_VOLUME`, `BGM_DUCK_RATIO`, `EST_CHARS_PER_SEC`) ค่าที่ใส่ใน storyboard จะใช้แทน default

### ไฟล์ที่เกิดขึ้น

ทุกอย่างของคลิปหนึ่งอยู่ใน `projects/<ชื่อ>/` เสร็จงานแล้วลบทั้งโฟลเดอร์ได้เลย

| ที่อยู่ (ใน `projects/<ชื่อ>/`) | คืออะไร | ลบได้ไหม |
|---|---|---|
| `storyboard.json` | บทและแผนคัต (input) | ไม่ควร |
| `final.mp4` | วิดีโอผลลัพธ์ (เปลี่ยนชื่อได้ด้วย `-o`) | ผลลัพธ์ |
| `timeline.json` | เวลาและ Pexels id ของทุกคัต + warnings | ผลลัพธ์ |
| `credits.txt` | เครดิตฟุตเทจสำหรับใส่คำอธิบายคลิป | ผลลัพธ์ |
| `voice_preview.wav` | เสียงพากย์จาก `--tts-only` | ได้ |
| `cache/tts/` | mp3 + word timing ต่อบรรทัด (key = ข้อความ + voice + rate + pitch) | ได้ แต่จะต้องเจนเสียงใหม่ |
| `cache/pexels/` | ผลค้นหาและไฟล์ฟุตเทจ | ได้ แต่จะต้องค้นและโหลดใหม่ และคลิปที่ได้อาจเปลี่ยน |
| `build/` | ไฟล์ชั่วคราวระหว่างเรนเดอร์ (ลบเองเมื่อสำเร็จ ยกเว้นใช้ `--keep-temp`) | ได้ |

> `timeline.json`, `credits.txt` และ `voice_preview.wav` ถูกเขียนลงโฟลเดอร์เดียวกับวิดีโอเสมอ ถ้าใช้ `-o` ชี้ออกนอก project ไฟล์พวกนี้จะไปอยู่ที่นั่นด้วย

---

## คู่มือสร้างวิดีโอใหม่

### 0. เตรียมครั้งแรก (ทำครั้งเดียว)

```bash
cd auto-shorts
source .venv/bin/activate          # ทุกคำสั่งด้านล่างสมมติว่า activate แล้ว
python -c "from PIL import features; print(features.check('raqm'))"   # ต้องได้ True
grep -q your_pexels_api_key_here .env && echo "ยังไม่ได้ใส่ PEXELS_API_KEY"
ls music/                          # มีเพลงอย่างน้อย 1 ไฟล์ (ไม่มีก็เรนเดอร์ได้ แต่ไม่มี BGM)
```

### 1. ให้ Claude เจน storyboard

แนบไฟล์ `storyboard.schema.json` (และแนบ `examples/storyboard.json` เป็นตัวอย่างด้วยก็ได้) แล้วใช้ prompt นี้:

```
คุณคือ Story Director ของช่อง YouTube Shorts ภาษาไทย
หัวข้อ: <หัวข้อ>   ความยาวเป้าหมาย: 40–50 วินาที   โทน: <เช่น ตื่นเต้น/อบอุ่น>

สร้าง storyboard.json ตาม schema ที่แนบ (schema_version "1.0") โดย:
- โครงสร้าง H-C-B-R: HOOK (3–4 วิ, ประโยคแรกต้องหยุดนิ้ว) → CONFLICT → BODY 1–2 scene → RESOLUTION + CTA
- narration_lines: ภาษาไทยพูดธรรมชาติ บรรทัดละ 1 ประโยค เว้นวรรคตรงจุดหายใจ/จุดที่อยากให้ซับตัด
  รวมทั้งคลิปประมาณ 13 ตัวอักษร/วินาที (≈ 550–600 ตัวอักษรสำหรับ 45 วิ)
- ตัวเลข ตัวย่อ และคำภาษาอังกฤษ ให้ใส่คำอ่านไว้ใน voice.pronunciations เช่น {"AI": "เอไอ"}
- cuts: 1 คัตต่อเสียงพูดประมาณ 2–2.5 วินาที, duration_hint_sec 1.5–3.0
  HOOK ที่ยาว 3–4 วิ ให้มี 2 คัต
- pexels_query: ภาษาอังกฤษ รูปธรรม "subject + action/object (+ setting)" 3–7 คำ
  ห้ามคำนามธรรม (success, motivation, idea) ห้าม AI/cartoon/3D/illustration
  ฟุตเทจจะเล่น 2x จึงควรเลือกฉากที่มีการเคลื่อนไหวต่อเนื่อง (มือทำงาน, คนเดิน, เมือง, ธรรมชาติ)
  ใส่ fallback_queries 1–2 อันที่กว้างขึ้น
- สลับ shot_type ระหว่างคัตติดกัน (close_up ↔ wide ↔ overhead ...) เพื่อ visual rhythm
- ใส่ subtitles.emphasis_words 3–5 คำสำคัญ (ต้องสะกดตรงกับในบท)
- คง voice, render, bgm ตามไฟล์ตัวอย่าง (voice_id th-TH-NiwatNeural, footage_speed 2.0)
ส่งเฉพาะ JSON ที่ valid เท่านั้น
```

บันทึกผลเป็น `projects/<ชื่อ>/storyboard.json` เช่น

```bash
mkdir -p projects/my_clip
# วาง JSON ลงไฟล์ projects/my_clip/storyboard.json
```

ชื่อ project ใช้ได้เฉพาะ a–z, A–Z, 0–9, `-` และ `_`

### 2. ตรวจโครงสร้างและดูแผน (ไม่ใช้เน็ต)

```bash
python render_shorts.py my_clip --dry-run
```

สิ่งที่ต้องดู:
- **ผ่าน schema** ถ้าไม่ผ่าน ให้ส่ง error กลับให้ Claude แก้
- **`≈ XXs estimated`** ควรอยู่ในช่วง 40–50s และห้ามเกิน 60s (ค่าประมาณคลาดจริงราว ±3%)
- **`N cuts (≈M needed)`** ถ้า N ห่างจาก M มาก ระบบจะแตกหรือรวมคัตเอง ควรให้ Claude เพิ่มหรือลดคัตให้ใกล้ M

### 3. เจนเสียงอย่างเดียวเพื่อฟังก่อน

```bash
python render_shorts.py my_clip --tts-only
open projects/my_clip/voice_preview.wav
```

- ฟังการออกเสียง ถ้าคำไหนอ่านผิด ให้เพิ่มใน `voice.pronunciations` แล้วรันใหม่ (ซับยังแสดงข้อความเดิม)
- ดูความยาวจริงที่ `total voice: XXs`
- ขั้นนี้ยังไม่ใช้ Pexels quota เสียงที่เจนแล้วจะถูก cache ไว้ใช้ตอนเรนเดอร์จริง

### 4. เรนเดอร์จริง

```bash
python render_shorts.py my_clip
open projects/my_clip/final.mp4
```

### 5. ตรวจผลและแก้ (Human-in-the-loop)

```bash
# ดู warnings
python -c "import json;[print('-',w) for w in json.load(open('projects/my_clip/timeline.json'))['warnings']]"

# ดูว่าแต่ละคัตใช้คลิปไหน
python -c "
import json
for s in json.load(open('projects/my_clip/timeline.json'))['scenes']:
    for c in s['cuts']:
        print(c['cut_id'], c['pexels_video_id'], c['query_used'], c['pexels_url'])"
```

| อาการ | วิธีแก้ |
|---|---|
| คัตไหนภาพไม่ตรงบท | ใส่ `"pexels_video_id": <id>` ในคัตนั้น หรือแก้ `pexels_query` แล้วรันใหม่ (คัตอื่นจะได้คลิปเดิมจาก cache) |
| ได้คลิปเดิมทั้งที่แก้ query แล้ว | เพิ่ม `--refresh-footage` |
| อยากได้จุดเริ่มคลิปหรือเพลงแบบอื่น | `--seed 7` (หรือเลขอื่น) |
| `needs N cuts (storyboard has M)` | บทยาวเกินกว่าจำนวนคัต → เพิ่มคัตหรือตัดบท |
| `dropped cut(s)` | scene สั้นเกินกว่าจะใส่ทุกคัต → ลดคัตหรือเพิ่มบท |
| `upscaled` | คลิปความละเอียดต่ำ → ปักคลิปใหม่หรือเปลี่ยนคีย์เวิร์ด |
| `looping a shorter clip` | คลิปสั้นกว่า คัต × `footage_speed` → เปลี่ยน query เป็นฉากที่มีคลิปยาวกว่า |
| เสียงพูดชิดกันเกินไป | เพิ่ม `voice.line_gap_sec` (0.03–0.08) หรือ `scene_gap_sec` (0.1–0.2) |
| พยัญชนะท้ายคำขาด | เพิ่ม `TTS_KEEP_TAIL_SEC` ที่หัว `render_shorts.py` |
| เพลงดัง/เบาเกิน | ปรับ `bgm.volume` และ `bgm.duck_ratio` (ratio ต่ำ = เพลงดังใต้เสียงพูดมากขึ้น) |
| `No audio was received` | voice นั้นล่มฝั่ง Microsoft → ทดสอบด้วย `edge-tts --voice <id> --text "ทดสอบ" --write-media test.mp3` แล้วเปลี่ยน `voice_id` |

### 6. เผยแพร่

- คัดลอกเนื้อหาใน `projects/my_clip/credits.txt` ไปใส่ในคำอธิบายคลิป
- ใช้เฉพาะเพลงที่คุณมีสิทธิ์ใช้

### สรุปคำสั่ง

```bash
python render_shorts.py <ชื่อ> --dry-run      # ตรวจ + ประมาณความยาว
python render_shorts.py <ชื่อ> --tts-only     # เสียงอย่างเดียว
python render_shorts.py <ชื่อ>                # เรนเดอร์จริง → projects/<ชื่อ>/final.mp4
rm -rf projects/<ชื่อ>                        # เสร็จงานแล้วลบทั้ง project

# flags เสริม
--no-subs            # ไม่ใส่ซับ
--no-bgm             # ไม่ใส่เพลง
--seed 7             # เปลี่ยนจุดเริ่มคลิปและเพลง
--refresh-footage    # ค้น Pexels ใหม่ ไม่ใช้ cache
--keep-temp          # เก็บ projects/<ชื่อ>/build/ ไว้ debug
-o v2.mp4            # ตั้งชื่อไฟล์วิดีโอเอง (อยู่ใน project)
```
