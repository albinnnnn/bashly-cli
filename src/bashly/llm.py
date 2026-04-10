import os
import re
from openai import OpenAI
from bashly.environments import Environment
from bashly.history import get_recent
from bashly.prompts import EXPLAIN_SYSTEM_PROMPT
from bashly import config

# Phrases that indicate the LLM slipped into conversational mode
# instead of generating a raw command. Only checked on responses that
# look like prose (>10 words), so short commands are not falsely rejected.
INJECTION_MARKERS = [
    "ignore previous",
    "ignore above",
    "disregard",
    "as an ai",
    "sure, here",
    "certainly!",
    "of course!",
    "i'm sorry",
    "i apologize",
    "happy to help",
]

# Directories to skip when listing CWD contents (saves tokens)
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}


def _get_cwd_files() -> str:
    """
    List files in CWD (2 levels deep) for the LLM to match against.
    Skips noisy directories. Uses forward slashes for consistency.
    Returns descriptive fallback if CWD is empty or listing fails.
    """
    try:
        entries = []
        cwd = os.getcwd()
        cwd_len = len(cwd)
        for root, dirs, files in os.walk(cwd):
            # Safe depth calculation — count separators in the suffix only
            suffix = root[cwd_len:]
            depth = suffix.count(os.sep) if suffix else 0
            if depth >= 2:
                dirs.clear()
                continue
            # Prune noisy directories in-place so os.walk skips them
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for name in sorted(files):
                rel = os.path.relpath(os.path.join(root, name), cwd)
                entries.append(rel.replace("\\", "/"))
        # Cap at 80 entries to prevent token bloat in large projects
        if len(entries) > 80:
            entries = entries[:80] + [f"…+{len(entries) - 80} more"]
        return ", ".join(entries) if entries else "(empty directory)"
    except Exception:
        return "(could not list files)"


def _sanitize_input(user_request: str) -> str:
    """
    Strip sequences commonly used in prompt injection.
    Only removes role markers at the START of a line (^) to avoid
    stripping legitimate mid-sentence uses like 'show system: uptime'.
    """
    # Only strip role markers at line start (injection attempt pattern)
    sanitized = re.sub(
        r"^(system|assistant|user)\s*:", "", user_request, flags=re.IGNORECASE | re.MULTILINE
    )
    sanitized = re.sub(r"^#{1,6}\s+", "", sanitized, flags=re.MULTILINE)
    return sanitized.strip()


def _validate_output(response_text: str) -> str | None:
    """
    Check the LLM output for signs that prompt injection succeeded.
    Only applies injection markers to responses that look like natural
    language (>10 words), so short commands like `echo "I cannot"` are
    not falsely rejected.
    """
    # Reject excessively long responses (likely conversational)
    if len(response_text) > 2000:
        return None

    # Only check injection markers on prose-like responses
    word_count = len(response_text.split())
    if word_count > 10:
        lower = response_text.lower()
        for marker in INJECTION_MARKERS:
            if marker in lower:
                return None

    return response_text


def _clean_llm_response(raw: str) -> str:
    """
    Cleans up the raw LLM response:
      1. Strips markdown code fences
      2. Removes any standalone CANNOT_GENERATE lines (LLM hedging)
      3. Returns CANNOT_GENERATE if nothing remains
    """
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    # If the entire response is CANNOT_GENERATE, pass through
    if text == "CANNOT_GENERATE":
        return text

    # Remove standalone CANNOT_GENERATE lines (LLM returning command + hedging)
    lines = [line for line in text.split("\n") if line.strip() != "CANNOT_GENERATE"]
    if not lines:
        return "CANNOT_GENERATE"

    return "\n".join(lines).strip()


def _get_session_context() -> str:
    """
    Returns the last 3 approved/copied commands as compact context.
    Lets the LLM understand references like 'the previous file'.
    Costs ~30 extra tokens per call — worth it for continuity.
    """
    try:
        recent = get_recent(3)
        if not recent:
            return ""
        lines = []
        for entry in recent:
            if entry["status"] in ("approved", "copied", "copied (danger-blocked)"):
                lines.append(f"{entry['request']} → {entry['command']}")
        if not lines:
            return ""
        return "[History: " + "; ".join(lines) + "]"
    except Exception:
        return ""


def get_command(user_request: str, env: Environment) -> str:
    """
    Takes the user's plain English request and the selected environment,
    returns the appropriate command or code snippet.

    Token-efficient design:
      - Compact system prompt (shared rules + env-specific line)
      - CWD + file listing + session history as short prefixes
      - max_tokens capped per environment (300 for shell, 500 for code)
      - Fast model by default (configurable via BASHLY_MODEL)
    """
    clean_request = _sanitize_input(user_request)

    if not clean_request:
        return "CANNOT_GENERATE"

    # Build context: CWD, file listing, and recent session history
    cwd = os.getcwd()
    files = _get_cwd_files()
    history = _get_session_context()
    user_content = f"[CWD: {cwd}]\n[Files: {files}]\n{history}\n{clean_request}".strip()

    try:
        api_key = config.get_api_key()
        if not api_key:
            return "ERROR: API Key is missing. Run `api config` or restart the app to set it."

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        
        response = client.chat.completions.create(
            model=config.get_model(),
            messages=[
                {"role": "system", "content": env.system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=env.max_tokens,
        )

        # Null-safe response handling
        if not response.choices or not response.choices[0].message.content:
            return "CANNOT_GENERATE"

        raw = response.choices[0].message.content.strip()

        # Clean up the response (strip fences, remove stray CANNOT_GENERATE lines)
        command = _clean_llm_response(raw)

        # Validate output for prompt injection
        validated = _validate_output(command)
        if validated is None:
            return "CANNOT_GENERATE"

        return validated

    except Exception as e:
        return f"ERROR: {str(e)}"


def get_explanation(command: str) -> str:
    """
    Explains a command or code snippet in plain English.
    Called when the user presses '?' before approving.
    """
    try:
        api_key = config.get_api_key()
        if not api_key:
            return "Could not explain: API Key is missing."

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

        response = client.chat.completions.create(
            model=config.get_model(),
            messages=[
                {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
                {"role": "user", "content": command},
            ],
            max_tokens=200,
        )

        if not response.choices or not response.choices[0].message.content:
            return "Could not generate an explanation."

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Could not explain: {str(e)}"
