import os
import json
from datetime import datetime
from config import DATABASE_PATH
from services.storage_service import get_cached_analysis, get_recent_videos

TRAINING_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
EXEMPLARS_FILE = os.path.join(TRAINING_DIR, 'training_exemplars.json')
GEMINI_DATASET_FILE = os.path.join(TRAINING_DIR, 'gemini_fine_tuning.jsonl')
OPENAI_DATASET_FILE = os.path.join(TRAINING_DIR, 'openai_fine_tuning.jsonl')

def _ensure_training_dir():
    os.makedirs(TRAINING_DIR, exist_ok=True)

def load_training_data() -> dict:
    _ensure_training_dir()
    if os.path.exists(EXEMPLARS_FILE):
        try:
            with open(EXEMPLARS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  [Training Service Error] Loading exemplars: {e}", flush=True)
    return {"samples": {}, "updated_at": datetime.utcnow().isoformat()}

def save_training_data(data: dict):
    _ensure_training_dir()
    data["updated_at"] = datetime.utcnow().isoformat()
    with open(EXEMPLARS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def add_video_to_training(video_id: str, custom_notes: str = "") -> dict:
    """
    Extracts an analyzed video from SQLite database, formats it into training pair,
    and adds it to the active model training store.
    """
    cached = get_cached_analysis(video_id)
    if not cached:
        return {"success": False, "error": f"Video '{video_id}' has not been analyzed yet or is not in cache."}
    
    meta = cached.get("_meta", {})
    overview = cached.get("video_overview", {})
    title = meta.get("title") or overview.get("title") or f"YouTube Video ({video_id})"
    category = overview.get("category", "General")
    duration = meta.get("duration") or overview.get("estimated_duration", "N/A")
    snippets = cached.get("_transcript_sample", [])
    
    # Compute token / word estimate
    raw_text = " ".join([s.get("text", "") for s in snippets if isinstance(s, dict)]) if snippets else ""
    word_count = len(raw_text.split())

    store = load_training_data()
    store["samples"][video_id] = {
        "video_id": video_id,
        "title": title,
        "author": meta.get("author", "Creator"),
        "duration": duration,
        "category": category,
        "custom_notes": custom_notes,
        "word_count": word_count,
        "has_transcript": bool(snippets),
        "added_at": datetime.utcnow().isoformat(),
        "verified_metrics": {
            "key_takeaways_count": len(cached.get("key_takeaways", [])),
            "chapters_count": len(cached.get("chapters", [])),
            "claims_count": len(cached.get("claims", [])),
            "quiz_count": len(cached.get("learning", {}).get("quiz", []))
        }
    }
    save_training_data(store)
    return {"success": True, "message": f"Successfully added '{title}' to model training exemplars.", "sample": store["samples"][video_id]}

def remove_video_from_training(video_id: str) -> dict:
    store = load_training_data()
    if video_id in store.get("samples", {}):
        del store["samples"][video_id]
        save_training_data(store)
        return {"success": True, "message": f"Removed video '{video_id}' from training store."}
    return {"success": False, "error": "Video not found in training store."}

def list_training_samples() -> list:
    store = load_training_data()
    samples = list(store.get("samples", {}).values())
    samples.sort(key=lambda x: x.get("added_at", ""), reverse=True)
    return samples

def get_training_stats() -> dict:
    samples = list_training_samples()
    total_words = sum(s.get("word_count", 0) for s in samples)
    categories = {}
    for s in samples:
        cat = s.get("category", "General")
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        "total_samples": len(samples),
        "estimated_tokens": int(total_words * 1.33),
        "categories": categories,
        "last_updated": load_training_data().get("updated_at")
    }

def get_exemplars_for_prompt(category: str = None, limit: int = 1) -> str:
    """
    Retrieves the best matching exemplar from training store to inject as a few-shot
    in-context reference during live analysis.
    """
    samples = list_training_samples()
    if not samples:
        return ""
    
    # Filter by category if available
    matches = [s for s in samples if s.get("category", "").lower() == (category or "").lower()]
    target_sample = matches[0] if matches else samples[0]
    vid_id = target_sample.get("video_id")
    
    cached = get_cached_analysis(vid_id)
    if not cached:
        return ""

    # Build condensed exemplar
    condensed = {
        "video_overview": cached.get("video_overview", {}),
        "key_takeaways": cached.get("key_takeaways", [])[:3],
        "chapters": cached.get("chapters", [])[:3],
        "claims": cached.get("claims", [])[:3],
        "learning": {
            "flashcards": cached.get("learning", {}).get("flashcards", [])[:2],
            "quiz": cached.get("learning", {}).get("quiz", [])[:2]
        }
    }
    return json.dumps(condensed, indent=2, ensure_ascii=False)

def export_gemini_jsonl() -> str:
    """
    Exports all training exemplars into Google Gemini Vertex AI / AI Studio SFT JSONL format.
    """
    _ensure_training_dir()
    samples = list_training_samples()
    lines = []
    
    from services.analysis_service import VIDEOLENS_PROMPT
    system_instruction = "You are LensYou, an elite video intelligence platform analyst. Analyze this entire video thoroughly across all dimensions and return strict valid JSON."

    for s in samples:
        vid_id = s.get("video_id")
        cached = get_cached_analysis(vid_id)
        if not cached:
            continue
        
        snippets = cached.get("_transcript_sample", [])
        transcript_text = "\n".join([f"[{sn.get('timestamp', '')}] {sn.get('text', '')}" for sn in snippets if isinstance(sn, dict)])
        meta = cached.get("_meta", {})
        
        user_prompt = VIDEOLENS_PROMPT.format(
            title=meta.get("title", s.get("title")),
            author=meta.get("author", s.get("author")),
            duration=meta.get("duration", s.get("duration")),
            transcript_sample=transcript_text[:120000]
        )
        
        # Clean cached object of non-schema keys
        clean_target = {k: v for k, v in cached.items() if not k.startswith("_")}
        target_json = json.dumps(clean_target, ensure_ascii=False)
        
        record = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                },
                {
                    "role": "model",
                    "parts": [{"text": target_json}]
                }
            ]
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    with open(GEMINI_DATASET_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    
    return GEMINI_DATASET_FILE

def export_openai_jsonl() -> str:
    """
    Exports all training exemplars into OpenAI / Open-Source (Llama/Mistral) fine-tuning JSONL format.
    """
    _ensure_training_dir()
    samples = list_training_samples()
    lines = []
    
    from services.analysis_service import VIDEOLENS_PROMPT
    system_instruction = "You are LensYou, an elite video intelligence platform analyst. Return strict valid JSON."

    for s in samples:
        vid_id = s.get("video_id")
        cached = get_cached_analysis(vid_id)
        if not cached:
            continue
        
        snippets = cached.get("_transcript_sample", [])
        transcript_text = "\n".join([f"[{sn.get('timestamp', '')}] {sn.get('text', '')}" for sn in snippets if isinstance(sn, dict)])
        meta = cached.get("_meta", {})
        
        user_prompt = VIDEOLENS_PROMPT.format(
            title=meta.get("title", s.get("title")),
            author=meta.get("author", s.get("author")),
            duration=meta.get("duration", s.get("duration")),
            transcript_sample=transcript_text[:120000]
        )
        
        clean_target = {k: v for k, v in cached.items() if not k.startswith("_")}
        target_json = json.dumps(clean_target, ensure_ascii=False)
        
        record = {
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": target_json}
            ]
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    with open(OPENAI_DATASET_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    
    return OPENAI_DATASET_FILE

# Seed with available cached videos if training store is currently empty
def seed_training_store():
    store = load_training_data()
    if not store.get("samples"):
        recent = get_recent_videos(limit=5)
        for r in recent:
            vid = r.get("video_id")
            if vid:
                add_video_to_training(vid, custom_notes="Curated bootstrap exemplar")
