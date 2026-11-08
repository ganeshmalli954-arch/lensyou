import time
from typing import Any, Dict, List, Optional

def run_entity_worker(
    segments: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    key_pool: Optional[List[str]] = None,
    is_paid: bool = False,
    raw_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Worker 7: Entity Intelligence & Knowledge Graph Worker (Non-Essential Auxiliary)
    Identifies people, companies, tools, concepts, and relationships (nodes/links).
    Fault-isolated so graph layout or token limits do not block core summary delivery.
    """
    from services.workers import WorkerResult
    start_t = time.time()

    try:
        entities = {}
        knowledge_graph = {}

        if raw_analysis and isinstance(raw_analysis, dict):
            entities = raw_analysis.get("entities", {})
            knowledge_graph = raw_analysis.get("knowledge_graph", {})

        if not entities or not isinstance(entities, dict):
            entities = {
                "people": [],
                "companies": [],
                "tools_software": [],
                "concepts": []
            }

        if not knowledge_graph or not isinstance(knowledge_graph, dict):
            knowledge_graph = {
                "nodes": [],
                "links": []
            }

        data = {
            "entities": entities,
            "knowledge_graph": knowledge_graph
        }

        return WorkerResult(
            module="entities",
            success=True,
            data=data,
            is_essential=False,
            execution_time=time.time() - start_t
        )

    except Exception as e:
        return WorkerResult(
            module="entities",
            success=False,
            error=str(e),
            is_essential=False,
            execution_time=time.time() - start_t
        )
