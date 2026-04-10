import subprocess
import re
import os

# Timeout for command execution (seconds).
# Configurable via BASHLY_TIMEOUT env var.
COMMAND_TIMEOUT = int(os.getenv("BASHLY_TIMEOUT", "60"))


# (regex_pattern, human_readable_label)
# Dangerous = red warning, execution blocked.
# Uses word boundaries (\b) to avoid false positives like "model" matching "del".
DANGEROUS_PATTERNS = [
    (r"\brm\s+-rf\b", "rm -rf"),
    (r"\brm\s+-r\b", "rm -r"),
    (r"\brmdir\s+/s\b", "rmdir /s"),
    (r"\bdel\s+/f\s+/s\b", "del /f /s"),
    (r"\bdel\s+/s\b", "del /s"),
    (r"\bsudo\s+rm\b", "sudo rm"),
    (r"\bdd\s+if=", "dd if="),
    (r"\bmkfs\b", "mkfs"),
    (r":\(\)\{", "fork bomb"),
    (r"\bchmod\s+777\b", "chmod 777"),
    (r"\bchmod\s+-R\s+777\b", "chmod -R 777"),
    (r">\s*/dev/sd[a-z]", "> /dev/sda"),
    (r"\bformat\s+[a-z]:", "format drive"),
    (r"\bshutdown\b", "shutdown"),
    (r"\breboot\b", "reboot"),
    (r"\bcurl\b.*\|\s*\bbash\b", "curl | bash"),
    (r"\bwget\b.*\|\s*\bbash\b", "wget | bash"),
    # PowerShell dangerous operations
    (r"-recurse.*-force", "-Recurse -Force"),
    (r"-force.*-recurse", "-Force -Recurse"),
    (r"\bremove-item\b.*-recurse", "Remove-Item -Recurse"),
    (r"\bremove-item\b.*\s-r\b", "Remove-Item -R"),
    (r"\binvoke-expression\b", "Invoke-Expression"),
    (r"\biex\b", "iex"),
    (r"-encodedcommand\b", "-EncodedCommand"),
    (r"\bstart-process\b", "Start-Process"),
]

# Caution = yellow warning, execution allowed.
CAUTION_PATTERNS = [
    (r"\bsudo\b", "sudo"),
    (r"\bchmod\b", "chmod"),
    (r"\bchown\b", "chown"),
    (r"\bkill\b", "kill"),
    (r"\bpkill\b", "pkill"),
    (r"\btaskkill\b", "taskkill"),
    (r"\bnet\s+user\b", "net user"),
    (r"\breg\s+delete\b", "reg delete"),
    (r"\bremove-item\b", "Remove-Item"),
    (r"\brmdir\b", "rmdir"),
    (r"\bunlink\b", "unlink"),
    (r"\brm\b", "rm"),
    (r"\bdel\b", "del"),
]

# Precompile for performance
_DANGER_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in DANGEROUS_PATTERNS]
_CAUTION_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in CAUTION_PATTERNS]

# Interactive commands that hang with captured output
_INTERACTIVE_RE = re.compile(
    r"^\s*(?:python3?|node|irb|ssh|nano|vim?|emacs|less|more|top|htop|cmd|powershell|bash|zsh|nslookup|ftp|telnet)\s*$",
    re.IGNORECASE,
)


def _normalize(command: str) -> str:
    """
    Normalize command for pattern matching.
    - Removes PowerShell backtick escaping (e.g. Remove-`Item → Remove-Item)
    - Collapses all whitespace to single spaces
    """
    normalized = command.replace("`", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def check_danger(command: str) -> dict:
    """
    Scans the command for dangerous or cautionary patterns.
    Returns a dict with:
      - level: 'safe', 'caution', or 'danger'
      - reason: why it was flagged (or None if safe)

    Uses regex with word boundaries to prevent false positives
    (e.g. 'model' no longer matches 'del'). Normalizes whitespace
    and strips PowerShell backtick escaping before checking.
    """
    normalized = _normalize(command)

    for pattern_re, label in _DANGER_COMPILED:
        if pattern_re.search(normalized):
            return {"level": "danger", "reason": f"contains '{label}'"}

    for pattern_re, label in _CAUTION_COMPILED:
        if pattern_re.search(normalized):
            return {"level": "caution", "reason": f"contains '{label}'"}

    return {"level": "safe", "reason": None}


def is_interactive(command: str) -> bool:
    """
    Check if a command is likely interactive (REPL, editor, pager)
    that would hang if executed with captured output.
    """
    first_cmd = re.split(r"[;&|]", command)[0].strip()
    return bool(_INTERACTIVE_RE.search(first_cmd))


def run_command(command: str, is_powershell: bool = False) -> dict:
    """
    Executes the command using subprocess.
    Returns a dict with:
      - success: True/False
      - output: stdout text
      - error: stderr text
      - exit_code: integer return code

    shell=True is used so that shell builtins like 'cd', pipes '|',
    and redirects '>' work correctly. This is intentional here since
    the user has explicitly approved the command.

    Timeout is configurable via BASHLY_TIMEOUT env var (default: 60s).
    """
    try:
        if is_powershell:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
        else:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )

        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"Command timed out after {COMMAND_TIMEOUT} seconds.",
            "exit_code": -1,
        }

    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "exit_code": -1,
        }