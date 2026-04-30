from typing import Any, Dict, List, Tuple

from app.utils import parse_time_to_seconds


def _overlap_ratio(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    if end <= start:
        return 0.0
    overlap = end - start
    shorter = min(a[1] - a[0], b[1] - b[0])
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def _local_bonus(clip: Dict[str, Any]) -> int:
    comp = clip.get("component_scores", {}) or {}
    keys = [
        "hook_score",
        "emotion_score",
        "surprise_score",
        "information_value_score",
        "visual_activity_score",
        "speech_energy_score",
        "caption_potential_score",
        "short_video_fit_score",
        "context_clarity_score",
    ]
    vals = [int(comp.get(k, 0)) for k in keys]
    if not vals:
        return 0
    return int(sum(vals) / len(vals))


def rank_and_filter_clips(
    candidate_payload: Dict[str, Any],
    requested_clips: int,
    max_duration_seconds: int,
) -> List[Dict[str, Any]]:
    clips = candidate_payload.get("clips", [])
    enriched: List[Dict[str, Any]] = []

    for item in clips:
        start = parse_time_to_seconds(item["start_time"])
        end = parse_time_to_seconds(item["end_time"])
        if end <= start:
            continue
        if end - start > max_duration_seconds:
            end = start + max_duration_seconds
        base_score = int(item.get("viral_score", 0))
        total_score = int((base_score * 0.7) + (_local_bonus(item) * 0.3))
        item["_start"] = start
        item["_end"] = end
        item["_total_score"] = max(0, min(total_score, 100))
        enriched.append(item)

    enriched.sort(key=lambda x: x["_total_score"], reverse=True)

    selected: List[Dict[str, Any]] = []
    for clip in enriched:
        keep = True
        for chosen in selected:
            ov = _overlap_ratio((clip["_start"], clip["_end"]), (chosen["_start"], chosen["_end"]))
            if ov > 0.45:
                keep = False
                break
        if keep:
            selected.append(clip)
        if len(selected) >= requested_clips:
            break

    for idx, clip in enumerate(selected, start=1):
        clip["rank"] = idx
        clip["viral_score"] = clip["_total_score"]
        clip["start_seconds"] = clip["_start"]
        clip["end_seconds"] = clip["_end"]

    return selected
