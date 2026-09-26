from gui import overlays as O


def test_list_overlays_only_images_sorted(tmp_path):
    for name in ["b_tiktok.png", "a_shorts.webp", "README.txt", "c.PNG"]:
        (tmp_path / name).write_text("x")
    assert O.list_overlays(tmp_path) == ["a_shorts.webp", "b_tiktok.png", "c.PNG"]


def test_list_overlays_missing_dir(tmp_path):
    assert O.list_overlays(tmp_path / "nope") == []


def test_overlay_html_off_or_missing_is_empty(tmp_path):
    (tmp_path / "shorts.png").write_text("x")
    assert O.overlay_html("shorts.png", False, tmp_path) == ""
    assert O.overlay_html(None, True, tmp_path) == ""
    assert O.overlay_html("missing.png", True, tmp_path) == ""


def test_overlay_html_points_at_served_file(tmp_path):
    (tmp_path / "my shorts.png").write_text("x")
    html = O.overlay_html("my shorts.png", True, tmp_path)
    assert 'class="as-overlay-img"' in html
    assert "/gradio_api/file=" in html and "my%20shorts.png" in html


def test_overlay_html_rejects_path_escape(tmp_path):
    (tmp_path / "overlays").mkdir()
    (tmp_path / "secret.png").write_text("x")
    assert O.overlay_html("../secret.png", True, tmp_path / "overlays") == ""
