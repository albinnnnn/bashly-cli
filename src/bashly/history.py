import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

# History file lives in the user's home directory.
# Path.home() works on both Windows (C:\Users\albin) and Linux (/home/albin).
HISTORY_FILE = Path.home() / ".bashly_history.json"

# Maximum number of history entries to keep.
# Oldest entries are dropped when this limit is reached.
MAX_HISTORY = 500


def load_history() -> list:
    """
    Loads the full history from the JSON file.
    Returns an empty list if the file doesn't exist, is corrupt,
    or contains non-list data.
    """
    if not HISTORY_FILE.exists():
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError, ValueError):
        return []


def save_entry(request: str, command: str, status: str, env_name: str = "unknown"):
    """
    Appends a single entry to the history file.

    Uses atomic write (temp file → os.replace) to prevent corruption
    if the process is killed mid-write. Caps history at MAX_HISTORY entries.

    status is one of:
      - 'approved' — user ran or copied the command
      - 'denied'   — user skipped it
      - 'copied'   — user copied without running (executable envs only)
      - 'copied (danger-blocked)' — dangerous command, copied only

    env_name is the full environment name e.g. 'Linux (bash)'
    """
    history = load_history()

    entry = {
        "request": request,
        "command": command,
        "status": status,
        "env": env_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    history.append(entry)

    # Enforce max size — drop oldest entries
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    try:
        # Atomic write: write to temp file, then rename over the original.
        # This prevents corruption if the process is killed mid-write.
        parent = HISTORY_FILE.parent
        fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            # os.replace is atomic on both Windows and Unix
            os.replace(tmp_path, HISTORY_FILE)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except IOError as e:
        print(f"Warning: could not save history — {e}")


def get_recent(n: int = 10) -> list:
    """
    Returns the last n entries from history, most recent first.
    Used when the user types 'history' in Bashly.
    """
    history = load_history()
    return list(reversed(history[-n:]))


def clear_history():
    """
    Deletes all saved history.
    Called when the user types 'clear history'.
    """
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()