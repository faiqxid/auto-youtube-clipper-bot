from typing import Dict, Tuple

from app.utils import escape_ffmpeg_text


def _position_expr(position: str) -> Tuple[str, str]:
    pos_map = {
        "top-left": ("40", "40"),
        "top-center": ("(w-text_w)/2", "40"),
        "top-right": ("w-text_w-40", "40"),
        "center-left": ("40", "(h-text_h)/2"),
        "center": ("(w-text_w)/2", "(h-text_h)/2"),
        "center-right": ("w-text_w-40", "(h-text_h)/2"),
        "bottom-left": ("40", "h-text_h-80"),
        "bottom-center": ("(w-text_w)/2", "h-text_h-80"),
        "bottom-right": ("w-text_w-40", "h-text_h-80"),
    }
    return pos_map.get(position, pos_map["top-center"])


def build_drawtext_filter(config: Dict) -> str:
    text = escape_ffmpeg_text(config.get("text", ""))
    if not text:
        return ""
    x, y = _position_expr(config.get("position", "top-center"))
    opacity = float(config.get("opacity", 0.35))
    font_size = int(config.get("font_size", 28))
    return (
        "drawtext="
        f"text='{text}':"
        f"x={x}:y={y}:"
        f"fontsize={font_size}:"
        "fontcolor=white:"
        f"alpha={opacity}:"
        "borderw=2:bordercolor=black@0.5"
    )
