import json
import logging
import time
from typing import Any, Dict, List

import google.generativeai as genai

from app.utils import seconds_to_hhmmss


PROMPT_TEMPLATE = """Kamu adalah AI editor short video profesional.
Tugas: pilih momen video paling berpotensi viral untuk format 9:16 (TikTok/Reels/Shorts).

Aturan ketat:
1) Kembalikan HANYA JSON valid.
2) Jangan markdown, jangan teks tambahan.
3) Jangan pilih bagian intro/outro yang datar.
4) Hindari overlap berlebihan antar clip.
5) Utamakan clip yang tetap jelas konteksnya saat dipotong.
6) Caption wajib bahasa Indonesia.
7) Hashtag relevan 5-12 item.
8) Format waktu HH:MM:SS.

Input:
- video_duration_seconds: {video_duration_seconds}
- requested_clips: {requested_clips}
- max_clip_duration_seconds: {max_clip_duration_seconds}
- visual_activity_summary: {visual_activity_summary}
- transcript_with_timestamp:
{transcript_with_timestamp}

Skema output JSON:
{{
  "clips": [
    {{
      "start_time": "00:03:12",
      "end_time": "00:03:42",
      "title": "Momen paling menarik ...",
      "viral_score": 87,
      "reason": "Alasan singkat kenapa dipilih.",
      "hook_text": "Kalimat pembuka paling kuat.",
      "caption_id": "Caption bahasa Indonesia yang natural.",
      "hashtags": ["#FYP", "#ShortsIndonesia"],
      "subtitle_focus_keywords": ["kata kunci 1", "kata kunci 2"],
      "component_scores": {{
        "hook_score": 0,
        "emotion_score": 0,
        "surprise_score": 0,
        "information_value_score": 0,
        "visual_activity_score": 0,
        "speech_energy_score": 0,
        "caption_potential_score": 0,
        "short_video_fit_score": 0,
        "context_clarity_score": 0
      }}
    }}
  ]
}}
"""


def _build_transcript_snippet(segments: List[Dict[str, Any]], limit: int = 400) -> str:
    lines = []
    for i, s in enumerate(segments):
        if i >= limit:
            break
        lines.append(
            f"[{seconds_to_hhmmss(s['start'])} - {seconds_to_hhmmss(s['end'])}] {s['text']}"
        )
    return "\n".join(lines)


def _strip_json_text(payload: str) -> str:
    text = payload.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "", 1)
    text = text.strip()
    left = text.find("{")
    right = text.rfind("}")
    if left != -1 and right != -1 and right > left:
        return text[left : right + 1]
    return text


def _validate_output(data: Dict[str, Any]) -> Dict[str, Any]:
    clips = data.get("clips")
    if not isinstance(clips, list):
        raise ValueError("Gemini output tidak memiliki field clips list")
    return data


def _build_models_to_try(primary: str, fallbacks: List[str]) -> List[str]:
    ordered = [primary] + list(fallbacks or [])
    out = []
    seen = set()
    for name in ordered:
        n = str(name).strip()
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _is_model_not_found(err_text: str) -> bool:
    text = err_text.lower()
    return "is not found for api version" in text or "models/" in text and "not found" in text


def _compact_errors(errors: List[str], limit: int = 8) -> str:
    if not errors:
        return "-"
    head = errors[:limit]
    rest = len(errors) - len(head)
    if rest > 0:
        head.append(f"(+{rest} error lain)")
    return " | ".join(head)


def analyze_moments(
    gemini_api_keys: List[str],
    gemini_model: str,
    gemini_model_fallbacks: List[str],
    transcript_segments: List[Dict[str, Any]],
    video_duration_seconds: int,
    requested_clips: int,
    max_clip_duration_seconds: int,
    visual_activity_summary: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, Any]:
    prompt = PROMPT_TEMPLATE.format(
        video_duration_seconds=video_duration_seconds,
        requested_clips=requested_clips,
        max_clip_duration_seconds=max_clip_duration_seconds,
        visual_activity_summary=json.dumps(visual_activity_summary, ensure_ascii=False),
        transcript_with_timestamp=_build_transcript_snippet(transcript_segments),
    )

    if not gemini_api_keys:
        raise RuntimeError("Tidak ada Gemini API key yang tersedia.")

    models_to_try = _build_models_to_try(gemini_model, gemini_model_fallbacks)
    errors = []
    for model_name in models_to_try:
        model_not_found = False
        for idx, key in enumerate(gemini_api_keys, start=1):
            try:
                logger.info("Sending transcript to Gemini model=%s key_index=%s", model_name, idx)
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.3},
                )
                text = getattr(response, "text", "") or ""
                text = _strip_json_text(text)
                data = json.loads(text)
                return _validate_output(data)
            except Exception as exc:
                msg = str(exc)
                if _is_model_not_found(msg):
                    model_not_found = True
                    logger.warning("Gemini model tidak tersedia: model=%s", model_name)
                    errors.append(f"model={model_name}: not_found")
                    break
                errors.append(f"model={model_name},key-{idx}: {msg}")
                logger.warning("Gemini model=%s key-%s failed: %s", model_name, idx, exc)
                time.sleep(0.4)
                continue
        if model_not_found:
            continue

    raise RuntimeError("Semua Gemini model/key gagal. Detail: " + _compact_errors(errors))
