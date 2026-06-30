import os
import json

TEMP_DIR = os.path.join(os.path.dirname(__file__), ".temp")
MAPPING_FILE = os.path.join(TEMP_DIR, "mapping.json")

def _load_mapping() -> dict:
    if not os.path.exists(MAPPING_FILE):
        return {}
    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_mapping(mapping: dict):
    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

def create(content: bytes, filename: str) -> str:
    """Store the artifact in .temp folder under a unique filename, assign an incremental ID, and save mapping."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Load existing mapping to determine the next incremental integer ID
    mapping = _load_mapping()
    existing_ids = []
    for k in mapping.keys():
        try:
            existing_ids.append(int(k))
        except ValueError:
            pass
    next_id = max(existing_ids) + 1 if existing_ids else 1
    artifact_id = str(next_id)
    
    # Ensure every artifact has its own different file
    unique_filename = f"{artifact_id}_{filename}"
    dest_path = os.path.join(TEMP_DIR, unique_filename)
    with open(dest_path, "wb") as f:
        f.write(content)
        
    # Update mapping: ID to the unique filename
    mapping[artifact_id] = unique_filename
    _save_mapping(mapping)
    
    return artifact_id

def create_from_file(file_path: str) -> str:
    """Helper method to create an artifact directly from a file path."""
    with open(file_path, "rb") as f:
        content = f.read()
    filename = os.path.basename(file_path)
    return create(content, filename)

def exists(artifact_id) -> bool:
    """Check if an artifact with the given ID exists and its file is present."""
    if artifact_id is None:
        return False
    mapping = _load_mapping()
    key = str(artifact_id)
    if key not in mapping:
        return False
    filename = mapping[key]
    file_path = os.path.join(TEMP_DIR, filename)
    return os.path.exists(file_path)

def get_bytes(artifact_id) -> bytes:
    """Retrieve the bytes of the artifact corresponding to the given ID."""
    mapping = _load_mapping()
    key = str(artifact_id)
    if key not in mapping:
        raise KeyError(f"Artifact ID '{artifact_id}' not found.")
    filename = mapping[key]
    file_path = os.path.join(TEMP_DIR, filename)
    with open(file_path, "rb") as f:
        return f.read()

class ArtifactStore:
    @staticmethod
    def put(content: bytes | str) -> int:
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content
        # Use a generic filename; the create function handles prefixing with next incremental ID
        artifact_id_str = create(content_bytes, "artifact.bin")
        return int(artifact_id_str)
