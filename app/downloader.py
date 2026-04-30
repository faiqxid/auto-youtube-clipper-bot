import logging
from pathlib import Path
from typing import Dict, Optional

import yt_dlp


def _parse_cookies_from_browser(value: str):
    # format sederhana: "chrome" atau "firefox:default"
    raw = (value or "").strip()
    if not raw:
        return None
    if ":" not in raw:
        return (raw,)
    browser, profile = raw.split(":", 1)
    browser = browser.strip()
    profile = profile.strip()
    if not browser:
        return None
    if profile:
        return (browser, profile)
    return (browser,)


def _build_ydl_opts(base_opts: Dict, auth: Optional[Dict], logger: logging.Logger) -> Dict:
    opts = dict(base_opts)
    auth = auth or {}
    cookies_file = auth.get("cookies_file")
    cookies_from_browser = auth.get("cookies_from_browser")

    if cookies_file:
        cookies_path = Path(cookies_file)
        if cookies_path.exists():
            opts["cookiefile"] = str(cookies_path)
        else:
            logger.warning("YTDLP_COOKIES_FILE tidak ditemukan: %s", cookies_path)

    browser_tuple = _parse_cookies_from_browser(cookies_from_browser or "")
    if browser_tuple:
        opts["cookiesfrombrowser"] = browser_tuple

    return opts


def _raise_user_friendly_error(exc: Exception) -> None:
    msg = str(exc)
    if "Sign in to confirm you" in msg or "not a bot" in msg:
        raise RuntimeError(
            "YouTube minta verifikasi anti-bot. Isi cookies YouTube di "
            "YTDLP_COOKIES_FILE (format Netscape) atau set YTDLP_COOKIES_FROM_BROWSER."
        ) from exc
    raise exc


def fetch_video_info(url: str, logger: logging.Logger, auth: Optional[Dict] = None) -> Dict:
    base_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }
    ydl_opts = _build_ydl_opts(base_opts, auth, logger)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        logger.info("Fetching video metadata: %s", url)
        try:
            info = ydl.extract_info(url, download=False)
            return info
        except Exception as exc:
            _raise_user_friendly_error(exc)


def download_video(url: str, output_dir: Path, logger: logging.Logger, auth: Optional[Dict] = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(output_dir / "%(id)s.%(ext)s")
    base_opts = {
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
    }
    ydl_opts = _build_ydl_opts(base_opts, auth, logger)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        logger.info("Downloading video: %s", url)
        try:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
            if path.suffix.lower() != ".mp4":
                mp4_candidate = path.with_suffix(".mp4")
                if mp4_candidate.exists():
                    path = mp4_candidate
            logger.info("Video downloaded: %s", path)
            return path
        except Exception as exc:
            _raise_user_friendly_error(exc)
