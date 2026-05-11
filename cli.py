"""CLI argparse + main() entry point for open-code.

Extracted from open_code.py in v0.5.0-pre per the v0.4 pre-commitment.
Keeps open_code.py focused on agent-loop semantics (run_loop, REPL,
streaming, helpers); cli.py handles argv -> behavior dispatch.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from google.genai import types

from sessions import Session, SessionStore, migrate_from_sqlite
from settings import load_layered_settings
from tools import CONFIG


def _print_session_list(sessions: list[Session]) -> None:
    if not sessions:
        print("(no sessions yet)")
        return
    print(f"{'ID':<38}  {'STARTED':<25}  {'MODEL':<35}  TASK")
    print("-" * 130)
    for s in sessions:
        task = s.task or ""
        if len(task) > 40:
            task = task[:37] + "..."
        print(f"{s.id:<38}  {s.started_at:<25}  {s.model:<35}  {task}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser. Defaults pulled from open_code constants."""
    from open_code import (
        DEFAULT_MODEL,
        DEFAULT_MAX_ITERATIONS,
        DEFAULT_OC_ROOT,
        DEFAULT_RESUME_MAX_MESSAGES,
    )

    parser = argparse.ArgumentParser(
        prog="open-code",
        description=(
            "Terminal coding agent -- LLM-agnostic (Gemini backend). "
            "With no task, drops into a REPL. Otherwise runs one task "
            "and exits."
        ),
    )
    parser.add_argument("task", nargs="*", help="The task description.")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPEN_CODE_MODEL", DEFAULT_MODEL),
        help=f"Gemini model (default: {DEFAULT_MODEL}; env OPEN_CODE_MODEL).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("OPEN_CODE_MAX_ITER", DEFAULT_MAX_ITERATIONS)),
        help=f"Cap agentic loop iterations (default: {DEFAULT_MAX_ITERATIONS}).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue the most recent session in this directory.",
    )
    parser.add_argument(
        "--resume-id",
        default=None,
        help="Continue a specific session by UUID (regardless of CWD).",
    )
    parser.add_argument(
        "--resume-max-messages",
        type=int,
        default=int(os.environ.get("OPEN_CODE_RESUME_MAX", DEFAULT_RESUME_MAX_MESSAGES)),
        help=(
            f"Cap on messages loaded by --resume/--resume-id (default {DEFAULT_RESUME_MAX_MESSAGES}). "
            "Set 0 to disable the cap and load full history."
        ),
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List recent sessions for this directory and exit.",
    )
    parser.add_argument(
        "--list-sessions-all",
        action="store_true",
        help="List sessions across all directories and exit.",
    )
    parser.add_argument(
        "--allow-outside-cwd",
        action="store_true",
        help="Allow write_file to paths outside the current working directory.",
    )
    parser.add_argument(
        "--allow-dangerous",
        action="store_true",
        help="Allow run_shell to execute commands matching the destructive denylist.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output (one full response per iteration).",
    )
    parser.add_argument(
        "--no-repomap",
        action="store_true",
        help="Disable the Aider-style repo-map symbol skeleton prepended to "
             "the system instruction.",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Don't spawn MCP servers declared in settings.json.",
    )
    parser.add_argument(
        "--trust-hooks",
        action="store_true",
        help="Allow this project's .open-code/hooks/ to run for this "
             "invocation without prompting. Does NOT persist trust.",
    )
    parser.add_argument(
        "--no-hooks",
        action="store_true",
        help="Disable all hook execution for this invocation.",
    )
    parser.add_argument(
        "--effort",
        choices=("low", "medium", "high", "xhigh"),
        default=None,
        help=(
            "Reasoning effort level. Maps to a thinking_budget passed "
            "to the model (low=0, medium=512, high=4096, xhigh=16384). "
            "Models that don't support reasoning ignore this."
        ),
    )
    parser.add_argument(
        "--statusline",
        action="store_true",
        help="Emit a one-line status footer to stderr after each iter "
             "(model / iter / tokens / refusals).",
    )
    parser.add_argument(
        "--style",
        default=None,
        help="Output style overlay applied to the system instruction "
             "(Tier 2 #23). Built-ins: default, concise, explanatory, "
             "learning, pair-programmer, yolo. Custom: drop "
             "<name>.md in .open-code/output-styles/ or ~/.open-code/output-styles/.",
    )
    parser.add_argument(
        "--list-styles",
        action="store_true",
        help="List available output styles (built-in + user + project) and exit.",
    )
    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="List installed plugins (Tier 2 #22) -- project + user -- and exit.",
    )
    parser.add_argument(
        "--auto-checkpoint",
        action="store_true",
        help="Take a shadow-git snapshot of the working tree at the "
             "start of each turn (Tier 2 #11). Requires `git` on PATH. "
             "Stored under .open-code/checkpoints.git/. Use /checkpoints "
             "and /restore in the REPL.",
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("OPEN_CODE_ROOT", str(DEFAULT_OC_ROOT)),
        help=f"Sessions root dir (default: {DEFAULT_OC_ROOT}).",
    )
    parser.add_argument(
        "--mode",
        choices=("default", "acceptEdits", "plan", "auto", "bypassPermissions"),
        default=None,
        help=(
            "Permission mode. default=ask on writes/shell; "
            "acceptEdits=auto-allow writes; plan=narrate only (no edits, no shell); "
            "bypassPermissions=skip rules (hard denylist still applies)."
        ),
    )
    parser.add_argument(
        "--architect",
        default=None,
        help=(
            "Model used by /plan (Aider-style architect/editor split). "
            "Defaults to settings.models.architect, or falls back to --model."
        ),
    )
    parser.add_argument(
        "--editor",
        default=None,
        help=(
            "Model used by /act. Defaults to settings.models.editor, "
            "or falls back to --model."
        ),
    )
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress per-iteration trace.")
    parser.add_argument(
        "--print", "-p", action="store_true", dest="print_json",
        help="Non-interactive JSON-lines output mode (Tier 2 #20). "
             "Emits one JSON object per line to stdout: session_start, "
             "text, tool_use, tool_result, session_end. Implies --quiet "
             "and --no-stream. Suitable for piping into other tools.",
    )
    parser.add_argument(
        "--show-metrics",
        action="store_true",
        help="Print token/iteration summary on completion.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Late imports: open_code re-imports from cli (build_parser, _print_session_list)
    # so we defer to avoid a cycle at module-load time.
    from open_code import (
        run_loop,
        load_project_layers,
        build_system_instruction_layered,
        expand_file_refs,
        set_mcp_client,
    )
    from repl import run_repl
    from mcp import MCPClient

    parser = build_parser()
    args = parser.parse_args(argv)

    cwd = Path.cwd().resolve()
    CONFIG.cwd = cwd
    CONFIG.allow_outside_cwd = args.allow_outside_cwd
    CONFIG.allow_dangerous = args.allow_dangerous
    # Tier 2 #14: status-line toggle (off by default)
    CONFIG.statusline_on = args.statusline  # type: ignore[attr-defined]

    # Layered settings: ~/.open-code -> project -> project-local.
    # CLI flags + env vars STILL win (already applied above).
    settings = load_layered_settings(cwd)
    # --mode flag overrides settings.mode
    if args.mode is not None:
        settings.mode = args.mode
    if args.architect is not None:
        settings.architect_model = args.architect
    if args.editor is not None:
        settings.editor_model = args.editor
    if args.effort is not None:
        settings.effort = args.effort
    if args.auto_checkpoint:
        settings.auto_checkpoint = True
    if args.style is not None:
        settings.output_style = args.style

    if args.list_styles:
        from output_styles import list_available
        for name, source in list_available(cwd):
            print(f"  {name:<20}  ({source})")
        return 0

    if args.list_plugins:
        import plugins as _plugins
        print(_plugins.render_plugin_listing(_plugins.discover_plugins(cwd)))
        return 0
    if args.print_json:
        # Implies --quiet and disables streaming so we emit one
        # well-formed JSON object per logical event instead of mixing
        # streamed text with our envelopes.
        args.quiet = True
        args.no_stream = True
        CONFIG.print_json = True  # type: ignore[attr-defined]
    else:
        CONFIG.print_json = False  # type: ignore[attr-defined]

    # Start any MCP servers declared in settings.json
    mcp_client: MCPClient | None = None
    mcp_servers_cfg = settings.raw.get("mcpServers") if settings.raw else None
    if mcp_servers_cfg and not args.no_mcp:
        mcp_client = MCPClient()
        mcp_client.start_servers(mcp_servers_cfg)
        set_mcp_client(mcp_client)

    # Hook trust gate. If the project ships .open-code/hooks/, prompt
    # the user for consent (or auto-deny in one-shot mode). This is the
    # mitigation for the "hostile repo clone -> RCE" class of bug.
    if args.no_hooks:
        settings.hooks_disabled = True
    else:
        import hooks as _hooks
        is_interactive = sys.stdin.isatty()
        _hooks.ensure_hooks_trusted(
            cwd, interactive=is_interactive,
            trust_override=args.trust_hooks,
        )
    if settings.sources and not args.quiet:
        print(
            f"[loaded settings from {', '.join(str(p) for p in settings.sources)}]",
            file=sys.stderr,
        )
    # If settings.model is set and the user didn't override on the CLI,
    # honor it. (CLI default is DEFAULT_MODEL when --model wasn't passed.)
    if settings.model and args.model == os.environ.get(
        "OPEN_CODE_MODEL",
        __import__("open_code").DEFAULT_MODEL,
    ):
        args.model = settings.model
    if (settings.max_iterations is not None and
            args.max_iterations == int(os.environ.get(
                "OPEN_CODE_MAX_ITER",
                __import__("open_code").DEFAULT_MAX_ITERATIONS))):
        args.max_iterations = settings.max_iterations

    root = Path(args.root).expanduser()
    store = SessionStore(root)

    # One-shot migration of v0.2.x SQLite -> v0.3 JSONL.
    legacy_db = root / "sessions.db"
    if legacy_db.exists() and not any(store.projects_dir.iterdir()):
        migrated = migrate_from_sqlite(legacy_db, store)
        if migrated > 0:
            sys.stderr.write(
                f"open-code: migrated {migrated} session(s) from {legacy_db} "
                f"to JSONL. Old DB renamed to .migrated; delete if unwanted.\n"
            )

    if args.list_sessions or args.list_sessions_all:
        sessions = (
            store.list_all() if args.list_sessions_all
            else store.list_for_cwd(str(cwd))
        )
        scope = "all directories" if args.list_sessions_all else str(cwd)
        print(f"Recent sessions in {scope}:")
        _print_session_list(sessions)
        return 0

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.stderr.write(
            "open-code: GEMINI_API_KEY is not set. Either:\n"
            "  export GEMINI_API_KEY=your-key   (POSIX)\n"
            "  $env:GEMINI_API_KEY = 'your-key' (PowerShell)\n"
            "  or put it in a .env file in this directory.\n"
            "Get one at https://aistudio.google.com/app/apikey\n"
        )
        return 1

    layers = load_project_layers(cwd)
    system_instruction = build_system_instruction_layered(layers)
    if layers and not args.quiet:
        print(
            f"[loaded {len(layers)} project-context layer(s): "
            f"{', '.join(str(p) for p, _ in layers)}]",
            file=sys.stderr,
        )

    # Tier 2 #23 -- apply output-style overlay (if any) to the
    # system_instruction. settings.output_style defaults to "default"
    # which is a no-op.
    if settings.output_style and settings.output_style != "default":
        from output_styles import apply_to_system_instruction
        system_instruction, style_source = apply_to_system_instruction(
            system_instruction, settings.output_style, cwd,
        )
        if not args.quiet:
            print(f"[output style: {settings.output_style} ({style_source})]",
                  file=sys.stderr)

    # Repo-map: append a symbol skeleton (Aider-style, Python only in v0.13)
    if not args.no_repomap:
        try:
            from repomap import build_repomap
            task_hint = " ".join(args.task) if args.task else None
            rm = build_repomap(cwd, task_hint=task_hint)
            if rm:
                system_instruction += "\n\n## Repo symbol skeleton\n\n" + rm
                if not args.quiet:
                    print(f"[repo-map: included {rm.count('# ')} files]",
                          file=sys.stderr)
        except Exception as exc:
            if not args.quiet:
                print(f"[repo-map disabled: {type(exc).__name__}: {exc}]",
                      file=sys.stderr)

    task = " ".join(args.task).strip()
    if not task:
        return run_repl(
            store=store,
            cwd=cwd,
            model=args.model,
            api_key=api_key,
            max_iterations=args.max_iterations,
            system_instruction=system_instruction,
            resume_max_messages=args.resume_max_messages,
            stream=not args.no_stream,
            quiet=args.quiet,
            show_metrics=args.show_metrics,
            initial_resume=args.resume,
            initial_resume_id=args.resume_id,
            settings=settings,
        )

    task_expanded, refs = expand_file_refs(task, cwd)
    if refs and not args.quiet:
        print(
            f"[expanded {len(refs)} @-file reference(s): "
            f"{', '.join(r['token'] for r in refs)}]",
            file=sys.stderr,
        )

    session: Session | None = None
    initial_history: list[types.Content] = []
    if args.resume_id:
        session = store.find_by_id(args.resume_id)
        if session is None:
            sys.stderr.write(f"open-code: no session with id {args.resume_id!r}\n")
            return 1
        initial_history, dropped = store.load_history(session, args.resume_max_messages)
        if not args.quiet:
            note = f"[resuming session {session.id} -- {len(initial_history)} prior messages"
            if dropped > 0:
                note += f"; {dropped} older dropped (--resume-max-messages to adjust)"
            print(note + "]", file=sys.stderr)
    elif args.resume:
        session = store.find_latest_for_cwd(str(cwd))
        if session is None:
            sys.stderr.write(
                f"open-code: no previous session found in {cwd}; starting a fresh one\n"
            )
        else:
            initial_history, dropped = store.load_history(session, args.resume_max_messages)
            if not args.quiet:
                note = f"[resuming session {session.id} -- {len(initial_history)} prior messages"
                if dropped > 0:
                    note += f"; {dropped} older dropped (--resume-max-messages to adjust)"
                print(note + "]", file=sys.stderr)
    if session is None:
        session = store.create(str(cwd), args.model, task)

    try:
        exit_code, metrics = run_loop(
            task=task_expanded,
            model=args.model,
            api_key=api_key,
            max_iterations=args.max_iterations,
            store=store,
            session=session,
            initial_history=initial_history,
            verbose=not args.quiet,
            stream=not args.no_stream,
            system_instruction=system_instruction,
            fire_session_start=True,
            settings=settings,
            is_repl=False,
        )
    finally:
        if mcp_client is not None:
            mcp_client.shutdown()

    if args.show_metrics:
        line = (
            f"\n[open-code] model={metrics['model']} "
            f"session={metrics['session_id']} "
            f"stream={metrics['streamed']} "
            f"iters={metrics['iterations']} "
            f"tool_calls={metrics['tool_calls']} "
            f"tool_errors={metrics['tool_errors']} "
            f"input_tok={metrics['total_input_tokens']} "
            f"output_tok={metrics['total_output_tokens']} "
            f"wall={metrics['wall_seconds']:.2f}s\n"
        )
        sys.stderr.write(line)
        total = store.aggregate_metrics(session)
        sys.stderr.write(
            f"[open-code:cumulative] session={session.id} "
            f"iters={total['n_iters']} "
            f"input_tok={total['input_tok']} "
            f"output_tok={total['output_tok']} "
            f"fallbacks={total['n_fallbacks']} "
            f"refusals={total['n_refusals']}\n"
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
