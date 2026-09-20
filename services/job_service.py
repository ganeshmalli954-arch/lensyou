import uuid
import threading
import time
from datetime import datetime
from services.metadata_service import get_video_oembed
from services.transcript_service import get_transcript_data
from services.analysis_service import run_videolens_analysis
from services.storage_service import (
    save_analysis, log_event, record_search_event,
    record_processing_event, update_processing_event, get_user,
    update_search_events_for_content
)
from services.auth_service import increment_quota, is_owner

JOBS = {}  # {job_id: {status, stage, stage_name, result, error, started_at}}

STAGES = [
    (1, 'Fetching metadata'),
    (2, 'Resolving transcript'),
    (3, 'Normalizing timestamps'),
    (4, 'Building temporal model'),
    (5, 'Generating core intelligence'),
    (6, 'Generating research insights'),
    (7, 'Generating learning material'),
    (8, 'Building knowledge graph'),
    (9, 'Preparing dashboard'),
]

def create_job() -> str:
    job_id = str(uuid.uuid4())[:12]
    JOBS[job_id] = {
        'status': 'queued',
        'stage': 0,
        'stage_name': 'Queued',
        'result': None,
        'error': None,
        'started_at': datetime.utcnow().isoformat()
    }
    return job_id

def get_job(job_id) -> dict | None:
    return JOBS.get(job_id)

def update_job_stage(job_id, stage_num):
    if job_id in JOBS:
        JOBS[job_id]['stage'] = stage_num
        stage_name = f"Stage {stage_num}"
        for s_num, s_name in STAGES:
            if s_num == stage_num:
                stage_name = s_name
                break
        JOBS[job_id]['stage_name'] = stage_name

def complete_job(job_id, result):
    if job_id in JOBS:
        JOBS[job_id]['status'] = 'completed'
        JOBS[job_id]['result'] = result
        title = (result.get('_meta', {}) or {}).get('title', job_id)
        log_event('INFO', f"Analysis job {job_id} completed successfully for '{title}'", source='analysis')

def format_user_error(error) -> str:
    err_str = str(error)
    if '503' in err_str or 'UNAVAILABLE' in err_str or 'high demand' in err_str.lower():
        return "AI analysis engines are currently experiencing a temporary global demand spike. Please wait a few moments and click 'Try Again'."
    if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str or 'quota' in err_str.lower():
        return "API request limit reached. Please wait a moment and try again."
    if 'No transcript' in err_str or 'TranscriptsDisabled' in err_str or 'NoTranscriptFound' in err_str:
        return "Could not retrieve transcript or captions for this YouTube video. Subtitles may be disabled by the creator."
    if 'Invalid YouTube URL' in err_str:
        return "Please enter a valid YouTube video link."
    clean = err_str.split('\n')[0].strip()
    if 'google.genai' in clean or 'ServerError' in clean or 'ClientError' in clean:
        return "AI analysis encountered a temporary service issue. Please click 'Try Again'."
    return clean[:140]

def fail_job(job_id, error):
    if job_id in JOBS:
        JOBS[job_id]['status'] = 'error'
        raw_msg = str(error)
        JOBS[job_id]['error'] = format_user_error(error)
        log_event('ERROR', f"Analysis job {job_id} failed: {raw_msg[:120]}", source='analysis')

def run_analysis_job(job_id, video_id, user_id, session_key, key_pool):
    proc_event_id = None
    try:
        # Determine priority tier (Owner or Paid Plan)
        user = get_user(user_id) if user_id else None
        user_email = user.get("email") if user else ""
        user_plan = user.get("plan", "free") if user else "anonymous"
        is_paid = is_owner(user_email) or (user_plan in ["pack10", "pack50", "unlimited"])

        update_job_stage(job_id, 1)
        meta_info = get_video_oembed(video_id)
        video_title = meta_info.get("title", f"YouTube Video ({video_id})")
        author_name = meta_info.get("author_name", "YouTube Creator")
        thumbnail_url = meta_info.get("thumbnail_url", f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")

        # Update any search records for this video to the real title
        update_search_events_for_content(video_id, video_title)

        # Record processing event in database
        proc_event_id = record_processing_event(
            user_id=user_id,
            session_key=session_key,
            content_id=video_id,
            content_title=video_title,
            content_type="YouTube Video",
            status="pending",
            plan=user_plan
        )

        update_job_stage(job_id, 2)
        transcript_res = get_transcript_data(video_id)
        if "error" in transcript_res:
            err = transcript_res["error"]
            if proc_event_id:
                update_processing_event(proc_event_id, status="failed", error_info=str(err))
            fail_job(job_id, err)
            return

        # Determine the video's authoritative duration (supporting 1–4+ hour lectures)
        real_secs = 0
        try:
            from services.metadata_service import get_video_duration_seconds
            real_secs = get_video_duration_seconds(video_id)
        except Exception as e_dur:
            print(f"  [Duration check note]: {e_dur}", flush=True)

        from utils.time_utils import format_seconds
        segments = transcript_res.get("segments", [])
        max_seg_end = int(max((float(s.get("start", 0)) + float(s.get("duration", 0)) for s in segments), default=0)) if segments else 0
        
        # Select authoritative maximum length
        final_secs = max(real_secs, max_seg_end, transcript_res.get("duration_seconds", 0))
        if final_secs > 0:
            duration_secs = final_secs
            duration_str = format_seconds(final_secs)
            transcript_res["duration_seconds"] = final_secs
            transcript_res["formatted_duration"] = duration_str
        else:
            duration_str = transcript_res.get("formatted_duration", "N/A")
            duration_secs = transcript_res.get("duration_seconds", 0)

        # If transcript was synthesized or sparse, span the full true lecture duration
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
                    "timestamp": format_seconds(t_start)
                })
            transcript_res["segments"] = new_segments

        update_job_stage(job_id, 4)

        analysis = run_videolens_analysis(
            transcript_res["segments"],
            duration_str,
            video_title,
            author_name,
            key_pool,
            is_paid=is_paid
        )

        update_job_stage(job_id, 8)

        # Attach meta
        model_name = analysis.get("_model_used", "Gemini AI")
        analysis["_meta"] = {
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url": thumbnail_url,
            "author": author_name,
            "title": video_title,
            "duration": duration_str,
            "duration_seconds": transcript_res.get("duration_seconds", 0),
            "tier": "Premium Intelligence" if is_paid else "Standard Analysis",
            "model_used": model_name,
            "is_premium": is_paid
        }

        from utils.time_utils import prepare_ui_transcript_sample
        analysis["_transcript_sample"] = prepare_ui_transcript_sample(transcript_res["segments"], max_snippets=2500)

        update_job_stage(job_id, 9)
        save_analysis(video_id, video_title, author_name, duration_str, analysis, user_id, session_key)
        increment_quota(user_id, session_key)

        if proc_event_id:
            update_processing_event(proc_event_id, status="success", duration=duration_str, model_used=model_name)

        complete_job(job_id, analysis)

    except Exception as e:
        if proc_event_id:
            update_processing_event(proc_event_id, status="failed", error_info=str(e))
        fail_job(job_id, e)

def start_job(job_id, **kwargs):
    t = threading.Thread(target=run_analysis_job, args=(job_id, kwargs.get('video_id'), kwargs.get('user_id'), kwargs.get('session_key'), kwargs.get('key_pool')), daemon=True)
    t.start()
