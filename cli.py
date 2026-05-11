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
            "Terminal coding agent — LLM-agnostic (Gemini backend). "
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
        "--root",
        default=os.environ.get("OPEN_CODE_ROOT", str(DEFAULT_OC_ROOT)),
        help=f"Sessions root dir (default: {DEFAULT_OC_ROOT}).",
    )
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress per-iteration trace.")
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
        run_repl,
        load_project_context,
        build_system_instruction,
        expand_file_refs,
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    cwd = Path.cwd().resolve()
    CONFIG.cwd = cwd
    CONFIG.allow_outside_cwd = args.allow_outside_cwd
    CONFIG.allow_dangerous = args.allow_dangerous

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

    project_ctx, project_path = load_project_context(cwd)
    system_instruction = build_system_instruction(project_ctx, project_path)
    if project_path and not args.quiet:
        print(f"[loaded {project_path} as project context]", file=sys.stderr)

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
            note = f"[resuming session {session.id} — {len(initial_history)} prior messages"
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
                note = f"[resuming session {session.id} — {len(initial_history)} prior messages"
                if dropped > 0:
                    note += f"; {dropped} older dropped (--resume-max-messages to adjust)"
                print(note + "]", file=sys.stderr)
    if session is None:
        session = store.create(str(cwd), args.model, task)

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
    )

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
