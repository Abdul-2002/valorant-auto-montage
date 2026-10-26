from __future__ import annotations

from src.youtube.errors import YouTubeUploadError

_PRIVACY = frozenset({"private", "unlisted", "public"})


def clean_metadata(
    *,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    category_id: str,
) -> dict[str, object]:
    cleaned_title = " ".join(title.split())
    if not cleaned_title:
        raise YouTubeUploadError("title is required")
    if len(cleaned_title) > 100:
        raise YouTubeUploadError("title must be 100 characters or fewer")
    cleaned_description = description.replace("\x00", "").strip()
    if len(cleaned_description) > 5000:
        raise YouTubeUploadError("description must be 5000 characters or fewer")
    privacy = privacy_status.strip().lower()
    if privacy not in _PRIVACY:
        raise YouTubeUploadError("privacy_status must be private, unlisted, or public")
    category = category_id.strip()
    if not category.isdigit():
        raise YouTubeUploadError("category_id must be a YouTube category number")
    return {
        "title": cleaned_title,
        "description": cleaned_description,
        "tags": _clean_tags(tags),
        "privacy_status": privacy,
        "category_id": category,
    }


def video_body(meta: dict[str, object]) -> dict[str, object]:
    return {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": meta["category_id"],
        },
        "status": {
            "privacyStatus": meta["privacy_status"],
            "selfDeclaredMadeForKids": False,
        },
    }


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        item = " ".join(str(raw).split())
        if not item or item.casefold() in seen:
            continue
        if len(item) > 30:
            raise YouTubeUploadError("each tag must be 30 characters or fewer")
        seen.add(item.casefold())
        cleaned.append(item)
    if len(",".join(cleaned)) > 500:
        raise YouTubeUploadError("tags exceed YouTube's 500 character limit")
    return cleaned
