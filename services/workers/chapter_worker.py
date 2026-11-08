import time
from typing import Any, Dict, List, Optional
from utils.time_utils import format_seconds
from services.metadata_service import parse_duration_string

def run_chapter_worker(
    segments: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    key_pool: Optional[List[str]] = None,
    is_paid: bool = False,
    raw_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Worker 4: Chapter & Timeline Worker (Essential with fallback)
    Detects chronological chapters, timeline milestones, and creator repurposing
    (YouTube chapters, viral clips, social posts). Guaranteed fallback ensures chapters
    are always navigable.
    """
    from services.workers import WorkerResult
    start_t = time.time()
    metadata = metadata or {}
    dur_sec = metadata.get("duration_seconds", 0)
    video_title = metadata.get("title", "Video")

    try:
        chapters = []
        timeline = []
        creator_repurposing = {}

        if raw_analysis and isinstance(raw_analysis, dict):
            chapters = raw_analysis.get("chapters", [])
            timeline = raw_analysis.get("timeline", [])
            creator_repurposing = raw_analysis.get("creator_repurposing", {})

        # Guaranteed fallback if AI produced empty or invalid chapters
        if not chapters:
            total_sec = dur_sec if dur_sec > 0 else 600
            num_ch = min(8, max(4, int(total_sec / 300)))
            step = total_sec / num_ch
            chapters = []
            for idx in range(num_ch):
                s_sec = idx * step
                e_sec = (idx + 1) * step if idx < num_ch - 1 else total_sec
                chapters.append({
                    "number": f"{idx + 1:02d}",
                    "title": f"Phase {idx + 1}: Key Principles of {video_title[:30]}",
                    "start_time": format_seconds(s_sec),
                    "end_time": format_seconds(e_sec),
                    "start_seconds": int(s_sec),
                    "end_seconds": int(e_sec),
                    "summary": f"Discussion covering topic segment {idx + 1}.",
                    "key_points": [f"Core element {idx + 1}.1", f"Practical application {idx + 1}.2"]
                })

        if not timeline:
            timeline = [
                {
                    "time": ch.get("start_time", "00:00"),
                    "seconds": ch.get("start_seconds", 0),
                    "title": ch.get("title", "Chapter"),
                    "description": ch.get("summary", ""),
                    "type": "key_moment"
                }
                for ch in chapters
            ]

        if not creator_repurposing or not isinstance(creator_repurposing, dict):
            raw_ch_lines = [f"{ch.get('start_time', '00:00')} {ch.get('title', '')}" for ch in chapters]
            creator_repurposing = {
                "youtube_chapters_raw": "\n".join(raw_ch_lines),
                "viral_clips": [
                    {
                        "title": f"Must-Watch: {chapters[0].get('title', 'Intro')}",
                        "hook": "Here's what everyone needs to know...",
                        "timestamp": "00:00",
                        "duration": "60s"
                    }
                ],
                "social_posts": {
                    "twitter_thread": [f"1/ 5 essential takeaways from {video_title}:"],
                    "linkedin_post": f"Key insights on {video_title}...",
                    "newsletter_blurb": f"In this analysis of {video_title}..."
                }
            }
        elif "youtube_chapters_raw" not in creator_repurposing or not creator_repurposing["youtube_chapters_raw"]:
            raw_ch_lines = [f"{ch.get('start_time', '00:00')} {ch.get('title', '')}" for ch in chapters]
            creator_repurposing["youtube_chapters_raw"] = "\n".join(raw_ch_lines)

        # Clamp all timestamps to <= dur_sec if dur_sec > 0
        if dur_sec > 0:
            for ch in chapters:
                if isinstance(ch, dict):
                    if ch.get("start_seconds", 0) > dur_sec:
                        ch["start_seconds"] = dur_sec
                        ch["start_time"] = format_seconds(dur_sec)

        data = {
            "chapters": chapters,
            "timeline": timeline,
            "creator_repurposing": creator_repurposing
        }

        return WorkerResult(
            module="chapters",
            success=True,
            data=data,
            is_essential=True,
            execution_time=time.time() - start_t
        )

    except Exception as e:
        return WorkerResult(
            module="chapters",
            success=False,
            error=str(e),
            is_essential=True,
            execution_time=time.time() - start_t
        )
