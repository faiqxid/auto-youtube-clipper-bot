import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


YOUTUBE_REGEX = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{6,}",
    re.IGNORECASE,
)


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bot.log"
    logger = logging.getLogger("auto-youtube-clipper-bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(formatter)
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def is_valid_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_REGEX.match(url.strip()))


def parse_time_to_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    return float(parts[0])


def seconds_to_hhmmss(seconds: float) -> str:
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def run_command(
    cmd: Iterable[str],
    logger: logging.Logger,
    timeout: Optional[int] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    logger.info("Run command: %s", " ".join(cmd))
    return subprocess.run(
        list(cmd),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def safe_rmtree(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def ensure_disk_space(path: Path, min_free_mb: int = 500) -> bool:
    usage = shutil.disk_usage(path)
    free_mb = usage.free / (1024 * 1024)
    return free_mb >= min_free_mb


def now_ms() -> int:
    return int(time.time() * 1000)


def build_unique_name(prefix: str, ext: str) -> str:
    token = str(now_ms())
    ext = ext.lstrip(".")
    return f"{prefix}_{token}.{ext}"


def escape_ffmpeg_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
    )


def escape_ffmpeg_path(path: Path) -> str:
    normalized = path.as_posix()
    normalized = normalized.replace(":", "\\:")
    return normalized
