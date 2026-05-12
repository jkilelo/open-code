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
        # prompt_toolkit session is built lazily on first `prompt()` call.
        # We cache it across calls so history + autosuggest stay coherent.
        self._pt_session: Any = None
        self._pt_available: bool | None = None  # tri-state cache

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
            # IMPORTANT: use `stderr=` flag, NOT `file=sys.stderr`.
            # Rich's Console with file= captures the file reference
            # at __init__ time. When Live activates with
            # redirect_stderr=True, it REPLACES sys.stderr with a
            # redirector -- but a Console with the captured ref
            # bypasses the redirect, so console.print lands inside
            # the live area and gets erased on the next refresh.
            # The `stderr=True` flag makes Console look up
            # `sys.stderr` dynamically on each write, so writes
            # flow through Live's redirector.
            # First v0.27.2 real-terminal run had this exact bug:
            # streamed model text (uses sys.stdout, picked up the
            # redirect) was visible; tool call render lines (use
            # console.print, captured the original stderr) were
            # eaten.
            self._console = Console(
                stderr=self._stderr,
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

    def live_panel(
        self,
        *,
        model: str,
        max_iters: int,
        session_id: str = "",
    ) -> "LiveStatusPanel | NoOpPanel":
        """Build a sticky bottom status panel for a turn.

        In rich+TTY mode: returns an active LiveStatusPanel that
        renders a fixed bottom area showing iter/model/tokens/current
        action. Tool calls + model text scroll naturally above it.
        In plain/json/non-TTY mode: returns a NoOpPanel whose methods
        are no-ops, so callers don't need to branch on mode.

        Toggle off via `OPEN_CODE_NO_PANEL=1`.
        """
        if (self.mode != MODE_RICH or self.quiet
                or os.environ.get("OPEN_CODE_NO_PANEL")):
            return NoOpPanel()
        try:
            console = self._rich_console()
            if not console.is_terminal:
                return NoOpPanel()
            return LiveStatusPanel(
                console=console,
                model=model,
                max_iters=max_iters,
                session_id=session_id,
            )
        except Exception:
            return NoOpPanel()

    def thinking(self, message: str = "thinking..."):
        """Context manager: live spinner during a long operation.

        Use around any API call or background task that takes >500ms.
        In rich mode + TTY this shows a Rich spinner that auto-clears
        when the block exits. In plain or json mode this is a no-op
        context manager so callers don't have to branch on mode.

        Example:
            with ui.thinking("calling gemini..."):
                response = client.models.generate_content(...)
        """
        from contextlib import contextmanager

        @contextmanager
        def _nullctx():
            yield

        if self.mode != MODE_RICH:
            return _nullctx()
        try:
            c = self._rich_console()
            # status() returns a context manager; just pass it back.
            return c.status(f"[dim]{message}[/dim]", spinner="dots")
        except Exception:
            return _nullctx()

    def model_call_start(self, *, iteration: int, model: str) -> None:
        """Announce that a model call is about to fire.

        In rich mode: nothing printed (the thinking() spinner covers it).
        In plain mode: a single line that survives in logs.
        In json mode: silent (callers emit JSON envelopes separately).
        """
        if self.quiet or self.mode == MODE_JSON:
            return
        if self.mode == MODE_PLAIN:
            self._stream.write(
                f"[iter {iteration}] calling {model}...\n"
            )
        # rich mode intentionally silent here -- the spinner is enough.

    def autobuild_start(self, *, domain: str, task: str) -> None:
        """Tier 3 autobuild start notification."""
        if self.quiet or self.mode == MODE_JSON:
            return
        snip = task[:60] + ("..." if len(task) > 60 else "")
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(
                f"  [yellow]+[/yellow] [bold]autobuild[/bold] "
                f"[dim]building specialist for [/dim]"
                f"[cyan]{domain or '?'}[/cyan]"
                f" [dim]({snip})[/dim]"
            )
        else:
            self._stream.write(
                f"  + autobuild: building specialist for {domain or '?'} "
                f"({snip})\n"
            )

    def autobuild_done(self, *, name: str, path: str,
                       tools: list[str]) -> None:
        if self.quiet or self.mode == MODE_JSON:
            return
        tools_str = ", ".join(tools) if tools else "(none)"
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(
                f"  [green]+[/green] [bold]autobuild[/bold] "
                f"[dim]saved[/dim] [cyan]{name}[/cyan] "
                f"[dim]-> {path}[/dim]\n"
                f"    [dim]tools:[/dim] {tools_str}"
            )
        else:
            self._stream.write(
                f"  + autobuild: saved {name} -> {path}\n"
                f"    tools: {tools_str}\n"
            )

    def turn_summary(self, *, iters: int, in_tok: int, out_tok: int,
                     wall: float, tool_calls: int = 0,
                     tool_errors: int = 0) -> None:
        """Concise one-line summary printed at end of a turn.

        Shown for every run (not gated on --show-metrics) so users
        always know what the turn cost. Tasteful: dim, single line.
        """
        if self.quiet or self.mode == MODE_JSON:
            return
        bits = [
            f"iters={iters}",
            f"in={in_tok}t",
            f"out={out_tok}t",
            f"wall={wall:.2f}s",
        ]
        if tool_calls:
            bits.append(f"tools={tool_calls}")
        if tool_errors:
            bits.append(f"errs={tool_errors}")
        line = " ".join(bits)
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(f"  [dim][{line}][/dim]")
        else:
            self._stream.write(f"  [{line}]\n")

    def session_pointer(self, session_id: str, path: str) -> None:
        """Show the session ID at start of one-shot runs.

        Lets users `open-code --resume-id <uuid>` later. In REPL mode
        this is redundant (the banner already shows it).
        """
        if self.quiet or self.mode == MODE_JSON:
            return
        if self.mode == MODE_RICH:
            c = self._rich_console()
            c.print(
                f"  [dim]session:[/dim] [yellow]{session_id[:8]}[/yellow]"
                f"[dim]...  --resume-id {session_id}[/dim]"
            )
        else:
            self._stream.write(
                f"  session: {session_id} (resume with "
                f"--resume-id {session_id})\n"
            )

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
                body.append(" -- LLM-agnostic coding agent (REPL)\n")
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
            "open-code -- LLM-agnostic coding agent (REPL mode)\n"
            f"Session {session_id} in {cwd}\n"
        )
        if model:
            out += f"Model: {model}\n"
        out += (
            "Type your task, /help for commands, /exit (or Ctrl+D) to leave.\n"
        )
        self._stream.write(out + "\n")

    # ---- input side (prompt_toolkit) ----

    def _try_pt(self) -> bool:
        """Cache whether prompt_toolkit is usable in this UI.

        Conditions for PT: rich mode AND stdin is a TTY AND the
        prompt_toolkit module imports successfully. Otherwise we
        fall back to the builtin `input()` (which on POSIX still has
        readline-backed history + line editing because repl.py
        imports `readline` at module load time).
        """
        if self._pt_available is not None:
            return self._pt_available
        if self.mode != MODE_RICH:
            self._pt_available = False
            return False
        try:
            if not sys.stdin.isatty():
                self._pt_available = False
                return False
        except (AttributeError, OSError):
            self._pt_available = False
            return False
        try:
            import prompt_toolkit  # noqa: F401
        except ImportError:
            self._pt_available = False
            return False
        self._pt_available = True
        return True

    def _build_pt_session(self, history_file: Any) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        if history_file is not None:
            try:
                # Ensure parent dir exists; PT will create the file lazily.
                history_file.parent.mkdir(parents=True, exist_ok=True)
                history = FileHistory(str(history_file))
            except OSError:
                history = InMemoryHistory()
        else:
            history = InMemoryHistory()
        return PromptSession(
            history=history,
            auto_suggest=AutoSuggestFromHistory(),
            # Ctrl-R for reverse-i-search across history
            enable_history_search=True,
        )

    def prompt(
        self,
        message: str = "> ",
        *,
        history_file: Any = None,
        completions: list[str] | None = None,
        multiline: bool = False,
    ) -> str:
        """Read one line (or multi-line block) of user input.

        Raises:
          EOFError on Ctrl-D
          KeyboardInterrupt on Ctrl-C (caller decides how to handle)

        Behavior by mode:
          rich + TTY + PT installed -> prompt_toolkit session with
            history file (FileHistory), AutoSuggestFromHistory,
            Ctrl-R reverse-i-search, optional WordCompleter for slash
            commands, optional multi-line (Esc-Enter for newline).
          else -> builtin input() (readline auto-enabled by repl.py).
        """
        if not self._try_pt():
            return input(message)
        # The whole PT path is wrapped because PT can fail on terminal
        # incompatibilities at any of three points:
        #   (a) PromptSession construction (Win32Output errors in
        #       MSYS / Git Bash / Cygwin where TERM=xterm-256color
        #       but the underlying console is the Windows console)
        #   (b) WordCompleter construction
        #   (c) session.prompt() itself (rare; mostly bracketed-paste
        #       quirks or environment-variable parsing)
        # EOFError + KeyboardInterrupt propagate; everything else
        # disables PT permanently and falls back to input().
        try:
            if self._pt_session is None:
                self._pt_session = self._build_pt_session(history_file)
            completer: Any = None
            if completions:
                from prompt_toolkit.completion import WordCompleter
                completer = WordCompleter(
                    completions, ignore_case=True, sentence=True,
                )
            return self._pt_session.prompt(
                message,
                completer=completer,
                multiline=multiline,
            )
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception:
            self._pt_available = False
            self._pt_session = None
            return input(message)

    def reset_input(self) -> None:
        """Drop the cached PromptSession.

        Available for callers that want a fresh PT session (e.g.
        a future per-CWD history file). NOT currently called by
        `/clear` -- preserving the PromptSession across `/clear`
        keeps history + autosuggest warm, which is the better UX
        default. Exposed in case a downstream consumer wants to
        force a rebuild.
        """
        self._pt_session = None

    def empty_listing(self, message: str, *, kind: str = "listing") -> None:
        """Emit an empty-state message that's visible in every mode.

        v0.25.2 introduced a behavioral regression: routing
        `print("(no sessions yet)")` through `ui.line()` made it a
        no-op in json mode, so `--print --list-sessions` with no
        sessions returned zero bytes. JSON consumers (CI, IDE
        plugins) need SOME response.

        In json mode this emits a one-line JSON event:
            {"type":"listing_empty", "kind":"sessions", "message":"..."}
        In every other mode it routes through `line()` -> plain text
        (or rich-styled dim text if rich is active).
        """
        if self.mode == MODE_JSON:
            try:
                sys.stdout.write(json.dumps({
                    "type": "listing_empty",
                    "kind": kind,
                    "message": message,
                }) + "\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass
            return
        self.line(message)

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


# ---------------------------------------------------------------------------
# Sticky bottom status panel (Claude-Code / vim-style live footer)
# ---------------------------------------------------------------------------


class NoOpPanel:
    """Drop-in for LiveStatusPanel when not in rich+TTY mode.

    All methods are no-ops so callers can use the same try/finally
    pattern regardless of mode.
    """

    def start(self) -> "NoOpPanel":
        return self

    def stop(self) -> None:
        pass

    def update(self, **kwargs: Any) -> None:
        pass

    def set_action(self, action: str) -> None:
        pass

    def __enter__(self) -> "NoOpPanel":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


class LiveStatusPanel:
    """Sticky bottom panel that auto-refreshes during a turn.

    Pattern (borrowed from Claude Code / vim status lines / tmux):
      +----------------------------------------------------------+
      | [iter 2/25]  gemini-3.1-flash-lite-preview               |
      | 3.1K in  |  16 out  |  2.1s  |  1 tool  |  0 err         |
      | now: reading README.md                                    |
      +----------------------------------------------------------+

    Tool calls and model text scroll naturally above the panel
    (Rich's Live takes over the bottom area and scrolls regular
    console.print output upward).

    Auto-refreshes 4x/sec so the elapsed wall time + spinner stay
    fresh. The "now" line is updated explicitly by run_loop.
    """

    def __init__(
        self,
        *,
        console: Any,
        model: str,
        max_iters: int,
        session_id: str = "",
    ) -> None:
        self._console = console
        self.model = model
        self.max_iters = max_iters
        self.session_id = session_id
        # Mutable state -- updated as the turn progresses
        self.iter = 0
        self.in_tok = 0
        self.out_tok = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self.action = "starting..."
        self._live: Any = None
        self._start_time = 0.0

    def _render(self) -> Any:
        import time as _time
        from rich.panel import Panel
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text

        elapsed = (
            _time.perf_counter() - self._start_time
            if self._start_time else 0.0
        )

        # First row: iter + model
        head = Text()
        head.append(f"[iter {self.iter}/{self.max_iters}] ",
                    style="bold cyan")
        head.append(self.model, style="dim")
        if self.session_id:
            head.append("  |  session ", style="dim")
            head.append(self.session_id[:8], style="dim")

        # Second row: counters
        counters = Text()
        counters.append(_fmt_tokens(self.in_tok), style="green")
        counters.append(" in  ", style="dim")
        counters.append(_fmt_tokens(self.out_tok), style="green")
        counters.append(" out  ", style="dim")
        counters.append(f"{elapsed:.1f}s", style="yellow")
        counters.append("  ", style="")
        counters.append(f"{self.tool_calls} tools", style="dim")
        if self.tool_errors:
            counters.append(
                f"  |  {self.tool_errors} err",
                style="red bold",
            )

        # Third row: current action with a spinner
        now_line = Table.grid(padding=0)
        now_line.add_column(no_wrap=True)
        now_line.add_column(no_wrap=False)
        spin = Spinner("dots", text="", style="cyan")
        action_text = Text("now: ", style="dim")
        action_text.append(self.action, style="bold")
        now_line.add_row(spin, action_text)

        # Assemble three rows in a Panel
        body = Table.grid(padding=0)
        body.add_column()
        body.add_row(head)
        body.add_row(counters)
        body.add_row(now_line)
        return Panel(
            body, border_style="cyan", expand=True,
            padding=(0, 1),
            title="[bold]open-code[/bold]",
            title_align="left",
        )

    def start(self) -> "LiveStatusPanel":
        import time as _time
        from rich.live import Live
        self._start_time = _time.perf_counter()
        # transient=True so the panel disappears cleanly on .stop().
        # The final summary is printed separately by ui.turn_summary.
        #
        # CRITICAL: redirect_stdout/stderr MUST be True (the default).
        # Without redirection, any sys.stdout.write / sys.stderr.write
        # call (the streaming model response, tool result prints,
        # checkpoint messages, etc.) lands at the cursor position --
        # which Live owns -- and gets overwritten on the next refresh.
        # First real-terminal test of v0.27.1 hit this: panel rendered
        # the first row, then the entire model response was eaten.
        # With redirect=True, writes are buffered through Rich's
        # Console and rendered cleanly ABOVE the Live area.
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            transient=True,
        )
        self._live.start()
        return self

    def stop(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def update(self, **kwargs: Any) -> None:
        """Update one or more counter fields and refresh the panel."""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        if self._live is not None:
            try:
                self._live.update(self._render())
            except Exception:
                pass

    def set_action(self, action: str) -> None:
        self.action = action[:80] if len(action) > 80 else action
        self.update()

    def __enter__(self) -> "LiveStatusPanel":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def _fmt_tokens(n: int) -> str:
    """Compact human-readable token count: 12345 -> '12.3K'."""
    if n < 1000:
        return str(n)
    if n < 1000000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1000000:.1f}M"
