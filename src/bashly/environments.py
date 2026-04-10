from dataclasses import dataclass
import platform
import os
from bashly.prompts import COMMAND_SYSTEM_PROMPT, SHARED_RULES


@dataclass
class Environment:
    name: str           # Display name shown in the picker
    short: str          # Short label shown in the prompt (e.g. "Linux")
    executable: bool    # Can we actually run commands on this machine?
    system_prompt: str  # Instructions given to the LLM for this environment
    max_tokens: int = 300  # Max response tokens — lower = fewer tokens billed


def _build_prompt(env_instruction: str) -> str:
    """Helper to assemble the full system prompt from centralized pieces."""
    return f"{COMMAND_SYSTEM_PROMPT}\n{env_instruction}\n{SHARED_RULES}"


ENVIRONMENTS = [
    Environment(
        name="Windows (PowerShell)",
        short="Win/PS",
        executable=True,
        system_prompt=_build_prompt("PowerShell command generator. Use cmdlets (Get-ChildItem not ls)."),
    ),
    Environment(
        name="Windows (CMD)",
        short="Win/CMD",
        executable=True,
        system_prompt=_build_prompt("CMD command generator. No PowerShell syntax."),
    ),
    Environment(
        name="Linux (bash)",
        short="Linux",
        executable=True,
        system_prompt=_build_prompt("Bash command generator for Linux."),
    ),
    Environment(
        name="macOS (zsh)",
        short="macOS",
        executable=True,
        system_prompt=_build_prompt("Zsh command generator for macOS. Prefer macOS-native tools."),
    ),
    Environment(
        name="Android (Termux)",
        short="Termux",
        executable=False,
        system_prompt=_build_prompt("Termux command generator. Use pkg not apt."),
    ),
    Environment(
        name="MicroPython (ESP32 / Pi Pico)",
        short="MicroPy",
        executable=False,
        max_tokens=500,
        system_prompt=_build_prompt("MicroPython code generator for ESP32/Pi Pico. Use machine, utime, network modules. Keep concise."),
    ),
    Environment(
        name="Arduino CLI",
        short="Arduino",
        executable=False,
        system_prompt=_build_prompt("Arduino CLI command generator (compile, upload, board list)."),
    ),
    Environment(
        name="Raspberry Pi (bash + GPIO)",
        short="RPi",
        executable=False,
        max_tokens=500,
        system_prompt=_build_prompt("Bash + GPIO command generator for Raspberry Pi OS. Use raspi-gpio/gpiozero/RPi.GPIO for hardware."),
    ),
]

import os

# Auto-detect default environment based on current OS and active shell
def _detect_default_index() -> int:
    system = platform.system()
    if system == "Linux":
        return 2  # Linux (bash)
    elif system == "Darwin":
        return 3  # macOS (zsh)
    elif system == "Windows":
        # Check if we are inside a PowerShell process
        if "PSModulePath" in os.environ:
            return 0  # Windows (PowerShell)
        else:
            return 1  # Windows (CMD)
    return 0


def pick_environment() -> Environment:
    """
    Displays the environment picker with auto-detected default.
    Pressing Enter without a number selects the detected OS default.
    """
    default_idx = _detect_default_index()

    print("\n  Select target environment:\n")
    for i, env in enumerate(ENVIRONMENTS, 1):
        executable_note = "" if env.executable else "  [copy only]"
        marker = "  ← recommended" if i - 1 == default_idx else ""
        print(f"    [{i}] {env.name}{executable_note}{marker}")
    
    print()
    while True:
        raw = input(f"  Enter number [{default_idx + 1}]: ").strip()
        if not raw:
            return ENVIRONMENTS[default_idx]
        try:
            choice = int(raw)
            if 1 <= choice <= len(ENVIRONMENTS):
                return ENVIRONMENTS[choice - 1]
            else:
                print(f"  Please enter a number between 1 and {len(ENVIRONMENTS)}")
        except ValueError:
            print("  Please enter a valid number")