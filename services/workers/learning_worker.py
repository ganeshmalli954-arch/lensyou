import time
import re
from typing import Any, Dict, List, Optional

def run_learning_worker(
    segments: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    key_pool: Optional[List[str]] = None,
    is_paid: bool = False,
    raw_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Worker 6: Learning Worker (Non-Essential Auxiliary)
    Produces Bloom's Taxonomy quizzes, spaced-repetition flashcards, key definitions,
    and structured study notes. Fault-isolated to prevent job failure on schema errors.
    """
    from services.workers import WorkerResult
    start_t = time.time()

    try:
        learning = {}
        if raw_analysis and isinstance(raw_analysis, dict):
            learning = raw_analysis.get("learning", {})

        key_definitions = learning.get("key_definitions", [])
        study_notes = learning.get("study_notes", [])
        flashcards = learning.get("flashcards", [])
        quiz = learning.get("quiz", [])

        # Sanitize definitions (strip markdown hashes/asterisks from term names)
        for d in key_definitions:
            if isinstance(d, dict) and "term" in d:
                d["term"] = re.sub(r'^[#*\s]+|[#*\s]+$', '', str(d["term"]))

        from services.verification_service import validate_bloom_quiz, validate_flashcards

        # Validate and guardrail quiz items
        validated_quiz, _ = validate_bloom_quiz(quiz)

        # Validate and guardrail flashcards
        validated_flashcards, _ = validate_flashcards(flashcards)

        data = {
            "learning": {
                "key_definitions": key_definitions,
                "study_notes": study_notes,
                "flashcards": validated_flashcards,
                "quiz": validated_quiz
            },
            "flashcards": validated_flashcards,
            "quizzes": validated_quiz
        }

        return WorkerResult(
            module="learning",
            success=True,
            data=data,
            is_essential=False,
            execution_time=time.time() - start_t
        )

    except Exception as e:
        return WorkerResult(
            module="learning",
            success=False,
            error=str(e),
            is_essential=False,
            execution_time=time.time() - start_t
        )
