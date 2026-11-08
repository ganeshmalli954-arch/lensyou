import time
from typing import Any, Dict, List, Optional

def run_claim_worker(
    segments: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    key_pool: Optional[List[str]] = None,
    is_paid: bool = False,
    raw_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Worker 5: Claim & Contradiction Worker (Non-Essential Auxiliary)
    Extracts distinct claims, statistics, speculations, and logical contradictions.
    Fault-isolated so errors degrade gracefully to PARTIAL without failing the job.
    """
    from services.workers import WorkerResult
    start_t = time.time()

    try:
        claims = []
        factual_claims = []
        contradictions = []

        if raw_analysis and isinstance(raw_analysis, dict):
            claims = raw_analysis.get("claims", [])
            if not claims and "key_takeaways" in raw_analysis:
                claims = raw_analysis.get("key_takeaways", [])
            factual_claims = raw_analysis.get("factual_claims") or claims
            contradictions = raw_analysis.get("contradictions", [])

        dur_sec = 7200
        author = ""
        if metadata and isinstance(metadata, dict):
            dur_sec = metadata.get("duration_seconds", 7200)
            author = metadata.get("author", "")

        from services.verification_service import verify_grounded_claims, classify_contradictions

        grounded_claims, v_stats = verify_grounded_claims(
            claims=claims,
            transcript_segments=segments or [],
            max_duration=dur_sec,
            channel_author=author
        )

        classified_contradictions = classify_contradictions(
            contradictions=contradictions,
            transcript_segments=segments or []
        )

        data = {
            "claims": grounded_claims,
            "factual_claims": grounded_claims,
            "contradictions": classified_contradictions,
            "verification_stats": v_stats
        }

        return WorkerResult(
            module="claims",
            success=True,
            data=data,
            is_essential=False,
            execution_time=time.time() - start_t
        )

    except Exception as e:
        return WorkerResult(
            module="claims",
            success=False,
            error=str(e),
            is_essential=False,
            execution_time=time.time() - start_t
        )
