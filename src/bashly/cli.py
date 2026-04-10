from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from rich import box
import sys
import platform
import pyperclip

from bashly.llm import get_command, get_explanation
from bashly.executor import check_danger, run_command, is_interactive
from bashly.history import save_entry, get_recent, clear_history
from bashly.environments import pick_environment, Environment
from bashly import config

console = Console()

# Map OS to expected environment names for mismatch detection
_OS_ENV_MAP = {
    "Windows": {"Windows (PowerShell)", "Windows (CMD)"},
    "Linux": {"Linux (bash)"},
    "Darwin": {"macOS (zsh)"},
}


def print_welcome():
    """Prints the welcome banner when Bashly starts."""
    api_status = "[green]Active[/green]" if config.get_api_key() else "[red]Missing[/red]"
    console.print(Panel.fit(
        "[bold cyan]Bashly[/bold cyan] — AI-powered cross-environment terminal assistant\n"
        f"[dim]API Key Status: {api_status}\n"
        "Type your request in plain English.\n"
        "Commands: [bold]help[/bold] · [bold]history[/bold] · [bold]switch env[/bold] · [bold]api key[/bold] · [bold]exit[/bold][/dim]",
        border_style="cyan"
    ))


def print_help():
    """Displays available commands as a styled table."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Command", style="bold white", width=18)
    table.add_column("Description", style="dim white")
    table.add_row("help", "Show this help message")
    table.add_row("history", "Show last 10 commands")
    table.add_row("clear history", "Delete all saved history")
    table.add_row("api key", "Add or update your OpenRouter API key")
    table.add_row("switch env", "Change target environment")
    table.add_row("sysinfo", "Show current system and OS info")
    table.add_row("exit", "Quit Bashly")
    table.add_row("[dim]anything else[/dim]", "[dim]Describe what you want in plain English[/dim]")
    console.print(table)


def print_command_panel(command: str, danger: dict, env: Environment):
    """
    Displays the suggested command in a styled panel.
    Uses rich Syntax highlighting for MicroPython and Arduino (code-like output).
    Color changes based on danger level.
    """
    # Pick syntax highlighting language
    # MicroPython output is Python code, everything else is shell
    if "MicroPython" in env.name:
        highlight_lang = "python"
    elif "Arduino" in env.name:
        highlight_lang = "cpp"
    else:
        highlight_lang = "bash"

    # Pick border color based on danger level
    if danger["level"] == "danger":
        border_color = "red"
        header = f"[bold red]⚠  DANGEROUS — {danger['reason']}[/bold red]"
    elif danger["level"] == "caution":
        border_color = "yellow"
        header = f"[bold yellow]⚡ Caution — {danger['reason']}[/bold yellow]"
    else:
        border_color = "green"
        header = f"[bold green]✓  Suggested ({env.short})[/bold green]"

    console.print(f"\n{header}")

    # Syntax highlighted command block
    syntax = Syntax(command, highlight_lang, theme="monokai", word_wrap=True)
    console.print(Panel(syntax, border_style=border_color, box=box.ROUNDED))


def print_history():
    """Renders the last 10 commands as a rich table."""
    entries = get_recent(10)

    if not entries:
        console.print("[dim]No history yet.[/dim]")
        return

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Time", style="dim", width=20)
    table.add_column("Env", style="cyan", width=10)
    table.add_column("Request", style="white")
    table.add_column("Command", style="cyan")
    table.add_column("Status", width=16)

    for entry in entries:
        status = entry["status"]
        if status in ("approved", "copied"):
            status_color = "green"
        elif status == "copied (danger-blocked)":
            status_color = "yellow"
        else:  # "denied"
            status_color = "red"
        table.add_row(
            entry["timestamp"],
            entry.get("env", "unknown"),
            entry["request"],
            entry["command"],
            f"[{status_color}]{status}[/{status_color}]",
        )

    console.print(table)


def _copy_to_clipboard(command: str):
    """
    Copies command to clipboard. If pyperclip fails (headless, SSH, WSL),
    shows the command text for manual copying instead of silently failing.
    """
    try:
        pyperclip.copy(command)
        console.print("[green]Copied to clipboard.[/green]")
    except Exception:
        console.print(
            "[yellow]Could not access clipboard. Copy the command manually:[/yellow]\n"
            f"[bold white]{command}[/bold white]"
        )


def _check_os_mismatch(env: Environment):
    """
    Warn if the user selected an executable environment that doesn't
    match the current OS (e.g. Linux on a Windows machine).
    """
    current_os = platform.system()
    expected_envs = _OS_ENV_MAP.get(current_os, set())

    if env.executable and expected_envs and env.name not in expected_envs:
        console.print(
            f"[yellow]⚠ Warning: you selected [bold]{env.name}[/bold] "
            f"but you're on [bold]{current_os}[/bold]. "
            "Commands may fail or behave unexpectedly.[/yellow]"
        )


def handle_approval(command: str, user_request: str, env: Environment, danger: dict):
    """
    Shows the approve/deny/explain/copy prompt and handles the user's choice.

    If the command is DANGEROUS and environment is executable:
      Direct execution is blocked. User can only copy or skip.
      Options: [c] Copy  [n] Skip  [?] Explain

    If the environment is executable and command is safe/caution:
      Options: [y] Run  [n] Skip  [c] Copy  [?] Explain

    If the environment is NOT executable (MicroPython, Arduino, Termux, RPi):
      Options: [y] Copy  [n] Skip  [?] Explain
    """
    is_blocked = env.executable and danger["level"] == "danger"

    while True:
        if is_blocked:
            # Dangerous command — block direct execution entirely
            console.print(
                f"\n[bold red]⛔ Direct execution blocked — {danger['reason']}[/bold red]\n"
                "[dim]Review the command carefully. You may copy it and run manually if you're sure.[/dim]"
            )
            console.print(
                "\n[bold]"
                "[[cyan]c[/cyan]] Copy to clipboard  "
                "[[red]n[/red]] Skip  "
                "[[yellow]?[/yellow]] Explain"
                "[/bold]"
            )
            choice = Prompt.ask("Your choice", choices=["c", "n", "?"], default="n")
        elif env.executable:
            console.print(
                "\n[bold]"
                "[[green]y[/green]] Run  "
                "[[red]n[/red]] Skip  "
                "[[cyan]c[/cyan]] Copy  "
                "[[yellow]?[/yellow]] Explain"
                "[/bold]"
            )
            choice = Prompt.ask("Your choice", choices=["y", "n", "c", "?"], default="n")
        else:
            # Non-executable environments — can only copy or skip
            console.print(
                f"\n[dim]This command targets [bold]{env.name}[/bold] — cannot run locally.[/dim]"
            )
            console.print(
                "\n[bold]"
                "[[green]y[/green]] Copy to clipboard  "
                "[[red]n[/red]] Skip  "
                "[[yellow]?[/yellow]] Explain"
                "[/bold]"
            )
            choice = Prompt.ask("Your choice", choices=["y", "n", "?"], default="n")

        # --- Handle the chosen action ---

        if choice == "y" and env.executable and not is_blocked:
            # Check for interactive commands that would hang
            if is_interactive(command):
                console.print(
                    "[yellow]⚠ This looks like an interactive command (REPL, editor, etc.) "
                    "that may hang. Consider copying and running it manually.[/yellow]"
                )
                if not Confirm.ask("Run anyway?", default=False):
                    _copy_to_clipboard(command)
                    save_entry(user_request, command, "copied", env.name)
                    break

            # Run the command locally (only for safe/caution commands)
            console.print("\n[dim]Running...[/dim]\n")
            result = run_command(command, is_powershell=("PowerShell" in env.name))

            if result["output"]:
                console.print(result["output"])

            if result["error"]:
                console.print(f"[red]{result['error']}[/red]")

                # Contextual hint for file/path errors
                err = result["error"].lower()
                if any(p in err for p in [
                    "not found", "cannot find", "no such file",
                    "does not exist", "not recognized", "path not found"
                ]):
                    console.print(
                        "[dim yellow]💡 Tip: try specifying the full path or "
                        "directory (e.g. 'delete C:\\\\path\\\\to\\\\file').[/dim yellow]"
                    )

            if not result["success"]:
                console.print(f"[red]Exit code: {result['exit_code']}[/red]")

            save_entry(user_request, command, "approved", env.name)
            break

        elif choice == "y" and not env.executable:
            # Copy to clipboard for non-executable environments
            _copy_to_clipboard(command)
            save_entry(user_request, command, "approved", env.name)
            break

        elif choice == "c":
            # Copy without running (executable envs and danger-blocked commands)
            _copy_to_clipboard(command)
            status = "copied (danger-blocked)" if is_blocked else "copied"
            save_entry(user_request, command, status, env.name)
            break

        elif choice == "n":
            console.print("[dim]Skipped.[/dim]")
            save_entry(user_request, command, "denied", env.name)
            break

        elif choice == "?":
            # Explain mode — ask LLM what the command does, then loop back
            console.print("\n[dim]Explaining...[/dim]")
            explanation = get_explanation(command)
            console.print(Panel(
                f"[white]{explanation}[/white]",
                title="[cyan]What this does[/cyan]",
                border_style="cyan"
            ))
            # Loop back to show approve/deny again


def main():
    # Setup Wizard: If no API key exists, prompt the user before starting.
    if not config.get_api_key():
        console.print(Panel(
            "[bold white]Welcome to Bashly![/bold white]\n\n"
            "To generate commands, you need an OpenRouter API key.\n"
            "You can get one for free at: [cyan]https://openrouter.ai/keys[/cyan]",
            border_style="magenta",
            title="First Time Setup"
        ))
        
        while True:
            new_key = Prompt.ask("\nPaste your API key here (or type 'exit' to quit)")
            if new_key.lower().strip() == 'exit':
                sys.exit(0)
            if new_key.strip():
                config.set_api_key(new_key.strip())
                console.print("[green]API Key saved successfully![/green]\n")
                break
            else:
                console.print("[red]API Key cannot be empty.[/red]")
                
    print_welcome()

    # Environment selection on startup (auto-detects OS default)
    env = pick_environment()
    console.print(f"\n[dim]Environment set to:[/dim] [bold cyan]{env.name}[/bold cyan]\n")

    # Warn if the selected environment doesn't match the current OS
    _check_os_mismatch(env)

    while True:
        try:
            user_request = console.input(
                f"\n[bold cyan]Bashly[/bold cyan] [dim]({env.short})[/dim][bold cyan] >[/bold cyan] "
            ).strip()

            if not user_request:
                continue

            # Built-in commands
            lower = user_request.lower()

            if lower == "exit":
                console.print("[dim]Goodbye.[/dim]")
                sys.exit(0)

            if lower == "help":
                print_help()
                continue

            if lower == "history":
                print_history()
                continue

            if lower == "clear history":
                if Confirm.ask("[yellow]Delete all history?[/yellow]", default=False):
                    clear_history()
                    console.print("[dim]History cleared.[/dim]")
                else:
                    console.print("[dim]Cancelled.[/dim]")
                continue
                
            if lower == "api key":
                new_key = Prompt.ask("\n[bold]Paste your new OpenRouter API key[/bold] (leave blank to cancel)")
                if new_key.strip():
                    config.set_api_key(new_key.strip())
                    console.print("[green]API Key updated successfully![/green]")
                else:
                    console.print("[dim]Cancelled. API Key was not changed.[/dim]")
                continue

            if lower == "sysinfo":
                console.print(
                    f"\n[bold cyan]System Information[/bold cyan]\n"
                    f"  OS:        [white]{platform.system()} {platform.release()}[/white]\n"
                    f"  Arch:      [white]{platform.machine()}[/white]\n"
                    f"  Python:    [white]v{platform.python_version()}[/white]\n"
                )
                continue

            if lower == "switch env":
                # Let the user change environment mid-session without restarting
                env = pick_environment()
                console.print(f"\n[dim]Switched to:[/dim] [bold cyan]{env.name}[/bold cyan]")
                _check_os_mismatch(env)
                continue

            # Step 1: Call LLM
            console.print("[dim]Thinking...[/dim]")
            command = get_command(user_request, env)

            # Step 2: Handle errors
            if command.startswith("ERROR:"):
                console.print(f"[red]{command}[/red]")
                continue

            if command == "CANNOT_GENERATE":
                console.print(
                    "[yellow]Bashly couldn't generate a command for that request. "
                    "Try rephrasing.[/yellow]"
                )
                continue

            # Step 3: Danger check (skip for non-executable targets — no risk of running)
            if env.executable:
                danger = check_danger(command)
            else:
                danger = {"level": "safe", "reason": None}

            # Step 4: Display the command
            print_command_panel(command, danger, env)

            # Step 5: Approve / deny / copy / explain
            handle_approval(command, user_request, env, danger)

        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Type 'exit' to quit.[/dim]")
            continue


if __name__ == "__main__":
    main()