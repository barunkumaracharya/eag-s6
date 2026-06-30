

import json
import uuid
from datetime import datetime
from pathlib import Path
from schemas import MemoryItem, ToolCall, HistoryItem
from llm_gatewayV3.client import LLM

MEMORY_FILE = Path("state") / "memory.json"

STOP_WORDS = {
    # Pronouns & Prepositions
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", 
    "yourself", "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", 
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves", "what", "which", 
    "who", "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were", "be", 
    "been", "being", "have", "has", "had", "having", "do", "does", "did", "doing", "a", "an", 
    "the", "and", "but", "if", "or", "because", "as", "until", "while", "of", "at", "by", 
    "for", "with", "about", "against", "between", "into", "through", "during", "before", 
    "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off", "over", 
    "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", 
    "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", 
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", 
    "will", "just", "don", "should", "now", "would", "could", "must",
    # Common system/tool vocabulary we want to ignore in keyword matches
    "called", "outcome", "result", "arguments", "value", "tool"
}


def remember(text: str, source: str, run_id: str) -> None:
    """Remember a fact or preference from the user query."""
    # Ensure directory exists
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Call LLM gateway with auto_route='memory' to extract facts/axioms
    llm = LLM()
    system = (
        "You are a memory processor. Your objective is to extract any definitive facts or axioms "
        "present in the user text. For each line/part of the user text, analyze its semantics:\n"
        "- Determine if it is a question/interrogative query (e.g. 'What is the capital of France?'). If so, ignore it.\n"
        "- Determine if it is a statement containing definitive facts, axioms, or user preferences (e.g. 'Environment day is 1st June. American national day is 4th July. I like apples.').\n"
        "If they are statements containing facts/axioms/preferences, extract them and provide them as summarized, clear declarative statements.\n"
        "- Your task is ONLY to parse the statements and determine facts from the given STATEMENTS ONLY"
        "- Donot generate anything that is NOT present in the given query."
        "- As part of validation, after you generate the list of facts, compare it with the given query and make sure that"
        "it is present in the given query."
        "Provide your output strictly as a JSON list under the key 'facts'."
    )
    
    schema = {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["facts"]
    }
    
    try:
        resp = []
        resp = llm.chat(
            prompt=text,
            system=system,
            auto_route="memory",
            response_format={"type": "json_schema", "schema": schema}
        )
        result = json.loads(resp.get("text", "{}"))
        facts = result.get("facts", [])
    except Exception as e:
        print(f"Memory extraction LLM call failed: {e}. Falling back to empty facts.")
        facts = []
        
    if not facts:
        print(f"Memory: No definitive facts extracted from: {text!r}")
        return
        
    # Extract keywords from the extracted facts
    combined_facts_text = " ".join(facts)
    words = [w.strip(".,?!;:()\"'").lower() for w in combined_facts_text.split()]
    keywords = list(set([w for w in words if len(w) > 3 and w not in STOP_WORDS]))
    
    item = MemoryItem(
        id=f"mem_{uuid.uuid4().hex[:8]}",
        kind="fact",
        keywords=keywords,
        descriptor=facts[0][:60] + "..." if len(facts[0]) > 60 else facts[0],
        value={"text": text, "extracted_facts": facts},
        artifact_id=None,
        source=source,
        run_id=run_id,
        goal_id=None,
        confidence=1.0,
        created_at=datetime.now()
    )
    
    # Load existing items
    items = []
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
                if not isinstance(items, list):
                    items = []
        except Exception:
            items = []
            
    items.append(item.model_dump(mode="json"))
    
    # Write back
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
        
    print(f"Memory: Remembering {item}")


def read(query: str, history: list[HistoryItem]) -> list[MemoryItem]:
    """Read relevant memory items for the given query and history."""
    if not MEMORY_FILE.exists():
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
    except Exception:
        return []
        
    query_words = {w.strip(".,?!;:()\"'").lower() for w in query.split()}
    query_words = {w for w in query_words if w not in STOP_WORDS}
    
    result = []
    for obj in data:
        try:
            item = MemoryItem(**obj)
            if item.kind != "fact" and item.kind != "tool_outcome":
                continue
            
            item_keywords = {k.lower() for k in item.keywords}
            overlap = query_words & item_keywords
            keyword_match = any(k in query.lower() for k in item_keywords)
            text_match = item.value.get("text", "").lower() in query.lower() or query.lower() in item.value.get("text", "").lower()
            
            if overlap or keyword_match or text_match:
                result.append(item)
        except Exception:
            continue
            
    return result


def record_outcome(
    tool_call: ToolCall | None,
    result_text: str,
    artifact_id: str | None,
    run_id: str,
    goal_id: str | None,
) -> None:
    """Record a tool execution outcome as a MemoryItem in the memory file."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Simple keyword extraction from tool name, arguments, and result text
    words = []
    if tool_call is not None:
        words.append(tool_call.name)
        for k, v in tool_call.arguments.items():
            words.append(k)
            words.append(str(v))
    if result_text:
        words.extend(result_text.split())
    keywords = list(set([
        w.strip(".,?!;:()\"'").lower() 
        for w in words 
        if len(w) > 3 and w.strip(".,?!;:()\"'").lower() not in STOP_WORDS
    ]))
    
    if tool_call is not None:
        desc = f"Called {tool_call.name} -> {result_text[:40]}..." if len(result_text) > 40 else f"Called {tool_call.name} -> {result_text}"
    else:
        desc = f"Outcome -> {result_text[:40]}..." if len(result_text) > 40 else f"Outcome -> {result_text}"
    
    item = MemoryItem(
        id=f"mem_{uuid.uuid4().hex[:8]}",
        kind="tool_outcome",
        keywords=keywords,
        descriptor=desc,
        value={
            "tool": tool_call.name if tool_call else None,
            "arguments": tool_call.arguments if tool_call else {},
            "result": result_text
        },
        artifact_id=artifact_id,
        source="tool_execution",
        run_id=run_id,
        goal_id=goal_id,
        confidence=1.0,
        created_at=datetime.now()
    )
    
    # Load existing items
    items = []
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
                if not isinstance(items, list):
                    items = []
        except Exception:
            items = []
            
    items.append(item.model_dump(mode="json"))
    
    # Write back
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
        
    print(f"Memory: Recorded outcome {item}")