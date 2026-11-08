import time
from typing import Any, Dict, Optional

class WorkerResult:
    """Normalized contract returned by all modular workers in services.workers."""
    def __init__(
        self,
        module: str,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        is_essential: bool = False,
        execution_time: float = 0.0
    ):
        self.module = module
        self.success = success
        self.data = data if data is not None else {}
        self.error = str(error) if error is not None else None
        self.is_essential = is_essential
        self.execution_time = round(execution_time, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "is_essential": self.is_essential,
            "execution_time": self.execution_time
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __repr__(self) -> str:
        status_str = "SUCCESS" if self.success else f"FAILED({self.error})"
        return f"<WorkerResult module={self.module} {status_str} essential={self.is_essential}>"

from services.workers.metadata_worker import run_metadata_worker
from services.workers.transcript_worker import run_transcript_worker
from services.workers.summary_worker import run_summary_worker
from services.workers.chapter_worker import run_chapter_worker
from services.workers.claim_worker import run_claim_worker
from services.workers.learning_worker import run_learning_worker
from services.workers.entity_worker import run_entity_worker
from services.workers.export_worker import run_export_worker

__all__ = [
    "WorkerResult",
    "run_metadata_worker",
    "run_transcript_worker",
    "run_summary_worker",
    "run_chapter_worker",
    "run_claim_worker",
    "run_learning_worker",
    "run_entity_worker",
    "run_export_worker",
]
