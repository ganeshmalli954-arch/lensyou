import json
from json_repair import repair_json

def safe_json_parse(text: str) -> dict:
    """Uses json_repair to fix truncated/broken Gemini JSON, fallback to empty dict with error key."""
    if not text:
        return {"error": "Empty JSON string"}
        
    try:
        # First try standard json parsing for speed
        text_clean = text.strip()
        if text_clean.startswith("```"):
            import re
            text_clean = re.sub(r'^```(?:json)?\s*\n?', '', text_clean)
            text_clean = re.sub(r'\n?```\s*$', '', text_clean)
        return json.loads(text_clean)
    except Exception:
        try:
            # Fallback to json_repair for broken/truncated output
            repaired = repair_json(text, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
            elif isinstance(repaired, list) and len(repaired) > 0 and isinstance(repaired[0], dict):
                return repaired[0]
            return {"error": "Could not parse repaired JSON into a dictionary"}
        except Exception as e:
            return {"error": f"JSON parsing failed completely: {str(e)}"}

def sanitize_data_strings(obj):
    """Recursively strip stray markdown asterisks and header hashes from Gemini JSON strings."""
    if isinstance(obj, str):
        cleaned = obj.replace("**", "").replace("### ", "").replace("## ", "")
        return cleaned
    elif isinstance(obj, list):
        return [sanitize_data_strings(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: sanitize_data_strings(v) for k, v in obj.items()}
    return obj
