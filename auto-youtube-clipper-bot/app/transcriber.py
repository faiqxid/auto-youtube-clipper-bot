import logging
from pathlib import Path
from typing import Dict, List

import whisperx


def _normalize_segments(segments: List[Dict]) -> List[Dict]:
    normalized = []
    for s in segments:
        normalized.append(
            {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")).strip(),
                "words": s.get("words", []),
            }
        )
    return normalized


def transcribe_audio(
    audio_path: Path,
    model_name: str,
    device: str,
    compute_type: str,
    logger: logging.Logger,
) -> Dict:
    logger.info("Loading WhisperX model=%s device=%s", model_name, device)
    model = whisperx.load_model(model_name, device=device, compute_type=compute_type)
    result = model.transcribe(str(audio_path), batch_size=16)

    language = result.get("language")
    logger.info("WhisperX language detected: %s", language)

    segments = result.get("segments", [])
    if language:
        try:
            align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
            aligned = whisperx.align(
                segments,
                align_model,
                metadata,
                str(audio_path),
                device,
                return_char_alignments=False,
            )
            segments = aligned.get("segments", segments)
        except Exception as exc:
            logger.warning("WhisperX alignment failed, continue without alignment: %s", exc)

    return {
        "language": language or "unknown",
        "segments": _normalize_segments(segments),
        "text": " ".join([s.get("text", "") for s in segments]).strip(),
    }
