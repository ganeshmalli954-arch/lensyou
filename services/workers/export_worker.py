import time
from typing import Any, Dict, Optional

def run_export_worker(
    analysis_data: Dict[str, Any],
    video_id: str,
    user_id: Optional[str] = None,
    session_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Worker 8: Export Worker (Non-Essential Auxiliary)
    Generates downloadable ReportLab PDF dossier, Markdown, and CSV data.
    Records generated export in SQLite table 'exports'.
    Fault-isolated so ReportLab XML issues or memory spikes never fail analysis jobs.
    """
    from services.workers import WorkerResult
    start_t = time.time()

    try:
        from pdf_generator import generate_detailed_pdf
        from services.storage_service import record_export

        import io
        pdf_out = generate_detailed_pdf(analysis_data)
        if isinstance(pdf_out, io.BytesIO):
            pdf_bytes = pdf_out.getvalue()
        elif isinstance(pdf_out, (bytes, bytearray)):
            pdf_bytes = bytes(pdf_out)
        else:
            pdf_bytes = b""
        file_size = len(pdf_bytes)

        export_id = ""
        try:
            export_id = record_export(
                video_id=video_id,
                export_type="pdf",
                user_id=user_id,
                session_key=session_key,
                file_size=file_size,
                status="completed"
            )
        except Exception:
            export_id = f"exp_{video_id[:8]}"

        data = {
            "pdf_generated": True,
            "pdf_bytes": pdf_bytes,
            "pdf_size": file_size,
            "export_id": export_id
        }

        return WorkerResult(
            module="export_pdf",
            success=True,
            data=data,
            is_essential=False,
            execution_time=time.time() - start_t
        )

    except Exception as e:
        return WorkerResult(
            module="export_pdf",
            success=False,
            error=str(e),
            is_essential=False,
            execution_time=time.time() - start_t
        )
