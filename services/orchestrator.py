import time
import uuid
import threading
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, Any, Dict, Optional, Tuple, List

from services.storage_service import (
    create_analysis_job, update_job_status, get_analysis_job,
    save_analysis, save_analysis_modular, get_cached_analysis,
    log_event, record_processing_event, update_processing_event,
    update_search_events_for_content, get_db
)
from services.auth_service import increment_quota, get_user, is_owner
from services.analysis_service import run_videolens_analysis
from services.workers import (
    run_metadata_worker,
    run_transcript_worker,
    run_summary_worker,
    run_chapter_worker,
    run_claim_worker,
    run_learning_worker,
    run_entity_worker,
    run_export_worker,
)

logger = logging.getLogger("orchestrator")


class JobStatus(str):
    """
    String subclass supporting case-insensitive equality bridging
    uppercase SQLite states ('COMPLETED', 'QUEUED', 'PARTIAL', 'FAILED')
    and legacy lowercase assertions ('completed', 'queued', 'partial', 'error').
    """
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            s1 = self.lower()
            s2 = other.lower()
            if s1 == s2:
                return True
            if {s1, s2} in ({'error', 'failed'}, {'completed', 'success'}):
                return True
            return False
        return super().__eq__(other)

    def __hash__(self) -> int:
        s = self.lower()
        if s in ('error', 'failed'):
            return hash('error')
        return hash(s)


STATUS_QUEUED = JobStatus("queued")
STATUS_EXTRACTING = JobStatus("extracting")
STATUS_PROCESSING = JobStatus("processing")
STATUS_VALIDATING = JobStatus("validating")
STATUS_COMPLETED = JobStatus("completed")
STATUS_PARTIAL = JobStatus("partial")
STATUS_FAILED = JobStatus("error")

STAGES = [
    (1, 'Fetching metadata'),
    (2, 'Resolving transcript'),
    (3, 'Normalizing timestamps'),
    (4, 'Building temporal model'),
    (5, 'Generating core intelligence'),
    (6, 'Generating research insights'),
    (7, 'Generating learning material'),
    (8, 'Validating evidence & guardrails'),
    (9, 'Preparing dashboard'),
]


def format_user_error(error: Any) -> str:
    """Format technical exceptions into safe, user-friendly messages."""
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


class AsyncJobOrchestrator:
    """
    Event-driven asynchronous job orchestrator managing video intelligence pipelines.
    Provides persistent SQLite lifecycle tracking, task-level fault isolation,
    exponential backoff retries, thread-safe deduplication locking, and timeouts.
    """
    def __init__(self, max_job_workers: int = 4, max_task_workers: int = 8):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.active_jobs: Dict[str, str] = {}
        self.lock = threading.RLock()
        self.job_pool = ThreadPoolExecutor(max_workers=max_job_workers, thread_name_prefix="JobOrch")
        self.task_pool = ThreadPoolExecutor(max_workers=max_task_workers, thread_name_prefix="WorkerTask")

        # Configured timeouts (seconds)
        self.timeouts = {
            "metadata": 15,
            "transcript": 35,
            "summary": 45,
            "chapters": 30,
            "claims": 30,
            "learning": 35,
            "entities": 30,
            "export_pdf": 25,
            "overall": 180
        }

    def shutdown(self, wait: bool = False):
        """Cleanly shuts down orchestrator worker thread pools."""
        self.job_pool.shutdown(wait=wait)
        self.task_pool.shutdown(wait=wait)

    def create_job(self, video_id: str = "", user_id: Optional[str] = None, session_key: Optional[str] = None) -> str:
        """Creates a new analysis job in memory and persists to SQLite analysis_jobs table."""
        job_id = str(uuid.uuid4())[:12]
        now = datetime.utcnow().isoformat()
        job_data = {
            'id': job_id,
            'video_id': video_id,
            'status': STATUS_QUEUED,
            'stage': 0,
            'stage_name': 'Queued',
            'progress': 0,
            'result': None,
            'error': None,
            'modules': {},
            'is_partial': False,
            'retry_count': 0,
            'started_at': now,
            'created_at': now
        }
        with self.lock:
            self.jobs[job_id] = job_data
            if video_id:
                self.active_jobs[video_id] = job_id

        try:
            create_analysis_job(job_id, video_id=video_id, user_id=user_id, session_key=session_key)
        except Exception as e:
            logger.warning(f"Failed to persist initial job {job_id} to SQLite: {e}")

        return job_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves job state from in-memory dictionary or hydrates from SQLite."""
        with self.lock:
            if job_id in self.jobs:
                return self.jobs[job_id]

        # Hydrate from SQLite if present
        db_job = get_analysis_job(job_id)
        if db_job:
            status_str = db_job.get('status', 'QUEUED')
            if status_str == 'COMPLETED':
                compat_status = STATUS_COMPLETED
            elif status_str == 'PARTIAL':
                compat_status = STATUS_PARTIAL
            elif status_str in ('FAILED', 'ERROR'):
                compat_status = STATUS_FAILED
            else:
                compat_status = JobStatus(status_str.lower())

            hydrated = {
                'id': db_job['id'],
                'video_id': db_job.get('video_id', ''),
                'status': compat_status,
                'stage': db_job.get('stage', 0),
                'stage_name': db_job.get('stage_name', ''),
                'progress': db_job.get('progress', 0),
                'result': db_job.get('result_summary'),
                'error': db_job.get('error'),
                'modules': {},
                'is_partial': status_str == 'PARTIAL',
                'retry_count': db_job.get('retry_count', 0),
                'started_at': db_job.get('created_at'),
                'created_at': db_job.get('created_at')
            }
            with self.lock:
                self.jobs[job_id] = hydrated
            return hydrated

        return None

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Convenience alias for get_job to retrieve job status and state."""
        return self.get_job(job_id)

    def update_stage(
        self,
        job_id: str,
        stage_num: int,
        stage_name: Optional[str] = None,
        progress: Optional[int] = None,
        modules: Optional[Dict[str, Any]] = None
    ):
        """Updates pipeline stage in memory and updates SQLite state machine."""
        if not stage_name:
            stage_name = f"Stage {stage_num}"
            for s_num, s_name in STAGES:
                if s_num == stage_num:
                    stage_name = s_name
                    break

        # Map stage number to persistent SQLite state string and in-memory JobStatus
        persistent_status = 'QUEUED'
        mem_status = STATUS_QUEUED
        if stage_num in (1, 2, 3):
            persistent_status = 'EXTRACTING'
            mem_status = STATUS_EXTRACTING
        elif 4 <= stage_num <= 7:
            persistent_status = 'PROCESSING'
            mem_status = STATUS_PROCESSING
        elif stage_num == 8:
            persistent_status = 'VALIDATING'
            mem_status = STATUS_VALIDATING
        elif stage_num == 9:
            persistent_status = 'COMPLETED'
            mem_status = STATUS_COMPLETED

        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]['stage'] = stage_num
                self.jobs[job_id]['stage_name'] = stage_name
                self.jobs[job_id]['status'] = mem_status
                if progress is not None:
                    self.jobs[job_id]['progress'] = progress
                if modules:
                    self.jobs[job_id]['modules'].update(modules)

        try:
            update_job_status(
                job_id,
                status=persistent_status,
                stage=stage_num,
                stage_name=stage_name,
                progress=progress
            )
        except Exception as e:
            logger.warning(f"Failed to update SQLite stage for {job_id}: {e}")

    def complete_job(
        self,
        job_id: str,
        result: Dict[str, Any],
        is_partial: bool = False,
        failed_modules: Optional[Dict[str, str]] = None
    ):
        """Completes an analysis job, transitioning to COMPLETED or PARTIAL."""
        status = STATUS_PARTIAL if is_partial else STATUS_COMPLETED
        stage_name = 'Completed (Partial)' if is_partial else 'Preparing dashboard'

        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]['status'] = status
                self.jobs[job_id]['stage'] = 9
                self.jobs[job_id]['stage_name'] = stage_name
                self.jobs[job_id]['progress'] = 100
                self.jobs[job_id]['is_partial'] = is_partial
                self.jobs[job_id]['result'] = result
                vid = self.jobs[job_id].get('video_id')
                if vid and vid in self.active_jobs:
                    self.active_jobs.pop(vid, None)

        sqlite_status = 'PARTIAL' if is_partial else 'COMPLETED'
        try:
            completed_mods = []
            if isinstance(result, dict) and "_module_status" in result:
                completed_mods = [k for k, v in result["_module_status"].items() if v == "COMPLETED"]
            update_job_status(
                job_id,
                status=sqlite_status,
                stage=9,
                stage_name=stage_name,
                progress=100,
                result_summary=result,
                modules_completed=completed_mods
            )
        except Exception as e:
            logger.warning(f"Failed to update SQLite complete_job for {job_id}: {e}")

        meta = result.get('_meta', {}) if isinstance(result, dict) else {}
        title = meta.get('title', job_id)
        mode_str = "with partial modules" if is_partial else "successfully"
        log_event('INFO', f"Analysis job {job_id} completed {mode_str} for '{title}'", source='analysis')

    def fail_job(self, job_id: str, error: Any):
        """Fails an analysis job with formatted user error message."""
        formatted_err = format_user_error(error)
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]['status'] = STATUS_FAILED
                self.jobs[job_id]['error'] = formatted_err
                vid = self.jobs[job_id].get('video_id')
                if vid and vid in self.active_jobs:
                    self.active_jobs.pop(vid, None)

        try:
            update_job_status(job_id, status='FAILED', error=formatted_err)
        except Exception as e:
            logger.warning(f"Failed to update SQLite fail_job for {job_id}: {e}")

        log_event('ERROR', f"Analysis job {job_id} failed: {str(error)[:120]}", source='analysis')

    def execute_with_retry(
        self,
        fn: Callable,
        task_name: str = "task",
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        backoff_factor: float = 2.0,
        job_id: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Executes a callable with exponential backoff on transient errors and thread pool isolation:
        delay = base_delay * (backoff_factor ** (attempt - 1))
        Submits fn to self.task_pool and enforces task timeout.
        """
        if max_retries is None:
            max_retries = 3
        if base_delay is None:
            base_delay = 0.05
        if timeout is None:
            timeout = self.timeouts.get(task_name, 30.0)

        attempts = 0
        while attempts < max_retries:
            attempts += 1
            try:
                future = self.task_pool.submit(fn)
                return future.result(timeout=timeout)
            except Exception as e:
                err_str = str(e).lower()
                is_transient = (
                    any(t in err_str for t in ['503', 'unavailable', '429', 'resource_exhausted', 'timeout', 'reset', 'connection'])
                    or isinstance(e, (ConnectionResetError, ConnectionError, TimeoutError, FutureTimeoutError))
                )
                if not is_transient or attempts >= max_retries:
                    raise

                delay = base_delay * (backoff_factor ** (attempts - 1))
                if job_id:
                    with self.lock:
                        if job_id in self.jobs:
                            self.jobs[job_id]['retry_count'] = attempts
                    try:
                        update_job_status(job_id, status="PROCESSING", retry_count=attempts)
                    except Exception:
                        pass
                time.sleep(delay)

    def submit_or_attach(self, video_id: str, user_id: Optional[str] = None, session_key: Optional[str] = None) -> Tuple[str, bool]:
        """
        Thread-safe deduplication lock: concurrent submissions for identical
        video_id attach to active/queued job instead of duplicating work.
        Returns: (job_id, is_new)
        """
        with self.lock:
            # 1. Check in-memory active jobs
            if video_id in self.active_jobs:
                active_id = self.active_jobs[video_id]
                job = self.get_job(active_id)
                if job and job.get("status") in [
                    STATUS_QUEUED, STATUS_EXTRACTING, STATUS_PROCESSING, STATUS_VALIDATING,
                    "queued", "extracting", "processing", "validating",
                    "QUEUED", "EXTRACTING", "PROCESSING", "VALIDATING"
                ]:
                    return active_id, False
                self.active_jobs.pop(video_id, None)

            # 2. Check active in SQLite analysis_jobs table
            try:
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute('''
                        SELECT id, status FROM analysis_jobs
                        WHERE video_id = ?
                          AND status IN ('QUEUED', 'EXTRACTING', 'PROCESSING', 'VALIDATING', 'queued', 'extracting', 'processing', 'validating')
                        ORDER BY created_at DESC LIMIT 1
                    ''', (video_id,))
                    row = c.fetchone()
                    if row:
                        self.active_jobs[video_id] = row['id']
                        return row['id'], False
            except Exception as e:
                logger.warning(f"Deduplication SQLite check error: {e}")

            # 3. Create fresh job
            new_id = self.create_job(video_id=video_id, user_id=user_id, session_key=session_key)
            self.active_jobs[video_id] = new_id
            return new_id, True

    def run_pipeline(
        self,
        job_id: str,
        video_id: str,
        user_id: Optional[str] = None,
        session_key: Optional[str] = None,
        key_pool: Optional[List[str]] = None,
        simulate_failures: Optional[Dict[str, bool]] = None
    ):
        """
        Synchronous pipeline runner executing 8 modular tasks with partial failure resiliency.
        Ensures unit tests calling run_analysis_job execute synchronously.
        """
        simulate_failures = simulate_failures or {}
        proc_event_id = None
        try:
            # 1. Determine user tier & permissions
            user = get_user(user_id) if user_id else None
            user_email = user.get("email") if user else ""
            user_plan = user.get("plan", "free") if user else "anonymous"
            is_paid = is_owner(user_email) or (user_plan in ["pack10", "pack50", "unlimited"])

            # 2. Check cached analysis (instant completion)
            cached = get_cached_analysis(video_id)
            if cached:
                cached_meta = cached.get('_meta') or {}
                c_title = cached_meta.get('title') or f"YouTube Video ({video_id})"
                c_dur = cached_meta.get('duration') or 'N/A'
                c_model = cached.get('_model_used') or cached_meta.get('model_used') or 'Gemini AI (Cached)'

                update_search_events_for_content(video_id, c_title)
                proc_event_id = record_processing_event(
                    user_id=user_id,
                    session_key=session_key,
                    content_id=video_id,
                    content_title=c_title,
                    content_type="YouTube Video",
                    status="pending",
                    plan=user_plan
                )
                self.update_stage(job_id, 9)
                increment_quota(user_id, session_key)
                if proc_event_id:
                    update_processing_event(proc_event_id, status="success", duration=c_dur, model_used=c_model)
                self.complete_job(job_id, cached)
                return

            # 3. Stage 1: Metadata Worker (Essential)
            self.update_stage(job_id, 1, 'Fetching metadata', progress=10)
            meta_res = self.execute_with_retry(
                lambda: run_metadata_worker(video_id),
                task_name="metadata",
                job_id=job_id
            )
            if not meta_res["success"]:
                self.fail_job(job_id, meta_res["error"])
                return
            metadata = meta_res["data"]
            video_title = metadata["title"]
            author_name = metadata["author"]
            thumbnail_url = metadata["thumbnail_url"]
            duration_str = metadata["duration"]

            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["modules"]["metadata"] = metadata

            update_search_events_for_content(video_id, video_title)
            proc_event_id = record_processing_event(
                user_id=user_id,
                session_key=session_key,
                content_id=video_id,
                content_title=video_title,
                content_type="YouTube Video",
                status="pending",
                plan=user_plan
            )

            # 4. Stage 2: Transcript Worker (Essential)
            self.update_stage(job_id, 2, 'Resolving transcript', progress=25)
            trans_res = self.execute_with_retry(
                lambda: run_transcript_worker(video_id, metadata),
                task_name="transcript",
                job_id=job_id
            )
            if not trans_res["success"]:
                if proc_event_id:
                    update_processing_event(proc_event_id, status="failed", error_info=str(trans_res["error"]))
                self.fail_job(job_id, trans_res["error"])
                return
            transcript_data = trans_res["data"]
            segments = transcript_data["segments"]
            duration_str = transcript_data["formatted_duration"]

            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["modules"]["transcript"] = segments

            # 5. Stage 3 & 4: Normalizing & Temporal Modeling
            self.update_stage(job_id, 3, 'Normalizing timestamps', progress=35)
            self.update_stage(job_id, 4, 'Building temporal model', progress=45)

            # 6. Stage 5: Summary & Core Intelligence (Essential)
            self.update_stage(job_id, 5, 'Generating core intelligence', progress=60)
            raw_analysis = run_videolens_analysis(
                segments,
                duration_str,
                video_title,
                author_name,
                key_pool,
                is_paid=is_paid
            )

            sum_res = self.execute_with_retry(
                lambda: run_summary_worker(segments, metadata, key_pool=key_pool, is_paid=is_paid, raw_analysis=raw_analysis),
                task_name="summary",
                job_id=job_id
            )
            if not sum_res["success"]:
                if proc_event_id:
                    update_processing_event(proc_event_id, status="failed", error_info=str(sum_res["error"]))
                self.fail_job(job_id, sum_res["error"])
                return
            summary_data = sum_res["data"]

            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["modules"]["summary"] = summary_data["video_overview"]

            modules_status = {
                "metadata": "COMPLETED",
                "transcript": "COMPLETED",
                "summary": "COMPLETED"
            }
            failed_modules = {}
            is_partial = False

            # 7. Stage 6: Chapter Worker (Essential with fallback)
            self.update_stage(job_id, 6, 'Generating research insights', progress=70)
            try:
                chap_res = self.execute_with_retry(
                    lambda: run_chapter_worker(segments, metadata, key_pool=key_pool, is_paid=is_paid, raw_analysis=raw_analysis),
                    task_name="chapters",
                    job_id=job_id
                )
            except Exception as e:
                chap_res = {"success": False, "error": str(e)}

            if chap_res["success"]:
                modules_status["chapters"] = "COMPLETED"
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]["modules"]["chapters"] = chap_res["data"]["chapters"]
            else:
                modules_status["chapters"] = "FAILED"
                failed_modules["chapters"] = chap_res["error"]
                is_partial = True

            # 8. Stage 7: Claims & Learning Workers (Non-essential Auxiliary)
            self.update_stage(job_id, 7, 'Generating learning material', progress=80)
            try:
                claim_res = self.execute_with_retry(
                    lambda: run_claim_worker(segments, metadata, key_pool=key_pool, is_paid=is_paid, raw_analysis=raw_analysis),
                    task_name="claims",
                    job_id=job_id
                )
            except Exception as e:
                claim_res = {"success": False, "error": str(e)}

            if claim_res["success"]:
                modules_status["claims"] = "COMPLETED"
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]["modules"]["claims"] = claim_res["data"]["claims"]
                        if "contradictions" in claim_res["data"]:
                            self.jobs[job_id]["modules"]["contradictions"] = claim_res["data"]["contradictions"]
                if isinstance(raw_analysis, dict):
                    raw_analysis["claims"] = claim_res["data"]["claims"]
                    raw_analysis["factual_claims"] = claim_res["data"].get("factual_claims", claim_res["data"]["claims"])
                    if "contradictions" in claim_res["data"]:
                        raw_analysis["contradictions"] = claim_res["data"]["contradictions"]
            else:
                modules_status["claims"] = "FAILED"
                failed_modules["claims"] = claim_res["error"]
                is_partial = True

            try:
                learn_res = self.execute_with_retry(
                    lambda: run_learning_worker(segments, metadata, key_pool=key_pool, is_paid=is_paid, raw_analysis=raw_analysis),
                    task_name="learning",
                    job_id=job_id
                )
            except Exception as e:
                learn_res = {"success": False, "error": str(e)}

            if learn_res["success"]:
                modules_status["learning"] = "COMPLETED"
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]["modules"]["learning"] = learn_res["data"]["learning"]
                if isinstance(raw_analysis, dict):
                    raw_analysis["learning"] = learn_res["data"]["learning"]
                    if "flashcards" in learn_res["data"]:
                        raw_analysis["flashcards"] = learn_res["data"]["flashcards"]
                    if "quizzes" in learn_res["data"]:
                        raw_analysis["quizzes"] = learn_res["data"]["quizzes"]
            else:
                modules_status["learning"] = "FAILED"
                failed_modules["learning"] = learn_res["error"]
                is_partial = True

            # Entity Intelligence & Knowledge Graph
            if simulate_failures.get("knowledge_graph"):
                modules_status["knowledge_graph"] = "FAILED"
                failed_modules["knowledge_graph"] = "Simulated knowledge graph generation failure"
                is_partial = True
            else:
                try:
                    ent_res = self.execute_with_retry(
                        lambda: run_entity_worker(segments, metadata, key_pool=key_pool, is_paid=is_paid, raw_analysis=raw_analysis),
                        task_name="entities",
                        job_id=job_id
                    )
                except Exception as e:
                    ent_res = {"success": False, "error": str(e)}

                if ent_res["success"]:
                    modules_status["entities"] = "COMPLETED"
                    modules_status["knowledge_graph"] = "COMPLETED"
                    with self.lock:
                        if job_id in self.jobs:
                            self.jobs[job_id]["modules"]["entities"] = ent_res["data"]["entities"]
                            self.jobs[job_id]["modules"]["knowledge_graph"] = ent_res["data"]["knowledge_graph"]
                else:
                    modules_status["knowledge_graph"] = "FAILED"
                    failed_modules["knowledge_graph"] = ent_res["error"]
                    is_partial = True

            # 9. Stage 8: Grounded AI Verification & Guardrails (VALIDATING)
            self.update_stage(job_id, 8, 'Validating evidence & guardrails', progress=90)
            try:
                from services.verification_service import (
                    verify_grounded_claims,
                    validate_bloom_quiz,
                    validate_flashcards,
                    classify_contradictions,
                )

                duration_sec = transcript_data.get("duration_seconds", 7200) if transcript_data else 7200
                channel_author = metadata.get("author", "") if metadata else ""

                # A. Verify Grounded Claims
                raw_claims = raw_analysis.get("claims", []) if isinstance(raw_analysis, dict) else []
                if not raw_claims and isinstance(raw_analysis, dict) and "key_takeaways" in raw_analysis:
                    raw_claims = raw_analysis.get("key_takeaways", [])

                verified_claims, claim_stats = verify_grounded_claims(
                    claims=raw_claims,
                    transcript_segments=segments or [],
                    max_duration=duration_sec,
                    channel_author=channel_author
                )
                if isinstance(raw_analysis, dict):
                    raw_analysis["claims"] = verified_claims
                    raw_analysis["factual_claims"] = verified_claims

                # Also ground key_takeaways if present and distinct
                if isinstance(raw_analysis, dict) and "key_takeaways" in raw_analysis and raw_analysis["key_takeaways"] != raw_claims:
                    grounded_takeaways, _ = verify_grounded_claims(
                        claims=raw_analysis["key_takeaways"],
                        transcript_segments=segments or [],
                        max_duration=duration_sec,
                        channel_author=channel_author
                    )
                    raw_analysis["key_takeaways"] = grounded_takeaways

                # B. Validate Bloom Quiz & Flashcards
                raw_learning = raw_analysis.get("learning", {}) if isinstance(raw_analysis, dict) else {}
                raw_quiz = raw_learning.get("quiz", []) if isinstance(raw_learning, dict) else []
                raw_flashcards = raw_learning.get("flashcards", []) if isinstance(raw_learning, dict) else []

                validated_quiz, is_quiz_valid = validate_bloom_quiz(raw_quiz)
                validated_flashcards, is_fc_valid = validate_flashcards(raw_flashcards)

                if isinstance(raw_learning, dict):
                    raw_learning["quiz"] = validated_quiz
                    raw_learning["flashcards"] = validated_flashcards
                if isinstance(raw_analysis, dict):
                    raw_analysis["learning"] = raw_learning
                    raw_analysis["quizzes"] = validated_quiz
                    raw_analysis["flashcards"] = validated_flashcards

                # C. Classify Contradictions
                raw_contradictions = raw_analysis.get("contradictions", []) if isinstance(raw_analysis, dict) else []
                verified_contradictions = classify_contradictions(
                    contradictions=raw_contradictions,
                    transcript_segments=segments or []
                )
                if isinstance(raw_analysis, dict):
                    raw_analysis["contradictions"] = verified_contradictions

                # D. Attach Verification Metadata
                claim_rate = claim_stats.get("grounding_rate", 1.0) if claim_stats else 1.0
                bloom_rate = 1.0 if is_quiz_valid else (round(len(validated_quiz) / max(1, len(raw_quiz)), 2) if raw_quiz else 1.0)

                verification_metadata = {
                    "status": "COMPLETED",
                    "claim_verification_rate": claim_rate,
                    "bloom_validity_rate": bloom_rate,
                    "claims_verified_count": len(verified_claims),
                    "quiz_questions_validated": len(validated_quiz),
                    "contradictions_classified_count": len(verified_contradictions),
                    "verified_contradictions": verified_contradictions,
                    "contradiction_breakdown": {
                        "DIRECT_CONTRADICTION": sum(1 for c in verified_contradictions if c.get("classification") == "DIRECT_CONTRADICTION"),
                        "TEMPORAL_EVOLUTION": sum(1 for c in verified_contradictions if c.get("classification") == "TEMPORAL_EVOLUTION"),
                        "CONDITIONAL_QUALIFICATION": sum(1 for c in verified_contradictions if c.get("classification") == "CONDITIONAL_QUALIFICATION"),
                        "PERSPECTIVE_DIVERGENCE": sum(1 for c in verified_contradictions if c.get("classification") == "PERSPECTIVE_DIVERGENCE"),
                    },
                    "verified_at": datetime.utcnow().isoformat()
                }

                if isinstance(raw_analysis, dict):
                    raw_analysis["_verification"] = verification_metadata
                    raw_analysis["claim_verification_rate"] = claim_rate
                    raw_analysis["bloom_validity_rate"] = bloom_rate
                    raw_analysis["claims_verified_count"] = len(verified_claims)
                    raw_analysis["quiz_questions_validated"] = len(validated_quiz)
                    raw_analysis["contradictions_classified_count"] = len(verified_contradictions)
                    raw_analysis["contradiction_breakdown"] = verification_metadata["contradiction_breakdown"]
                    raw_analysis["verified_contradictions"] = verified_contradictions

                modules_status["verification"] = "COMPLETED"

                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]["modules"]["claims"] = verified_claims
                        self.jobs[job_id]["modules"]["contradictions"] = verified_contradictions
                        self.jobs[job_id]["modules"]["learning"] = raw_learning
                        self.jobs[job_id]["modules"]["verification"] = verification_metadata

            except Exception as e:
                logger.error(f"Error during validation stage for job {job_id}: {e}")
                modules_status["verification"] = "FAILED"
                failed_modules["verification"] = str(e)
                # Validation error degrades gracefully to PARTIAL without crashing job
                is_partial = True

            # 10. Stage 9: Export Worker (Non-essential Auxiliary)
            self.update_stage(job_id, 9, 'Preparing dashboard', progress=95)
            if simulate_failures.get("export_pdf"):
                modules_status["export_pdf"] = "FAILED"
                failed_modules["export_pdf"] = "Simulated ReportLab worker memory error"
                is_partial = True
            else:
                try:
                    exp_res = self.execute_with_retry(
                        lambda: run_export_worker(raw_analysis, video_id, user_id=user_id, session_key=session_key),
                        task_name="export_pdf",
                        job_id=job_id
                    )
                except Exception as e:
                    exp_res = {"success": False, "error": str(e)}

                if exp_res["success"]:
                    modules_status["export_pdf"] = "COMPLETED"
                else:
                    modules_status["export_pdf"] = "FAILED"
                    failed_modules["export_pdf"] = exp_res["error"]
                    is_partial = True

            # 11. Final Polish, Relational Persistence & Completion
            model_name = raw_analysis.get("_model_used", "Gemini AI")
            raw_analysis["_meta"] = {
                "video_id": video_id,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": thumbnail_url,
                "author": author_name,
                "title": video_title,
                "duration": duration_str,
                "duration_seconds": transcript_data.get("duration_seconds", 0),
                "tier": "Premium Intelligence" if is_paid else "Standard Analysis",
                "model_used": model_name,
                "is_premium": is_paid
            }
            raw_analysis["_transcript_sample"] = transcript_data.get("ui_sample", [])
            raw_analysis["_module_status"] = modules_status
            raw_analysis["_partial"] = is_partial
            raw_analysis["is_partial"] = is_partial
            raw_analysis["transcript_segments"] = segments

            with self.lock:
                current_modules = dict(self.jobs.get(job_id, {}).get("modules", {}))
            raw_analysis["modules"] = current_modules
            if failed_modules:
                raw_analysis["_error_details"] = failed_modules
                raw_analysis["failed_modules"] = failed_modules

            save_analysis(video_id, video_title, author_name, duration_str, raw_analysis, user_id, session_key)
            increment_quota(user_id, session_key)

            if proc_event_id:
                update_processing_event(proc_event_id, status="success", duration=duration_str, model_used=model_name)

            self.complete_job(job_id, raw_analysis, is_partial=is_partial, failed_modules=failed_modules)

        except Exception as e:
            if proc_event_id:
                update_processing_event(proc_event_id, status="failed", error_info=str(e))
            self.fail_job(job_id, e)
