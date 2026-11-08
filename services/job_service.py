"""
services.job_service
Backward-compatible facade delegating to services.orchestrator.AsyncJobOrchestrator.
Maintains 100% backward compatibility for all existing methods and guarantees
synchronous execution for tests calling run_analysis_job directly.
"""
from typing import Any, Dict, Optional, Tuple, List
from services.orchestrator import (
    AsyncJobOrchestrator, JobStatus, STAGES, format_user_error,
    STATUS_QUEUED, STATUS_EXTRACTING, STATUS_PROCESSING, STATUS_VALIDATING,
    STATUS_COMPLETED, STATUS_PARTIAL, STATUS_FAILED
)

# Global singleton orchestrator
orchestrator = AsyncJobOrchestrator()
JOBS = orchestrator.jobs

def create_job(video_id: str = "", user_id: Optional[str] = None, session_key: Optional[str] = None) -> str:
    return orchestrator.create_job(video_id=video_id, user_id=user_id, session_key=session_key)

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return orchestrator.get_job(job_id)

def update_job_stage(job_id: str, stage_num: int):
    orchestrator.update_stage(job_id, stage_num)

def complete_job(job_id: str, result: Dict[str, Any]):
    is_partial = False
    if isinstance(result, dict) and (result.get('_partial') or result.get('is_partial')):
        is_partial = True
    orchestrator.complete_job(job_id, result, is_partial=is_partial)

def fail_job(job_id: str, error: Any):
    orchestrator.fail_job(job_id, error)

def run_analysis_job(
    job_id: str,
    video_id: str,
    user_id: Optional[str] = None,
    session_key: Optional[str] = None,
    key_pool: Optional[List[str]] = None
):
    """
    Executes the analysis pipeline synchronously on the caller's thread,
    guaranteeing that existing unit and regression tests run to completion.
    """
    orchestrator.run_pipeline(
        job_id,
        video_id,
        user_id=user_id,
        session_key=session_key,
        key_pool=key_pool
    )

def start_job(job_id: str, **kwargs):
    """
    Submits the analysis pipeline to run asynchronously in the orchestrator job pool.
    """
    orchestrator.job_pool.submit(
        orchestrator.run_pipeline,
        job_id,
        kwargs.get('video_id', ''),
        kwargs.get('user_id'),
        kwargs.get('session_key'),
        kwargs.get('key_pool')
    )

def submit_or_attach(
    video_id: str,
    user_id: Optional[str] = None,
    session_key: Optional[str] = None
) -> Tuple[str, bool]:
    """
    Thread-safe deduplication lock: concurrent submissions for identical video_id
    attach to active/queued job instead of duplicating work.
    """
    return orchestrator.submit_or_attach(video_id, user_id=user_id, session_key=session_key)
