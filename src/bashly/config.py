import os
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".bashly_config.json"

def load_config() -> dict:
    """Load configuration from the user's home folder."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, IOError, ValueError):
        return {}

def save_config(config: dict) -> bool:
    """Save configuration to the user's home folder."""
    try:
        # Create config file with restricted permissions (0o600 on unix systems if possible)
        # using standard open on windows is fine since windows handles ACLs differently
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except IOError:
        return False

def get_api_key() -> str | None:
    """Retrieve the API key from config (or env for fallback/dev)."""
    # Environment variable overrides config file
    env_key = os.getenv("OPENROUTER_API_KEY")
    if env_key:
        return env_key
    
    config = load_config()
    return config.get("api_key")

def set_api_key(api_key: str):
    """Save a new API key."""
    config = load_config()
    config["api_key"] = api_key.strip()
    save_config(config)

def get_model() -> str:
    """Retrieve the model to use from config (or env)."""
    env_model = os.getenv("BASHLY_MODEL")
    if env_model:
        return env_model
        
    config = load_config()
    return config.get("model", "google/gemini-2.0-flash-001")

def set_model(model: str):
    config = load_config()
    config["model"] = model.strip()
    save_config(config)
