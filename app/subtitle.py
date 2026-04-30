from pathlib import Path
from typing import Dict, List


def _fmt_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_srt_time(seconds: float) -> str:
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clean_word(word: str) -> str:
    w = (word or "").strip()
    if not w:
        return ""
    return w.replace("{", "").replace("}", "").replace("\n", " ")


def _iter_words_for_clip(transcript_segments: List[Dict], clip_start: float, clip_end: float) -> List[Dict]:
    words = []
    for seg in transcript_segments:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        if seg_end < clip_start or seg_start > clip_end:
            continue

        seg_words = seg.get("words") or []
        valid_words = []
        for item in seg_words:
            w = _clean_word(str(item.get("word", "")))
            if not w:
                continue
            if item.get("start") is None or item.get("end") is None:
                continue
            ws = float(item["start"])
            we = float(item["end"])
            if we <= ws:
                continue
            if we < clip_start or ws > clip_end:
                continue
            valid_words.append(
                {
                    "text": w,
                    "start": max(ws, clip_start) - clip_start,
                    "end": min(we, clip_end) - clip_start,
                }
            )
        if valid_words:
            words.extend(valid_words)
            continue

        # Fallback jika word-level timestamp tidak tersedia:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        split_words = [_clean_word(x) for x in text.split()]
        split_words = [x for x in split_words if x]
        if not split_words:
            continue
        start = max(seg_start, clip_start) - clip_start
        end = min(seg_end, clip_end) - clip_start
        if end <= start:
            continue
        dur = (end - start) / len(split_words)
        for i, token in enumerate(split_words):
            ws = start + (i * dur)
            we = start + ((i + 1) * dur)
            words.append({"text": token, "start": ws, "end": we})

    words.sort(key=lambda x: x["start"])
    return words


def _build_karaoke_events(words: List[Dict], max_words_per_event: int = 6, max_event_seconds: float = 3.2) -> List[str]:
    if not words:
        return []

    events = []
    chunk: List[Dict] = []

    def flush_chunk() -> None:
        nonlocal chunk
        if not chunk:
            return
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        if end <= start:
            chunk = []
            return

        parts = []
        for w in chunk:
            word_dur_cs = max(8, int(round((w["end"] - w["start"]) * 100)))
            parts.append(rf"{{\k{word_dur_cs}}}{w['text']}")
        text = " ".join(parts)
        events.append(
            f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},Karaoke,,0,0,0,,{text}"
        )
        chunk = []

    for w in words:
        if not chunk:
            chunk.append(w)
            continue
        projected_count = len(chunk) + 1
        projected_dur = w["end"] - chunk[0]["start"]
        if projected_count > max_words_per_event or projected_dur > max_event_seconds:
            flush_chunk()
        chunk.append(w)
    flush_chunk()
    return events


def build_ass_karaoke_for_clip(
    transcript_segments: List[Dict],
    clip_start: float,
    clip_end: float,
    output_path: Path,
) -> Path:
    words = _iter_words_for_clip(transcript_segments, clip_start, clip_end)
    events = _build_karaoke_events(words)
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Karaoke,Arial,58,&H00FFFFFF,&H0000D7FF,&H00000000,&H32000000,"
        "1,0,0,0,100,100,0,0,1,3,0,2,70,70,210,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    lines = header + events

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
