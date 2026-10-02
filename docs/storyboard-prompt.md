# Prompt สร้าง Storyboard

คัดลอกข้อความในกรอบด้านล่างทั้งก้อนไปวางในแชต Claude แล้วแก้แค่ 3 บรรทัดแรก (หัวข้อ, ความยาว, โทน) ไม่ต้องแนบไฟล์ เพราะกฎของ `storyboard.schema.json` อยู่ในข้อความนี้ครบแล้ว

ได้ JSON กลับมาแล้วให้บันทึกเป็น `projects/<ชื่อ>/storyboard.json` แล้วรัน `python render_shorts.py <ชื่อ> --dry-run` ถ้าไม่ผ่าน ให้ส่ง error กลับไปให้ Claude แก้

> ถ้าแก้ `storyboard.schema.json` (เพิ่มหรือลบ field, เปลี่ยน enum) ต้องแก้ prompt นี้ตามด้วย

````text
หัวข้อ: <หัวข้อคลิป>
ความยาวเป้าหมาย: 45 วินาที
โทน: <เช่น ตื่นเต้น / อบอุ่น / ลึกลับ>

คุณคือ Story Director ของช่อง YouTube Shorts ภาษาไทย
สร้าง storyboard เป็น JSON ตามโครงสร้างและกฎด้านล่างนี้ ส่งกลับเฉพาะ JSON ที่ valid ในบล็อกเดียว ไม่ต้องอธิบาย

## โครงสร้าง (ห้ามมี key อื่นนอกจากที่ระบุ)

{
  "schema_version": "1.0",
  "meta": {
    "title": "<ชื่อคลิปภาษาไทย>",
    "topic": "<หัวข้อสั้นๆ ภาษาอังกฤษหรือไทย>",
    "target_duration_sec": 45,
    "language": "th-TH"
  },
  "voice": {
    "voice_id": "th-TH-NiwatNeural",
    "rate": "+10%",
    "pitch": "+0Hz",
    "line_gap_sec": 0.05,
    "scene_gap_sec": 0.12,
    "pronunciations": { "AI": "เอไอ" }
  },
  "subtitles": {
    "emphasis_words": ["<คำสำคัญ 1>", "<คำสำคัญ 2>", "<คำสำคัญ 3>"]
  },
  "scenes": [
    {
      "scene_id": "S1",
      "role": "HOOK",
      "emotion": "<อารมณ์ของฉาก เช่น ท้าทาย ชวนสงสัย>",
      "visual_intent": "<ภาพรวมที่ผู้ชมควรเห็น/รู้สึก>",
      "narration_lines": ["<ประโยคที่ 1>", "<ประโยคที่ 2>"],
      "cuts": [
        {
          "cut_id": "S1C1",
          "duration_hint_sec": 2.0,
          "shot_type": "close_up",
          "pexels_query": "<english concrete query>",
          "fallback_queries": ["<broader english query>"],
          "visual_intent": "<คัตนี้ต้องสื่ออะไร>"
        }
      ]
    }
  ]
}

## กฎของ field (ถ้าผิด ระบบจะไม่ยอมรับไฟล์)

- schema_version ต้องเป็น "1.0" เท่านั้น, meta.title ห้ามว่าง, target_duration_sec อยู่ในช่วง 15–180
- voice.rate รูปแบบ "+10%" (เครื่องหมาย + หรือ - ตามด้วยตัวเลข 1–3 หลักและ %), voice.pitch รูปแบบ "+0Hz"
- voice.pronunciations คือ {ข้อความในบท: คำอ่าน} ใช้แก้เฉพาะเสียงอ่าน ซับยังแสดงข้อความเดิม
  ใส่ทุกตัวเลข ตัวย่อ และคำภาษาอังกฤษที่อยู่ในบท เช่น {"80%": "แปดสิบเปอร์เซ็นต์", "AI": "เอไอ"} ถ้าไม่มีให้ใส่ {}
- scenes มีอย่างน้อย 2 scene แต่ละ scene ต้องมี scene_id, role, narration_lines, cuts
  และควรมี emotion ทุก scene (visual_intent, notes ใส่หรือไม่ใส่ก็ได้)
- scene_id และ cut_id ใช้ได้เฉพาะ A–Z a–z 0–9 _ - และห้ามซ้ำกันทั้งไฟล์ (ตั้งแบบ S1, S1C1, S1C2, S2, S2C1 …)
- role เป็นหนึ่งใน HOOK, CONFLICT, BODY, RESOLUTION เรียงตามลำดับนี้เท่านั้น
  scene แรกเป็น HOOK, scene สุดท้ายเป็น RESOLUTION, BODY มีซ้ำได้ 1–2 scene
- narration_lines มีอย่างน้อย 1 บรรทัด ห้ามเป็นข้อความว่าง
- cut แต่ละอันต้องมี cut_id, duration_hint_sec, shot_type, pexels_query
  (fallback_queries, visual_intent, notes ใส่หรือไม่ใส่ก็ได้; ห้ามใส่ pexels_video_id และ exclude_video_ids)
- duration_hint_sec เป็นตัวเลข 1.5–3.0 (เป็นแค่น้ำหนัก ระบบจะสเกลให้ตรงกับเสียงจริงเอง)
- shot_type เป็นหนึ่งใน: extreme_close_up, close_up, medium, wide, aerial, overhead, pov,
  over_the_shoulder, tracking, slow_motion, timelapse
- pexels_query และ fallback_queries ต้องเป็นภาษาอังกฤษล้วน ห้ามมีอักษรไทย, pexels_query ยาวอย่างน้อย 3 ตัวอักษร,
  fallback_queries ไม่เกิน 4 อัน
- subtitles.emphasis_words 3–5 คำ ต้องสะกดตรงกับที่ปรากฏในบทเป๊ะๆ
- ห้ามใส่ key render และ bgm (ระบบใช้ค่าตั้งต้นเอง)

## แนวทางการเขียน

- โครงเรื่อง H-C-B-R: HOOK 3–4 วินาที (ประโยคแรกต้องทำให้หยุดเลื่อน) → CONFLICT → BODY 1–2 scene → RESOLUTION + CTA
- narration_lines: ภาษาไทยแบบพูดธรรมชาติ บรรทัดละ 1 ประโยคสั้น
  เว้นวรรคตรงจุดหายใจหรือจุดที่อยากให้ซับขึ้นบรรทัดใหม่ (ซับแต่ละวลียาวไม่เกินประมาณ 14 ตัวอักษร)
- ความยาวบท: เสียงพูดประมาณ 12 ตัวอักษร/วินาที (ไม่นับวรรณยุกต์และสระบน/ล่าง)
  → 45 วินาที ≈ 500–550 ตัวอักษรรวมทั้งคลิป และห้ามเกิน 60 วินาที
- จำนวนคัต: 1 คัตต่อเสียงพูดประมาณ 2–2.5 วินาที, HOOK ที่ยาว 3–4 วินาทีให้มี 2 คัต
- pexels_query: รูปธรรม "subject + action/object (+ setting)" 3–7 คำ เช่น "woman scrolling phone in bed"
  ห้ามคำนามธรรม (success, motivation, idea) ห้าม AI / cartoon / 3D / illustration
  ฟุตเทจจะเล่นเร็ว 2 เท่า จึงควรเลือกฉากที่มีการเคลื่อนไหวต่อเนื่อง (มือทำงาน คนเดิน เมือง ธรรมชาติ)
- fallback_queries 1–2 อันที่กว้างกว่า query หลัก
- emotion: อารมณ์ของเสียงพากย์ในฉากนั้น 2–6 คำ บรรยายให้นักพากย์เข้าใจ เช่น "ท้าทาย ชวนสงสัย", "ตึงเครียด กดดัน",
  "ตื่นเต้น เปิดเผยความลับ", "มีพลัง เร่งเร้า", "อบอุ่น ให้กำลังใจ" และไล่อารมณ์ให้มีขึ้นลงตามโครงเรื่อง
- สลับ shot_type ระหว่างคัตที่อยู่ติดกัน (close_up ↔ wide ↔ overhead …) เพื่อให้ภาพมีจังหวะ
````
