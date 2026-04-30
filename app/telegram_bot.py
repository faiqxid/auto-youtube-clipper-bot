import asyncio
import logging
from typing import Any, Dict

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.analyzer import analyze_moments
from app.caption import normalize_caption_and_hashtags
from app.clipper import extract_audio, get_video_probe, render_vertical_clip
from app.cropper import estimate_focus_x, summarize_visual_activity
from app.downloader import download_video, fetch_video_info
from app.scoring import rank_and_filter_clips
from app.subtitle import build_srt_for_clip
from app.transcriber import transcribe_audio
from app.utils import (
    build_unique_name,
    ensure_disk_space,
    is_valid_youtube_url,
    safe_rmtree,
    setup_logging,
)
from config.settings import Settings


YOUTUBE_LINK_PATTERN = r"(?i)^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{6,}"


(
    WAIT_LINK,
    WAIT_CLIP_COUNT,
    WAIT_DURATION,
    WAIT_DURATION_CUSTOM,
    WAIT_SUBTITLE,
    WAIT_WM_ENABLE,
    WAIT_WM_TEXT,
    WAIT_WM_POSITION,
    WAIT_WM_OPACITY,
    WAIT_WM_OPACITY_CUSTOM,
    WAIT_WM_FONT,
    WAIT_WM_FONT_CUSTOM,
    WAIT_QUALITY,
    WAIT_CONFIRM,
) = range(14)

RUNNING_JOBS: Dict[int, asyncio.Task] = {}
LOGGER: logging.Logger
SETTINGS: Settings
PROCESS_SEMAPHORE: asyncio.Semaphore


def _session_defaults() -> Dict[str, Any]:
    return {
        "youtube_url": "",
        "clip_count": min(3, SETTINGS.max_clips_per_video),
        "max_duration": SETTINGS.default_clip_duration,
        "subtitle_enabled": SETTINGS.enable_subtitle_default,
        "watermark": {
            "enabled": SETTINGS.enable_watermark_default,
            "text": SETTINGS.watermark_default_text,
            "position": SETTINGS.watermark_default_position,
            "opacity": SETTINGS.watermark_default_opacity,
            "font_size": SETTINGS.watermark_default_font_size,
        },
        "quality": SETTINGS.default_output_quality,
    }


def _yn(text: str) -> bool:
    return text.strip().lower() in {"ya", "yes", "aktif", "on"}


def _get_session(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    if "clip_session" not in context.user_data:
        context.user_data["clip_session"] = _session_defaults()
    return context.user_data["clip_session"]


async def _ask_clip_count(update: Update) -> None:
    keyboard = [["1", "2", "3"], ["4", "5"]]
    await update.message.reply_text(
        f"Berapa jumlah clip? (maks: {SETTINGS.max_clips_per_video})",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["clip_session"] = _session_defaults()
    await update.message.reply_text(
        "Kirim link YouTube untuk mulai proses clipping.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAIT_LINK


async def start_from_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not is_valid_youtube_url(text):
        await update.message.reply_text("Kirim `/start` lalu masukkan link YouTube.", parse_mode="Markdown")
        return ConversationHandler.END
    context.user_data["clip_session"] = _session_defaults()
    context.user_data["clip_session"]["youtube_url"] = text
    await _ask_clip_count(update)
    return WAIT_CLIP_COUNT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    task = RUNNING_JOBS.get(chat_id)
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("Proses dibatalkan.")
    else:
        await update.message.reply_text("Tidak ada proses aktif.")
    return ConversationHandler.END


async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text.strip()
    if not is_valid_youtube_url(url):
        await update.message.reply_text("Link tidak valid. Kirim link YouTube yang benar.")
        return WAIT_LINK
    session = _get_session(context)
    session["youtube_url"] = url
    await _ask_clip_count(update)
    return WAIT_CLIP_COUNT


async def receive_clip_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text("Masukkan angka jumlah clip.")
        return WAIT_CLIP_COUNT
    clip_count = int(raw)
    if clip_count < 1 or clip_count > SETTINGS.max_clips_per_video:
        await update.message.reply_text(f"Jumlah clip harus 1 - {SETTINGS.max_clips_per_video}.")
        return WAIT_CLIP_COUNT
    session["clip_count"] = clip_count
    keyboard = [["15", "30", "45", "60"], ["Custom"]]
    await update.message.reply_text(
        "Durasi maksimal tiap clip (detik)?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return WAIT_DURATION


async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip().lower()
    if text == "custom":
        await update.message.reply_text("Masukkan durasi custom dalam detik (contoh: 25).")
        return WAIT_DURATION_CUSTOM
    if not text.isdigit():
        await update.message.reply_text("Pilih dari menu atau ketik angka.")
        return WAIT_DURATION
    session["max_duration"] = int(text)
    await update.message.reply_text(
        "Subtitle otomatis?",
        reply_markup=ReplyKeyboardMarkup([["Aktif", "Nonaktif"]], resize_keyboard=True),
    )
    return WAIT_SUBTITLE


async def receive_duration_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Durasi custom harus angka.")
        return WAIT_DURATION_CUSTOM
    val = int(text)
    if val < 5 or val > 120:
        await update.message.reply_text("Durasi custom harus di rentang 5-120 detik.")
        return WAIT_DURATION_CUSTOM
    session["max_duration"] = val
    await update.message.reply_text(
        "Subtitle otomatis?",
        reply_markup=ReplyKeyboardMarkup([["Aktif", "Nonaktif"]], resize_keyboard=True),
    )
    return WAIT_SUBTITLE


async def receive_subtitle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip().lower()
    if text not in {"aktif", "nonaktif"}:
        await update.message.reply_text("Pilih Aktif atau Nonaktif.")
        return WAIT_SUBTITLE
    session["subtitle_enabled"] = text == "aktif"
    await update.message.reply_text(
        "Tambahkan watermark?",
        reply_markup=ReplyKeyboardMarkup([["Ya", "Tidak"]], resize_keyboard=True),
    )
    return WAIT_WM_ENABLE


async def receive_wm_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip().lower()
    if text not in {"ya", "tidak"}:
        await update.message.reply_text("Pilih Ya atau Tidak.")
        return WAIT_WM_ENABLE
    enabled = text == "ya"
    session["watermark"]["enabled"] = enabled
    if not enabled:
        await update.message.reply_text(
            "Pilih kualitas output video.",
            reply_markup=ReplyKeyboardMarkup([["low", "medium", "high"]], resize_keyboard=True),
        )
        return WAIT_QUALITY
    await update.message.reply_text("Masukkan teks watermark. Contoh: @username")
    return WAIT_WM_TEXT


async def receive_wm_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Teks watermark tidak boleh kosong.")
        return WAIT_WM_TEXT
    session["watermark"]["text"] = text
    keyboard = [
        ["top-left", "top-center", "top-right"],
        ["center-left", "center", "center-right"],
        ["bottom-left", "bottom-center", "bottom-right"],
    ]
    await update.message.reply_text(
        "Pilih posisi watermark:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return WAIT_WM_POSITION


async def receive_wm_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    position = update.message.text.strip()
    valid = {
        "top-left",
        "top-center",
        "top-right",
        "center-left",
        "center",
        "center-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
    if position not in valid:
        await update.message.reply_text("Posisi tidak valid. Pilih dari menu.")
        return WAIT_WM_POSITION
    session["watermark"]["position"] = position
    await update.message.reply_text(
        "Pilih opacity watermark.",
        reply_markup=ReplyKeyboardMarkup([["0.2", "0.35", "0.5", "0.7"], ["Custom"]], resize_keyboard=True),
    )
    return WAIT_WM_OPACITY


async def receive_wm_opacity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip().lower()
    if text == "custom":
        await update.message.reply_text("Masukkan opacity custom (contoh: 0.42).")
        return WAIT_WM_OPACITY_CUSTOM
    try:
        opacity = float(text)
    except ValueError:
        await update.message.reply_text("Opacity tidak valid.")
        return WAIT_WM_OPACITY
    if opacity < 0.05 or opacity > 1.0:
        await update.message.reply_text("Opacity harus antara 0.05 sampai 1.0.")
        return WAIT_WM_OPACITY
    session["watermark"]["opacity"] = opacity
    await update.message.reply_text(
        "Pilih ukuran font watermark.",
        reply_markup=ReplyKeyboardMarkup([["20", "24", "28", "32", "40"], ["Custom"]], resize_keyboard=True),
    )
    return WAIT_WM_FONT


async def receive_wm_opacity_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    try:
        opacity = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Opacity custom tidak valid.")
        return WAIT_WM_OPACITY_CUSTOM
    if opacity < 0.05 or opacity > 1.0:
        await update.message.reply_text("Opacity custom harus 0.05 - 1.0.")
        return WAIT_WM_OPACITY_CUSTOM
    session["watermark"]["opacity"] = opacity
    await update.message.reply_text(
        "Pilih ukuran font watermark.",
        reply_markup=ReplyKeyboardMarkup([["20", "24", "28", "32", "40"], ["Custom"]], resize_keyboard=True),
    )
    return WAIT_WM_FONT


async def receive_wm_font(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip().lower()
    if text == "custom":
        await update.message.reply_text("Masukkan ukuran font custom (contoh: 26).")
        return WAIT_WM_FONT_CUSTOM
    if not text.isdigit():
        await update.message.reply_text("Ukuran font tidak valid.")
        return WAIT_WM_FONT
    font_size = int(text)
    if font_size < 12 or font_size > 96:
        await update.message.reply_text("Ukuran font harus 12-96.")
        return WAIT_WM_FONT
    session["watermark"]["font_size"] = font_size
    await update.message.reply_text(
        "Pilih kualitas output video.",
        reply_markup=ReplyKeyboardMarkup([["low", "medium", "high"]], resize_keyboard=True),
    )
    return WAIT_QUALITY


async def receive_wm_font_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Ukuran font custom harus angka.")
        return WAIT_WM_FONT_CUSTOM
    font_size = int(text)
    if font_size < 12 or font_size > 96:
        await update.message.reply_text("Ukuran font custom harus 12-96.")
        return WAIT_WM_FONT_CUSTOM
    session["watermark"]["font_size"] = font_size
    await update.message.reply_text(
        "Pilih kualitas output video.",
        reply_markup=ReplyKeyboardMarkup([["low", "medium", "high"]], resize_keyboard=True),
    )
    return WAIT_QUALITY


async def receive_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = _get_session(context)
    quality = update.message.text.strip().lower()
    if quality not in {"low", "medium", "high"}:
        await update.message.reply_text("Kualitas harus low, medium, atau high.")
        return WAIT_QUALITY
    session["quality"] = quality
    wm_status = "aktif" if session["watermark"]["enabled"] else "nonaktif"
    subtitle = "aktif" if session["subtitle_enabled"] else "nonaktif"
    await update.message.reply_text(
        "\n".join(
            [
                "Konfirmasi proses:",
                f"- Jumlah clip: {session['clip_count']}",
                f"- Durasi max: {session['max_duration']} detik",
                f"- Subtitle: {subtitle}",
                f"- Watermark: {wm_status}",
                f"- Kualitas: {session['quality']}",
                "Balas: Mulai atau Batal",
            ]
        ),
        reply_markup=ReplyKeyboardMarkup([["Mulai", "Batal"]], resize_keyboard=True),
    )
    return WAIT_CONFIRM


async def receive_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "batal":
        await update.message.reply_text("Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if text != "mulai":
        await update.message.reply_text("Pilih Mulai atau Batal.")
        return WAIT_CONFIRM

    chat_id = update.effective_chat.id
    active = RUNNING_JOBS.get(chat_id)
    if active and not active.done():
        await update.message.reply_text("Masih ada proses aktif. Tunggu selesai atau gunakan /cancel.")
        return ConversationHandler.END

    session = dict(_get_session(context))
    await update.message.reply_text("Proses dimulai. Bot akan kirim progres tahap demi tahap.")
    task = asyncio.create_task(_run_pipeline(chat_id, session, context))
    RUNNING_JOBS[chat_id] = task
    return ConversationHandler.END


async def _status(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    await context.bot.send_message(chat_id=chat_id, text=text)


async def _run_pipeline(chat_id: int, session: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE) -> None:
    if PROCESS_SEMAPHORE.locked():
        await _status(context, chat_id, "Server sedang sibuk. Request kamu masuk antrian...")

    async with PROCESS_SEMAPHORE:
        await _run_pipeline_internal(chat_id, session, context)


async def _run_pipeline_internal(chat_id: int, session: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE) -> None:
    job_dir = SETTINGS.temp_dir / build_unique_name(f"job_{chat_id}", "dir")
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir = SETTINGS.output_dir / f"chat_{chat_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not ensure_disk_space(SETTINGS.temp_dir, min_free_mb=500):
            raise RuntimeError("Storage VPS hampir habis. Minimal 500MB ruang kosong dibutuhkan.")

        await _status(context, chat_id, "Link diterima, sedang validasi...")
        info = await asyncio.to_thread(fetch_video_info, session["youtube_url"], LOGGER)
        duration = int(info.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError("Durasi video tidak terbaca.")
        max_seconds = SETTINGS.max_video_duration_minutes * 60
        if duration > max_seconds:
            raise RuntimeError(
                f"Video terlalu panjang ({duration}s). Batas maksimal {SETTINGS.max_video_duration_minutes} menit."
            )

        await _status(context, chat_id, "Video sedang didownload...")
        video_path = await asyncio.to_thread(download_video, session["youtube_url"], job_dir, LOGGER)

        await _status(context, chat_id, "Audio sedang diekstrak...")
        audio_path = job_dir / "audio.wav"
        await asyncio.to_thread(extract_audio, video_path, audio_path, LOGGER)

        await _status(context, chat_id, "Audio sedang ditranskrip dengan WhisperX...")
        transcript = await asyncio.to_thread(
            transcribe_audio,
            audio_path,
            SETTINGS.whisperx_model,
            SETTINGS.whisperx_device,
            SETTINGS.whisperx_compute_type,
            LOGGER,
        )
        if not transcript.get("segments"):
            raise RuntimeError("Tidak ada segmen transkrip. Audio mungkin tidak jelas atau kosong.")

        await _status(context, chat_id, "AI sedang menganalisis momen viral...")
        visual_summary = await asyncio.to_thread(summarize_visual_activity, video_path, LOGGER)
        analysis = await asyncio.to_thread(
            analyze_moments,
            SETTINGS.gemini_api_keys,
            SETTINGS.gemini_model,
            transcript["segments"],
            duration,
            session["clip_count"],
            session["max_duration"],
            visual_summary,
            LOGGER,
        )

        clips = rank_and_filter_clips(analysis, session["clip_count"], session["max_duration"])
        if not clips:
            raise RuntimeError("AI tidak menemukan momen yang layak dipotong.")
        await _status(context, chat_id, "Momen terbaik ditemukan...")

        probe = await asyncio.to_thread(get_video_probe, video_path, LOGGER)
        source_w = probe["width"]
        source_h = probe["height"]

        for idx, clip in enumerate(clips, start=1):
            await _status(context, chat_id, f"Video clip {idx} sedang diproses...")
            start_s = float(clip["start_seconds"])
            end_s = float(clip["end_seconds"])

            await _status(context, chat_id, f"Video {idx} sedang diubah ke rasio 9:16...")
            focus_x = await asyncio.to_thread(estimate_focus_x, video_path, start_s, end_s, LOGGER)

            subtitle_path = None
            if session["subtitle_enabled"]:
                await _status(context, chat_id, f"Subtitle clip {idx} sedang dibuat...")
                subtitle_path = job_dir / f"clip_{idx:02d}.srt"
                await asyncio.to_thread(
                    build_srt_for_clip,
                    transcript["segments"],
                    start_s,
                    end_s,
                    subtitle_path,
                )

            await _status(context, chat_id, f"Rendering clip {idx}...")
            out_path = out_dir / f"clip_{idx:02d}.mp4"
            await asyncio.to_thread(
                render_vertical_clip,
                video_path,
                out_path,
                start_s,
                end_s,
                source_w,
                source_h,
                focus_x,
                session["quality"],
                subtitle_path,
                session["watermark"],
                LOGGER,
            )

            caption, hashtags = normalize_caption_and_hashtags(clip)
            detail = "\n".join(
                [
                    f"Clip {idx} selesai.",
                    "",
                    "Timestamp sumber:",
                    f"{clip.get('start_time')} - {clip.get('end_time')}",
                    "",
                    f"Viral Score: {clip.get('viral_score', 0)}/100",
                    f"Alasan: {clip.get('reason', '-')}",
                    "",
                    f"Caption: {caption}",
                    "Hashtag:",
                    " ".join(hashtags),
                ]
            )

            max_bytes = SETTINGS.telegram_max_file_size_mb * 1024 * 1024
            if out_path.stat().st_size > max_bytes:
                await _status(
                    context,
                    chat_id,
                    f"Clip {idx} melebihi batas ukuran Telegram ({SETTINGS.telegram_max_file_size_mb}MB).",
                )
                continue

            await _status(context, chat_id, f"Mengirim hasil clip {idx} ke Telegram...")
            with out_path.open("rb") as f:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=detail)

            if SETTINGS.auto_delete_output_after_send:
                try:
                    out_path.unlink()
                except Exception:
                    pass

        await _status(context, chat_id, "Semua clip selesai diproses.")
    except asyncio.CancelledError:
        await _status(context, chat_id, "Proses dihentikan oleh user.")
    except Exception as exc:
        LOGGER.exception("Pipeline failed for chat_id=%s", chat_id)
        await _status(context, chat_id, f"Terjadi error: {exc}")
    finally:
        RUNNING_JOBS.pop(chat_id, None)
        if SETTINGS.auto_delete_temp_files:
            safe_rmtree(job_dir)


def run_bot() -> None:
    global SETTINGS
    global LOGGER
    SETTINGS = Settings.from_env()
    LOGGER = setup_logging(SETTINGS.log_dir)
    global PROCESS_SEMAPHORE
    PROCESS_SEMAPHORE = asyncio.Semaphore(SETTINGS.max_concurrent_jobs)
    LOGGER.info("Starting Auto YouTube Clipper Bot")
    LOGGER.info(
        "Gemini keys loaded: %s | max_concurrent_jobs=%s",
        len(SETTINGS.gemini_api_keys),
        SETTINGS.max_concurrent_jobs,
    )

    app = Application.builder().token(SETTINGS.telegram_bot_token).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(YOUTUBE_LINK_PATTERN) & ~filters.COMMAND, start_from_link),
        ],
        states={
            WAIT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAIT_CLIP_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_clip_count)],
            WAIT_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration)],
            WAIT_DURATION_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration_custom)],
            WAIT_SUBTITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_subtitle)],
            WAIT_WM_ENABLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_enable)],
            WAIT_WM_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_text)],
            WAIT_WM_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_position)],
            WAIT_WM_OPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_opacity)],
            WAIT_WM_OPACITY_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_opacity_custom)],
            WAIT_WM_FONT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_font)],
            WAIT_WM_FONT_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wm_font_custom)],
            WAIT_QUALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quality)],
            WAIT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("cancel", cancel))

    app.run_polling(close_loop=False)
