from pathlib import Path
from typing import Dict, List


def _fmt_srt_time(seconds: float) -> str:
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt_for_clip(
    transcript_segments: List[Dict],
    clip_start: float,
    clip_end: float,
    output_path: Path,
) -> Path:
    lines = []
    idx = 1
    for seg in transcript_segments:
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        if end < clip_start or start > clip_end:
            continue
        s = max(start, clip_start) - clip_start
        e = min(end, clip_end) - clip_start
        if e <= s:
            continue
        lines.append(str(idx))
        lines.append(f"{_fmt_srt_time(s)} --> {_fmt_srt_time(e)}")
        lines.append(text)
        lines.append("")
        idx += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
