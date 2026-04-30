import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_float(value: str, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _as_list(value: str) -> List[int]:
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip()]


@dataclass
class Settings:
    telegram_bot_token: str
    gemini_api_key: str
    gemini_api_keys: List[str]
    gemini_api_keys_file: Path
    bot_admin_ids: List[int]
    output_dir: Path
    temp_dir: Path
    log_dir: Path
    max_video_duration_minutes: int
    max_clips_per_video: int
    default_clip_duration: int
    default_output_ratio: str
    default_caption_language: str
    default_output_quality: str
    enable_subtitle_default: bool
    enable_watermark_default: bool
    watermark_default_text: str
    watermark_default_position: str
    watermark_default_opacity: float
    watermark_default_font_size: int
    whisperx_model: str
    whisperx_device: str
    whisperx_compute_type: str
    gemini_model: str
    ytdlp_cookies_file: Path
    ytdlp_cookies_from_browser: str
    max_concurrent_jobs: int
    telegram_max_file_size_mb: int
    auto_delete_temp_files: bool
    auto_delete_output_after_send: bool

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        base = Path.cwd()
        gemini_api_keys_file = base / os.getenv("GEMINI_API_KEYS_FILE", "config/gemini_api_keys.txt")
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        gemini_api_keys = cls._load_gemini_api_keys(gemini_api_keys_file, gemini_api_key)
        settings = cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            gemini_api_key=gemini_api_key,
            gemini_api_keys=gemini_api_keys,
            gemini_api_keys_file=gemini_api_keys_file,
            bot_admin_ids=_as_list(os.getenv("BOT_ADMIN_IDS", "")),
            output_dir=base / os.getenv("OUTPUT_DIR", "outputs"),
            temp_dir=base / os.getenv("TEMP_DIR", "temp"),
            log_dir=base / os.getenv("LOG_DIR", "logs"),
            max_video_duration_minutes=_as_int(os.getenv("MAX_VIDEO_DURATION_MINUTES"), 60),
            max_clips_per_video=_as_int(os.getenv("MAX_CLIPS_PER_VIDEO"), 5),
            default_clip_duration=_as_int(os.getenv("DEFAULT_CLIP_DURATION"), 30),
            default_output_ratio=os.getenv("DEFAULT_OUTPUT_RATIO", "9:16"),
            default_caption_language=os.getenv("DEFAULT_CAPTION_LANGUAGE", "id"),
            default_output_quality=os.getenv("DEFAULT_OUTPUT_QUALITY", "medium"),
            enable_subtitle_default=_as_bool(os.getenv("ENABLE_SUBTITLE_DEFAULT"), True),
            enable_watermark_default=_as_bool(os.getenv("ENABLE_WATERMARK_DEFAULT"), False),
            watermark_default_text=os.getenv("WATERMARK_DEFAULT_TEXT", "").strip(),
            watermark_default_position=os.getenv("WATERMARK_DEFAULT_POSITION", "top-center"),
            watermark_default_opacity=_as_float(os.getenv("WATERMARK_DEFAULT_OPACITY"), 0.35),
            watermark_default_font_size=_as_int(os.getenv("WATERMARK_DEFAULT_FONT_SIZE"), 28),
            whisperx_model=os.getenv("WHISPERX_MODEL", "small"),
            whisperx_device=os.getenv("WHISPERX_DEVICE", "cpu"),
            whisperx_compute_type=os.getenv("WHISPERX_COMPUTE_TYPE", "int8"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            ytdlp_cookies_file=base / os.getenv("YTDLP_COOKIES_FILE", "config/youtube_cookies.txt"),
            ytdlp_cookies_from_browser=os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip(),
            max_concurrent_jobs=_as_int(os.getenv("MAX_CONCURRENT_JOBS"), 2),
            telegram_max_file_size_mb=_as_int(os.getenv("TELEGRAM_MAX_FILE_SIZE_MB"), 50),
            auto_delete_temp_files=_as_bool(os.getenv("AUTO_DELETE_TEMP_FILES"), True),
            auto_delete_output_after_send=_as_bool(os.getenv("AUTO_DELETE_OUTPUT_AFTER_SEND"), False),
        )
        settings.validate_required()
        settings.ensure_dirs()
        return settings

    def validate_required(self) -> None:
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.gemini_api_keys:
            missing.append("GEMINI_API_KEYS_FILE (atau GEMINI_API_KEY)")
        if self.max_concurrent_jobs < 1:
            raise RuntimeError("MAX_CONCURRENT_JOBS minimal 1.")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Konfigurasi wajib belum diisi di .env: {joined}")

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_gemini_api_keys(keys_file: Path, env_key: str) -> List[str]:
        keys: List[str] = []
        if keys_file.exists():
            for line in keys_file.read_text(encoding="utf-8").splitlines():
                value = line.strip()
                if not value or value.startswith("#"):
                    continue
                keys.append(value)
        if env_key:
            keys.append(env_key)

        unique = []
        seen = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique
