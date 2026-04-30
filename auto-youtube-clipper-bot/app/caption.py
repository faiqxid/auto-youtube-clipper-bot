from typing import Dict, List, Tuple


def normalize_caption_and_hashtags(clip: Dict) -> Tuple[str, List[str]]:
    caption = str(clip.get("caption_id", "")).strip()
    hashtags = clip.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []
    tags = []
    for tag in hashtags:
        t = str(tag).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t.replace(" ", "")
        tags.append(t)
    if not caption:
        caption = "Bagian ini menarik banget. Kamu setuju?"
    if not tags:
        tags = ["#ShortsIndonesia", "#KontenIndonesia", "#FYP", "#VideoViral", "#ReelsIndonesia"]
    return caption, tags[:12]
