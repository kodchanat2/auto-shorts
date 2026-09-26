"""Social-app UI overlays (transparent 9:16 images in overlays/) drawn over the video preview only."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from render_shorts import SCRIPT_DIR

OVERLAY_DIR = SCRIPT_DIR / "overlays"
IMAGE_EXTS = {".png", ".webp"}

# Keeps the overlay image glued to the visible 9:16 picture inside the Gradio video player
# (the player letterboxes and resizes, so this re-measures a few times a second).
SYNC_JS = """
<script>
(() => {
  function sync() {
    document.querySelectorAll('.as-preview').forEach((root) => {
      const img = root.querySelector('img.as-overlay-img');
      if (!img) return;
      const v = root.querySelector('video');
      const r = v && v.getBoundingClientRect();
      if (!r || !r.width || !r.height) { img.style.display = 'none'; return; }
      const ar = v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : 9 / 16;
      let w = r.width, h = r.height;
      if (w / h > ar) w = h * ar; else h = w / ar;
      const op = (img.offsetParent || document.body).getBoundingClientRect();
      Object.assign(img.style, {
        display: 'block',
        left: (r.left + (r.width - w) / 2 - op.left) + 'px',
        top: (r.top + (r.height - h) / 2 - op.top) + 'px',
        width: w + 'px', height: h + 'px',
      });
    });
  }
  setInterval(sync, 300);
  window.addEventListener('resize', sync);
})();
</script>
"""


def list_overlays(folder: Path = OVERLAY_DIR) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def overlay_html(name: str | None, enabled: bool, folder: Path = OVERLAY_DIR) -> str:
    if not enabled or not name:
        return ""
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        return ""
    return f'<img class="as-overlay-img" alt="" src="/gradio_api/file={quote(str(path))}">'
