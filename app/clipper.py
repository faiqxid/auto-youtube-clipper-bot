import json
import logging
from pathlib import Path
from typing import Dict, Optional

from app.utils import escape_ffmpeg_path, run_command
from app.watermark import build_drawtext_filter


QUALITY_CRF = {
    "low": "30",
    "medium": "24",
    "high": "20",
}


def get_video_probe(video_path: Path, logger: logging.Logger) -> Dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        str(video_path),
    ]
    result = run_command(cmd, logger)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    width = int(stream.get("width", 1920))
    height = int(stream.get("height", 1080))
    duration = float(stream.get("duration", 0.0))
    return {"width": width, "height": height, "duration": duration}


def extract_audio(video_path: Path, audio_path: Path, logger: logging.Logger) -> Path:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_path),
    ]
    run_command(cmd, logger)
    return audio_path


def _build_crop_filter(src_w: int, src_h: int, focus_x_ratio: float) -> str:
    target_w = 1080
    target_h = 1920
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio >= target_ratio:
        crop_w = int(src_h * target_ratio)
        crop_h = src_h
        center_x = int(src_w * focus_x_ratio)
        x = max(0, min(src_w - crop_w, center_x - (crop_w // 2)))
        y = 0
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)
        x = 0
        y = max(0, (src_h - crop_h) // 2)

    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={target_w}:{target_h}"


def render_vertical_clip(
    source_video: Path,
    output_video: Path,
    start_time: float,
    end_time: float,
    source_width: int,
    source_height: int,
    focus_x_ratio: float,
    quality: str,
    subtitle_srt: Optional[Path],
    watermark_config: Optional[Dict],
    logger: logging.Logger,
) -> Path:
    vf_chain = [_build_crop_filter(source_width, source_height, focus_x_ratio)]

    if subtitle_srt and subtitle_srt.exists() and subtitle_srt.stat().st_size > 0:
        srt_path = escape_ffmpeg_path(subtitle_srt)
        vf_chain.append(
            "subtitles="
            f"'{srt_path}':"
            "force_style='Alignment=2,FontSize=10,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Bold=1,Outline=2,MarginV=100'"
        )

    if watermark_config and watermark_config.get("enabled") and watermark_config.get("text"):
        wf = build_drawtext_filter(watermark_config)
        if wf:
            vf_chain.append(wf)

    crf = QUALITY_CRF.get(quality, QUALITY_CRF["medium"])
    vf = ",".join(vf_chain)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_time}",
        "-to",
        f"{end_time}",
        "-i",
        str(source_video),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        crf,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_video),
    ]
    run_command(cmd, logger, timeout=60 * 20)
    return output_video
