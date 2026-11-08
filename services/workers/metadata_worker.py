import time
from typing import Any, Dict
from services.metadata_service import extract_video_id, get_video_oembed, get_video_duration_seconds
from utils.time_utils import format_seconds

def run_metadata_worker(url_or_video_id: str) -> Dict[str, Any]:
    """
    Worker 1: Metadata Worker (Essential)
    Validates URL, extracts canonical 11-char video_id, queries oEmbed metadata,
    and resolves authoritative video duration.
    """
    from services.workers import WorkerResult
    start_t = time.time()
    
    if not url_or_video_id or not isinstance(url_or_video_id, str):
        return WorkerResult(
            module="metadata",
            success=False,
            error="Please enter a valid YouTube video link.",
            is_essential=True,
            execution_time=time.time() - start_t
        )

    vid = extract_video_id(url_or_video_id.strip())
    if not vid or len(vid) != 11:
        return WorkerResult(
            module="metadata",
            success=False,
            error="Invalid YouTube URL",
            is_essential=True,
            execution_time=time.time() - start_t
        )

    try:
        meta_info = get_video_oembed(vid) or {}
    except Exception as e:
        meta_info = {
            "title": f"YouTube Video ({vid})",
            "author_name": "YouTube Creator",
            "thumbnail_url": f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        }

    title = meta_info.get("title") or f"YouTube Video ({vid})"
    author = meta_info.get("author_name") or "YouTube Creator"
    thumbnail_url = meta_info.get("thumbnail_url") or f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"

    dur_sec = 0
    try:
        dur_sec = get_video_duration_seconds(vid)
    except Exception:
        dur_sec = 0

    dur_str = format_seconds(dur_sec) if dur_sec > 0 else "N/A"

    data = {
        "video_id": vid,
        "video_url": f"https://www.youtube.com/watch?v={vid}",
        "title": title,
        "author": author,
        "thumbnail_url": thumbnail_url,
        "duration_seconds": dur_sec,
        "duration": dur_str
    }

    return WorkerResult(
        module="metadata",
        success=True,
        data=data,
        is_essential=True,
        execution_time=time.time() - start_t
    )
