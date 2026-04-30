import logging
from pathlib import Path
from typing import Dict

import yt_dlp


def fetch_video_info(url: str, logger: logging.Logger) -> Dict:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        logger.info("Fetching video metadata: %s", url)
        info = ydl.extract_info(url, download=False)
        return info


def download_video(url: str, output_dir: Path, logger: logging.Logger) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(output_dir / "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        logger.info("Downloading video: %s", url)
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
        if path.suffix.lower() != ".mp4":
            mp4_candidate = path.with_suffix(".mp4")
            if mp4_candidate.exists():
                path = mp4_candidate
        logger.info("Video downloaded: %s", path)
        return path
