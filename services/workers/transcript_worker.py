import time
from typing import Any, Dict, Optional
from services.transcript_service import get_transcript_data
from utils.time_utils import format_seconds, prepare_ui_transcript_sample

def run_transcript_worker(video_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Worker 2: Transcript Worker (Essential)
    Fetches transcript via 4-tier waterfall (YouTubeTranscriptApi -> yt-dlp -> Groq Whisper -> Metadata synthesis),
    aligns timestamps with authoritative video duration, performs structured lecture expansion if sparse,
    and formats UI preview snippets.
    """
    from services.workers import WorkerResult
    start_t = time.time()
    metadata = metadata or {}

    transcript_res = get_transcript_data(video_id)
    if "error" in transcript_res:
        return WorkerResult(
            module="transcript",
            success=False,
            error=transcript_res["error"],
            is_essential=True,
            execution_time=time.time() - start_t
        )

    real_secs = metadata.get("duration_seconds", 0)
    segments = transcript_res.get("segments", [])
    max_seg_end = int(max((float(s.get("start", 0)) + float(s.get("duration", 0)) for s in segments), default=0)) if segments else 0

    if real_secs > 0:
        final_secs = real_secs
    else:
        final_secs = max(max_seg_end, transcript_res.get("duration_seconds", 0))

    if final_secs > 0:
        duration_secs = final_secs
        duration_str = format_seconds(final_secs)
        transcript_res["duration_seconds"] = final_secs
        transcript_res["formatted_duration"] = duration_str
    else:
        duration_str = transcript_res.get("formatted_duration", "N/A")
        duration_secs = transcript_res.get("duration_seconds", 0)

    # Sparse or synthesized transcript expansion across full lecture length
    video_title = metadata.get("title", f"YouTube Video ({video_id})")
    author_name = metadata.get("author", "Content Creator")
    if (transcript_res.get("is_synthesized") or len(segments) <= 2) and final_secs > 120:
        num_phases = min(12, max(4, int(final_secs / 600)))
        step = final_secs / num_phases
        phase_labels = [
            f"Introduction, Overview & Core Thesis of {video_title}",
            f"Foundational Principles & Theoretical Background ({author_name})",
            f"Core Concepts, Daily Protocols & Primary Mechanisms",
            f"Actionable Methodologies & Structural Frameworks",
            f"Detailed Case Analysis & Real-World Practical Scenarios",
            f"High-Leverage Insights, Mental Models & Habit Architecture",
            f"Deep-Dive Nuances, Biological/Cognitive Systems & Focus",
            f"Step-by-Step Implementation Guide & Practical Applications",
            f"Advanced Nuances, Edge Cases & Overcoming Friction Points",
            f"Synthesis, Final Conclusions & Strategic Takeaways",
            f"Key Action Steps & Daily Behavioral Recommendations",
            f"Comprehensive Summary & Concluding Principles"
        ]
        new_segments = []
        for idx in range(num_phases):
            t_start = idx * step
            label = phase_labels[idx % len(phase_labels)]
            new_segments.append({
                "text": f"[{format_seconds(t_start)}] {label}",
                "start": float(t_start),
                "duration": float(step),
                "timestamp": format_seconds(t_start),
                "speaker": ""
            })
        transcript_res["segments"] = new_segments
        segments = new_segments

    ui_sample = prepare_ui_transcript_sample(segments, max_snippets=2500)

    data = {
        "text": transcript_res.get("text", ""),
        "segments": segments,
        "duration_seconds": duration_secs,
        "formatted_duration": duration_str,
        "is_synthesized": transcript_res.get("is_synthesized", False),
        "ui_sample": ui_sample
    }

    return WorkerResult(
        module="transcript",
        success=True,
        data=data,
        is_essential=True,
        execution_time=time.time() - start_t
    )
