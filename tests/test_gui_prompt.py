from gui import prompt as PR
from gui.projects import Brief

DOC = """# title

intro

````text
หัวข้อ: <หัวข้อคลิป>
ความยาวเป้าหมาย: 45 วินาที
โทน: <เช่น ตื่นเต้น / อบอุ่น / ลึกลับ>

body "target_duration_sec": 45,
````
"""


def test_load_template_extracts_text_block(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text(DOC, encoding="utf-8")
    tpl = PR.load_template(doc)
    assert tpl.startswith("หัวข้อ:")
    assert "````" not in tpl
    assert "intro" not in tpl


def test_build_prompt_fills_brief():
    tpl = DOC.split("````text\n")[1].split("````")[0]
    out = PR.build_prompt(tpl, Brief(topic="แมวกับกล่อง", tone="ตลก", duration=40))
    assert "หัวข้อ: แมวกับกล่อง" in out
    assert "ความยาวเป้าหมาย: 40 วินาที" in out
    assert "โทน: ตลก" in out
    assert '"target_duration_sec": 40' in out
    assert "<หัวข้อคลิป>" not in out


def test_real_prompt_doc_has_all_placeholders():
    tpl = PR.load_template(PR.PROMPT_DOC)
    out = PR.build_prompt(tpl, Brief(topic="X", tone="Y", duration=50))
    assert "หัวข้อ: X" in out and "โทน: Y" in out and "ความยาวเป้าหมาย: 50 วินาที" in out


def test_fix_prompt_contains_errors():
    out = PR.build_fix_prompt("• scenes/0/cuts: bad")
    assert "• scenes/0/cuts: bad" in out
    assert "JSON" in out
