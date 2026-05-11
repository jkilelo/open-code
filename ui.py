"""Output rendering for open-code -- rich on a TTY, plain otherwise.

Three modes:
    rich   -- ANSI colors + Unicode box drawing via the `rich` library.
              The default when stderr is a TTY and NO_COLOR isn't set.
    plain  -- ASCII-only, no ANSI escapes. The default when output is
              piped or when --plain is passed. Also forced when the
              NO_COLOR env var is set (per https://no-color.org/).
    json   -- structured JSON-lines (existing --print mode in
              open_code._emit_json). UI calls become no-ops; the
              caller's _emit_json drives the output.

Source-side discipline: this module is pure ASCII. Rich's box-drawing
characters appear only in runtime output, never as literal source
chars -- they come out of the `rich` library's own data files.

Honest trade-offs:
- rich is now a runtime dependency. We pin >=14.0 because that's the
  current stable line (the v13 -> v14 break primarily affected
  internal API; the public Console / Text / Panel / Table surfaces
  we use are stable from v12+).
- We do NOT integrate prompt_toolkit's input side here. That's a
  bigger refactor (replaces every `input()` call in repl.py); slated
  as a follow-up if the user wants it after seeing this.
- Rich's Markdown render is opt-in via `markdown=True`. By default
  model_text uses plain `print` so model output stays diff-clean for
  test assertions and pipe-friendly output.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

MODE_RICH = "rich"
MODE_PLAIN = "plain"
MODE_JSON = "json"

VALID_MODES = (MODE_RICH, MODE_PLAIN, MODE_JSON)


def detect_mode(
    *,
    plain_override: bool = False,
    json_override: bool = False,
    stream: TextIO | None = None,
) -> str:
    """Pick a mode given environment + user flags.

    Precedence (highest first):
      1. --print  (json_override)         -> json
      2. --plain  (plain_override)        -> plain
      3. NO_COLOR or OPEN_CODE_PLAIN env  -> plain
      4. stream isn't a TTY               -> plain
      5. fallback                         -> rich
    """
    if json_override:
        return MODE_JSON
    if plain_override:
        return MODE_PLAIN
    if os.environ.get("NO_COLOR"):
        return MODE_PLAIN
    if os.environ.get("OPEN_CODE_PLAIN"):
        return MODE_PLAIN
    if stream is None:
        stream = sys.stderr
    try:
        if not stream.isatty():
            return MODE_PLAIN
    except (AttributeError, OSError):
        return MODE_PLAIN
    return MODE_RICH


def _short(s: str, n: int = 100) -> str:
    s = str(s)
    if len(s) <= n:
        return s
    return s[: n - 1] + "..."


def _short_args(args: dict[str, Any], n: int = 60) -> str:
    """Compact one-line representation of tool args."""
    try:
        return _short(json.dumps(args, default=str), n)
    except (TypeError, ValueError):
        return _short(str(args), n)


def _result_summary(name: str, result: dict[str, Any]) -> str:
    """One-line summary string for a tool result."""
    if not result.get("ok"):
        return f"error: {result.get('error', 'unknown')}"
    if name == "read_file":
        return f"{result.get('size', '?')} bytes"
    if name == "write_file":
        return (
            f"wrote {result.get('bytes_written', '?')} bytes to "
            f"{result.get('path', '?')}"
        )
    if name == "list_dir":
        entries = result.get("entries", [])
        return f"{len(entries)} entries"
    if name == "run_shell":
        return (
            f"exit={result.get('exit_code', '?')}, stdout: "
            f"{_short(result.get('stdout', ''), 60)}"
        )
    return "ok"


class UI:
    """Output renderer. Pick a mode at construction; all methods route
    through it.

    Instances are cheap to create. The rich Console (when used) is
    lazy: it's not built until the first rich call, so plain-mode
    callers don't pay the import cost.
    """

    def __init__(
        self,
        mode: str = MODE_RICH,
        *,
        quiet: bool = False,
        stderr: bool = True,
    ) -> None:
        if mode not in VALID_MODES:
            mode = MODE_PLAIN
        self.mode = mode
        self.quiet = quiet
        self._stderr = stderr
        self._console: Any = None  # lazy rich.console.Console

    @classmethod
    def auto(
        cls,
        *,
        plain: bool = False,
        json_mode: bool = False,
        quiet: bool = False,
        stderr: bool = True,
    ) -> "UI":
        stream = sys.stderr if stderr else sys.stdout
        mode = detect_mode(
            plain_override=plain,
            json_override=json_mode,
            stream=stream,
        )
        return cls(mode=mode, quiet=quiet, stderr=stderr)

    @property
    def is_rich(self) -> bool:
        return self.mode == MODE_RICH

    @property
    def is_plain(self) -> bool:
        return self.mode == MODE_PLAIN

    @property
    def is_json(self) -> bool:
        return self.mode == MODE_JSON

    @property
    def _stream(self) -> TextIO:
        return sys.stderr if self._stderr else sys.stdout

    def _rich_console(self) -> Any:
        if self._console is None and self.mode == MODE_RICH:
            from rich.console import Console
            self._console = Console(
                file=self._stream,
                # Let rich auto-detect color support. Setting
                # force_terminal=True here would defeat NO_COLOR
                # downstream tools, so we leave it None.
                highlight=False,
                soft_wrap=True,
            )
        return self._console

    # ---- core output methods ----

    def line(self, text: str = "") -> None:
        """Plain literal line, no decoration."""
        if self.mode == MODE_JSON:
            return
        self._stream.write(text + "\n")

    def info(self, msg: str) -> None:
        """Verbose-mode trace line. Suppressed by quiet."""
        if self.quiet or self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(f"[dim]{msg}[/dim]")
        else:
            self._stream.write(f"{msg}\n")

    def warn(self, msg: str) -> None:
        """Non-fatal warning."""
        if self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(f"[yellow]\\[warn][/yellow] {msg}")
        else:
            self._stream.write(f"[warn] {msg}\n")

    def error(self, msg: str) -> None:
        """Error line. Always printed (even in quiet mode) except JSON."""
        if self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(f"[red bold]\\[error][/red bold] {msg}")
        else:
            self._stream.write(f"[error] {msg}\n")

    def tool_call(self, name: str, args: dict[str, Any]) -> None:
        """Render a model-issued tool invocation."""
        if self.quiet or self.mode == MODE_JSON:
            return
        short = _short_args(args, 80)
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(
                f"  [bold cyan]->[/bold cyan] "
                f"[bold]{name}[/bold]"
                f"[dim]({short})[/dim]"
            )
        else:
            self._stream.write(f"  -> {name}({short})\n")

    def tool_result(self, name: str, result: dict[str, Any]) -> None:
        """Render a tool result, OK or error."""
        if self.quiet or self.mode == MODE_JSON:
            return
        ok = bool(result.get("ok"))
        summary = _result_summary(name, result)
        if self.mode == MODE_RICH:
            c = self._rich_console()
            tag = (
                "[green bold][OK][/green bold]"
                if ok
                else "[red bold][X][/red bold]"
            )
            colour = "" if ok else "red"
            text = (
                f"  {tag} [cyan]{name}[/cyan]"
                + (f" [{colour}]-> {summary}[/{colour}]" if colour
                   else f" -> {summary}")
            )
            c.print(text)
        else:
            tag = "[OK]" if ok else "[X]"
            self._stream.write(f"  {tag} {name} -> {summary}\n")

    def status_line(self, **fields: Any) -> None:
        """One-line status footer (model / iter / tokens / etc)."""
        if self.quiet or self.mode == MODE_JSON:
            return
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(f"  [dim]\\[{kv}\\][/dim]")
        else:
            self._stream.write(f"  [{kv}]\n")

    def model_text(self, text: str, *, markdown: bool = False) -> None:
        """Render the assistant's plain-text response.

        Defaults to literal stdout write -- callers that want markdown
        rendering opt in. Rationale: tests + pipes prefer raw text.
        """
        if self.mode == MODE_JSON:
            return
        if markdown and self.mode == MODE_RICH:
            try:
                from rich.markdown import Markdown
                c = self._rich_console()
                c.print(Markdown(text))
                return
            except Exception:
                pass  # fall back to plain
        # Always to stdout (the agent's actual response), not stderr.
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    def banner(self, *, session_id: str, cwd: str,
               model: str = "") -> None:
        """REPL session banner."""
        if self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            try:
                from rich.panel import Panel
                from rich.text import Text
                c = self._rich_console()
                body = Text()
                body.append("open-code", style="bold cyan")
                body.append(" -- Gemini coding agent (REPL)\n")
                body.append("Session ", style="dim")
                body.append(session_id, style="yellow")
                body.append(" in ", style="dim")
                body.append(cwd, style="dim")
                if model:
                    body.append("\nModel: ", style="dim")
                    body.append(model)
                body.append(
                    "\nType your task, /help for commands, "
                    "/exit (or Ctrl+D) to leave.",
                    style="dim",
                )
                c.print(Panel(body, border_style="cyan", expand=False))
                return
            except Exception:
                pass
        out = (
            "open-code -- Gemini coding agent (REPL mode)\n"
            f"Session {session_id} in {cwd}\n"
        )
        if model:
            out += f"Model: {model}\n"
        out += (
            "Type your task, /help for commands, /exit (or Ctrl+D) to leave.\n"
        )
        self._stream.write(out + "\n")

    def table(self, *, title: str, columns: list[str],
              rows: list[list[str]]) -> None:
        """Render a list-of-rows as a table (sessions, skills, etc)."""
        if self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            try:
                from rich.table import Table
                c = self._rich_console()
                t = Table(title=title, show_lines=False,
                          header_style="bold cyan")
                for col in columns:
                    t.add_column(col)
                for row in rows:
                    t.add_row(*[str(x) for x in row])
                c.print(t)
                return
            except Exception:
                pass
        # Plain ASCII table
        widths = [
            max(len(c), *(len(str(row[i])) for row in rows))
            if rows else len(c)
            for i, c in enumerate(columns)
        ]
        sep = "  ".join("-" * w for w in widths)
        header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
        self._stream.write(f"{title}\n{header}\n{sep}\n")
        for row in rows:
            line = "  ".join(
                str(x).ljust(w) for x, w in zip(row, widths)
            )
            self._stream.write(line + "\n")
