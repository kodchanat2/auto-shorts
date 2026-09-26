"""Look & feel: warm paper background, ink text, tomato accent for actions and progress."""
from __future__ import annotations

import html

import gradio as gr

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.orange,
    neutral_hue=gr.themes.colors.stone,
    font=[gr.themes.GoogleFont("IBM Plex Sans Thai"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    radius_size=gr.themes.sizes.radius_sm,
).set(
    body_background_fill="var(--as-paper)",
    block_background_fill="var(--as-surface)",
    button_primary_background_fill="var(--as-accent)",
    button_primary_background_fill_hover="var(--as-accent-strong)",
    button_primary_text_color="#fff",
)

CSS = """
:root {
  --as-paper: #f6f1e7; --as-surface: #fffdf8; --as-ink: #1f1b16; --as-muted: #6f675c;
  --as-accent: #e4572e; --as-accent-strong: #c2411c; --as-ok: #2f7d4f; --as-err: #b3261e;
  --as-track: #e9e1d2;
}
.dark {
  --as-paper: #16130f; --as-surface: #201c17; --as-ink: #f3ede3; --as-muted: #a79d8f;
  --as-track: #3a332a;
}
.as-title h1 { font-family: "Kanit", sans-serif; font-weight: 700; letter-spacing: -0.02em;
  font-size: clamp(1.8rem, 1.2rem + 2vw, 2.6rem); margin: 0; color: var(--as-ink); }
.as-title p { color: var(--as-muted); margin: .2rem 0 0; }
.as-bar { display: grid; gap: .35rem; }
.as-bar-track { height: 12px; border-radius: 999px; background: var(--as-track); overflow: hidden; }
.as-bar-fill { height: 100%; background: var(--as-accent); transform-origin: left;
  transition: transform 300ms cubic-bezier(0.16, 1, 0.3, 1); }
.as-bar[data-state="ok"] .as-bar-fill { background: var(--as-ok); }
.as-bar[data-state="error"] .as-bar-fill { background: var(--as-err); }
.as-bar-label { font-size: .9rem; color: var(--as-muted); font-variant-numeric: tabular-nums; }
.as-bar[data-state="error"] .as-bar-label { color: var(--as-err); }
@media (prefers-reduced-motion: reduce) { .as-bar-fill { transition: none; } }
.as-overlay-img { position: absolute; pointer-events: none; z-index: 20; display: none; }
.as-overlay-slot { height: 0 !important; min-height: 0 !important; overflow: visible !important; }
/* dropdown menus: lift them off the page so they don't read as transparent */
.options { background: var(--as-surface) !important; border: 1px solid var(--as-track) !important;
  box-shadow: 0 12px 32px rgb(0 0 0 / 0.28) !important; border-radius: 8px !important; }
"""

HEAD = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Kanit:wght@600;700&display=swap" rel="stylesheet">')


def progress_bar(fraction: float, label: str, state: str = "running") -> str:
    """state: running | ok | error. Width animates via transform (compositor-only)."""
    f = max(0.0, min(1.0, fraction))
    return (f'<div class="as-bar" data-state="{state}" role="progressbar" aria-valuemin="0" '
            f'aria-valuemax="100" aria-valuenow="{round(f * 100)}">'
            f'<div class="as-bar-track"><div class="as-bar-fill" style="transform: scaleX({f:.3f})"></div></div>'
            f'<div class="as-bar-label">{round(f * 100)}% · {html.escape(label)}</div></div>')
