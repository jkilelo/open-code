"""Interactive REPL for open-code (Claude Code-style `claude` with no args).

Extracted from open_code.py in v0.10.0-pre per the v0.9 pre-commitment
(open_code.py was at 991 lines and growing).

Provides:
- REPL_BANNER, REPL_HELP -- user-facing strings
- run_repl(...) -- the main interactive loop

Slash commands:
  /help /exit /quit /clear /sessions /switch /cost /model /dump
  /skills /skill /mode /plan /act
"""
from __future__ import annotations

import json
import sys
import uuid as _uuid
from pathlib import Path
from typing import Any

from llm import LLMClient, Message, Part
from sessions import Session, SessionStore


REPL_BANNER = """\
open-code -- Gemini coding agent (REPL mode)
Session {sid} in {cwd}
Type your task, /help for commands, /exit (or Ctrl+D) to leave.
"""

REPL_HELP = """\
Slash commands:
  /help              show this help
  /exit, /quit       leave the REPL
  /clear             start a fresh session (forget context)
  /sessions          list recent sessions in this CWD
  /switch <uuid>     switch to a different session by UUID
  /cost              show cumulative cost for this session
  /model <name>      switch the model used for subsequent turns
  /dump              print the path of the JSONL transcript
  /skills            list skills under .open-code/skills/
  /skill <n> [args]  run a skill by name; $ARGUMENTS / $1.. interpolated
  /agents            list subagents under .open-code/agents/ (use via the delegate tool)
  /compact [keep]    summarize older history; keep last N msgs verbatim (default 10)
  /effort [name]     show or set reasoning effort (low/medium/high/xhigh)
  /style [name]      show or set output style overlay (default/concise/explanatory/learning/pair-programmer/yolo or custom)
  /checkpoints       list recent shadow-git checkpoints (Tier 2 #11)
  /checkpoint [label] take a manual snapshot now (use after a risky edit)
  /restore <ref>     restore working tree to a prior checkpoint (DESTRUCTIVE; confirms)
  /undo [N]          restore to the start of the Nth-most-recent turn (default N=1)
  /loop <interval> <task>    repeat a task every <interval> (e.g. 30, 5m, 1h). Ctrl-C to stop.
  /schedule <delay> <task>   run a task once after <delay> (e.g. 60, 10m, 2h). Ctrl-C cancels.
  /autobuild                 show autobuild status + list built specialists
  /autobuild on              re-enable autobuild for this session
  /autobuild off             disable autobuild for this session
  /autobuild search <q>      BM25 search across the agent library
  /autobuild approve <name>  promote a pending specialist to live (when auto_approve=false)
  /autobuild reject <name>   discard a pending specialist
  /autobuild pending         list specialists awaiting approval
  /autobuild history <name>  show archived versions of a specialist
  /autobuild revert <name>   restore the most recent archived version (or specify ts prefix)
  /mode [name]       show or set permission mode (default/acceptEdits/plan/auto/bypassPermissions)
  /plan <task>       run <task> in plan mode (read-only); save result as a plan event
  /act [task]        load most recent plan; switch to acceptEdits; execute

@-file references in prompts:
  Reference any local file with @path/to/file. open-code reads it and
  injects the content alongside your prompt. Example:
      > summarize @README.md and suggest improvements
"""


def run_repl(
    *,
    store: SessionStore,
    cwd: Path,
    model: str,
    api_key: str,
    max_iterations: int,
    system_instruction: str,
    resume_max_messages: int,
    stream: bool,
    quiet: bool,
    show_metrics: bool,
    initial_resume: bool,
    initial_resume_id: str | None,
    settings: Any = None,
    ui: Any = None,
    llm: LLMClient | None = None,
) -> int:
    """Interactive REPL. Persistent session; each prompt becomes a task."""
    # Late imports of open_code symbols to avoid a cycle at module load.
    from open_code import run_loop, expand_file_refs, _print_session_list
    if ui is None:
        from ui import UI as _UI
        ui = _UI.auto(quiet=quiet)

    try:
        import readline  # noqa: F401  -- enables history + line editing
    except ImportError:
        pass

    # Lazily build LLMClient if caller didn't supply one.
    if llm is None:
        from open_code import _make_llm_from_settings
        llm = _make_llm_from_settings(settings, api_key)

    session: Session | None = None
    initial_history: list[Message] = []
    if initial_resume_id:
        session = store.find_by_id(initial_resume_id)
        if session is None:
            sys.stderr.write(f"open-code: no session with id {initial_resume_id!r}\n")
            return 1
        initial_history, dropped = store.load_history(session, resume_max_messages)
        sys.stderr.write(
            f"[resuming session {session.id} -- {len(initial_history)} prior messages"
            + (f"; {dropped} older dropped" if dropped else "")
            + "]\n"
        )
    elif initial_resume:
        session = store.find_latest_for_cwd(str(cwd))
        if session is not None:
            initial_history, dropped = store.load_history(session, resume_max_messages)
            sys.stderr.write(
                f"[resuming session {session.id} -- {len(initial_history)} prior messages"
                + (f"; {dropped} older dropped" if dropped else "")
                + "]\n"
            )
    if session is None:
        session = store.create(str(cwd), model, "(REPL session)")

    ui.banner(session_id=session.id, cwd=str(cwd), model=model)

    current_model = model
    history: list[Message] = list(initial_history)

    # Slash commands offered as tab-completions in the prompt_toolkit
    # path. Kept in sync with the dispatch below; missing ones just
    # mean no autocompletion, not a broken command.
    SLASH_COMMANDS = [
        "/help", "/exit", "/quit", "/clear", "/sessions", "/switch",
        "/cost", "/model", "/dump", "/skills", "/skill", "/agents",
        "/compact", "/effort", "/style",
        "/checkpoints", "/checkpoint", "/restore", "/undo",
        "/mode", "/plan", "/act",
        "/loop", "/schedule",
        "/autobuild",
    ]
    # Persistent input history: ~/.open-code/history.txt. Survives
    # across REPL launches so Up-arrow gives you yesterday's prompts.
    _history_path = Path.home() / ".open-code" / "history.txt"

    while True:
        try:
            line = ui.prompt(
                "> ",
                history_file=_history_path,
                completions=SLASH_COMMANDS,
            ).strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue

        if not line:
            continue

        if line.startswith("/"):
            cmd, _, rest = line[1:].partition(" ")
            cmd = cmd.lower().strip()
            rest = rest.strip()
            if cmd in ("exit", "quit"):
                break
            if cmd == "help":
                print(REPL_HELP)
                continue
            if cmd == "clear":
                session = store.create(str(cwd), current_model, "(REPL session)")
                history = []
                print(f"[new session {session.id}]")
                continue
            if cmd == "sessions":
                sess = store.list_for_cwd(str(cwd))
                if not sess:
                    ui.empty_listing("(no sessions yet)", kind="sessions")
                else:
                    rows: list[list[str]] = []
                    for s in sess:
                        task = s.task or ""
                        if len(task) > 40:
                            task = task[:37] + "..."
                        rows.append([s.id, s.started_at, s.model, task])
                    ui.table(
                        title=f"Sessions in {cwd}",
                        columns=["ID", "STARTED", "MODEL", "TASK"],
                        rows=rows,
                    )
                continue
            if cmd == "switch":
                if not rest:
                    print("usage: /switch <session-uuid>")
                    continue
                new = store.find_by_id(rest)
                if new is None:
                    print(f"no session with id {rest!r}")
                    continue
                session = new
                history, dropped = store.load_history(session, resume_max_messages)
                msg = f"[switched to session {session.id} -- {len(history)} prior messages"
                if dropped:
                    msg += f"; {dropped} older dropped"
                print(msg + "]")
                continue
            if cmd == "cost":
                agg = store.aggregate_metrics(session)
                print(
                    f"session={session.id} iters={agg['n_iters']} "
                    f"input_tok={agg['input_tok']} output_tok={agg['output_tok']} "
                    f"fallbacks={agg['n_fallbacks']} refusals={agg['n_refusals']}"
                )
                continue
            if cmd == "model":
                if not rest:
                    print(f"current model: {current_model}")
                    continue
                current_model = rest
                print(f"[model set to {current_model}]")
                continue
            if cmd == "dump":
                print(session.path)
                continue
            if cmd == "skills":
                import skills as _skills
                skill_items = _skills.discover_skills(cwd)
                if not skill_items:
                    ui.empty_listing(
                        "(no skills defined; create "
                        ".open-code/skills/<name>/SKILL.md)",
                        kind="skills",
                    )
                else:
                    rows = []
                    for sk in skill_items:
                        desc = sk.description or ""
                        if len(desc) > 55:
                            desc = desc[:52] + "..."
                        rows.append([sk.name, desc])
                    ui.table(title="Skills",
                             columns=["NAME", "DESCRIPTION"], rows=rows)
                continue
            if cmd == "agents":
                import subagents as _subagents
                agents_items = _subagents.discover_agents(cwd)
                if not agents_items:
                    ui.empty_listing(
                        "(no agents defined; create "
                        ".open-code/agents/<name>.md)",
                        kind="agents",
                    )
                else:
                    rows = []
                    for ag in agents_items:
                        desc = ag.description or ""
                        if len(desc) > 40:
                            desc = desc[:37] + "..."
                        m = ag.model or "(default)"
                        rows.append([ag.name, m, desc])
                    ui.table(title="Agents",
                             columns=["NAME", "MODEL", "DESCRIPTION"],
                             rows=rows)
                continue
            if cmd == "plan":
                if not rest:
                    print("usage: /plan <task description>")
                    continue
                if settings is None:
                    from settings import Settings as _S
                    settings = _S()
                prior_mode = settings.mode
                settings.mode = "plan"
                task_expanded, refs = expand_file_refs(rest, cwd)
                if refs and not quiet:
                    print(f"[expanded {len(refs)} @-file reference(s)]",
                          file=sys.stderr)
                plan_model = settings.architect_model or current_model
                if plan_model != current_model and not quiet:
                    print(f"[plan using architect model {plan_model!r}]",
                          file=sys.stderr)
                try:
                    exit_code, metrics = run_loop(
                        task=task_expanded,
                        model=plan_model, api_key=api_key,
                        max_iterations=max_iterations,
                        store=store, session=session,
                        initial_history=history,
                        verbose=not quiet, stream=stream,
                        system_instruction=system_instruction,
                        fire_session_start=(not history),
                        settings=settings, is_repl=True, ui=ui,
                        llm=llm,
                    )
                except KeyboardInterrupt:
                    settings.mode = prior_mode
                    print("\n[plan interrupted]", file=sys.stderr)
                    continue
                history, _ = store.load_history(session, resume_max_messages)
                settings.mode = prior_mode
                last_model_text = ""
                try:
                    with session.path.open("r", encoding="utf-8") as f:
                        for L in f:
                            try:
                                ev = json.loads(L)
                            except Exception:
                                continue
                            if ev.get("kind") == "msg" and ev.get("role") == "model":
                                tps = [p.get("text", "") for p in ev.get("parts", [])
                                       if p.get("type") == "text"]
                                if tps:
                                    last_model_text = "\n".join(tps)
                except OSError:
                    pass
                if last_model_text:
                    pid = _uuid.uuid4().hex[:8]
                    store.append_plan(
                        session, plan_id=pid,
                        content=last_model_text,
                        model=metrics.get("model", current_model),
                    )
                    if not quiet:
                        print(f"[plan saved: id={pid}; /act to execute]",
                              file=sys.stderr)
                if metrics.get("model") and metrics["model"] != current_model:
                    current_model = metrics["model"]
                continue
            if cmd == "act":
                latest = store.latest_plan(session)
                if not latest:
                    print("no plan recorded in this session; use /plan first")
                    continue
                plan_id = latest.get("plan_id", "?")
                plan_text = latest.get("content", "")
                if settings is None:
                    from settings import Settings as _S
                    settings = _S()
                prior_mode = settings.mode
                settings.mode = "acceptEdits"
                default_act_directive = (
                    "Now execute the plan above. For every file the plan "
                    "describes, call write_file with the exact path and "
                    "content shown. For every shell command the plan "
                    "describes, call run_shell. Do NOT describe what you "
                    "would do -- actually call the tools. After all tool "
                    "calls succeed, give a one-line confirmation."
                )
                task_with_plan = (
                    f"<plan id=\"{plan_id}\">\n{plan_text}\n</plan>\n\n"
                    f"{rest if rest else default_act_directive}"
                )
                act_model = settings.editor_model or current_model
                if not quiet:
                    suffix = (f" (editor model {act_model!r})"
                              if act_model != current_model else "")
                    print(f"[acting on plan {plan_id}; mode=acceptEdits{suffix}]",
                          file=sys.stderr)
                try:
                    exit_code, metrics = run_loop(
                        task=task_with_plan,
                        model=act_model, api_key=api_key,
                        max_iterations=max_iterations,
                        store=store, session=session,
                        initial_history=history,
                        verbose=not quiet, stream=stream,
                        system_instruction=system_instruction,
                        fire_session_start=(not history),
                        settings=settings, is_repl=True, ui=ui,
                        llm=llm,
                    )
                except KeyboardInterrupt:
                    settings.mode = prior_mode
                    print("\n[act interrupted]", file=sys.stderr)
                    continue
                history, _ = store.load_history(session, resume_max_messages)
                settings.mode = prior_mode
                if metrics.get("model") and metrics["model"] != current_model:
                    current_model = metrics["model"]
                continue
            if cmd == "compact":
                # Summarize older history; keep N most-recent msgs.
                keep = 10
                if rest:
                    try:
                        keep = max(2, int(rest))
                    except ValueError:
                        print(f"usage: /compact [keep_recent_msgs]")
                        continue
                full_history, _ = store.load_history(session, max_messages=0)
                if len(full_history) <= keep:
                    print(f"[only {len(full_history)} msgs; nothing to compact]")
                    continue
                dropped = full_history[:-keep]
                kept = full_history[-keep:]
                # Render dropped msgs as text for the summarizer.
                # Provider-agnostic via the neutral Message/Part shape.
                stub_lines: list[str] = []
                for m in dropped:
                    role = m.role or "?"
                    text_bits: list[str] = []
                    for p in m.parts:
                        if p.is_text() and p.text:
                            text_bits.append(p.text)
                        elif p.is_tool_call():
                            text_bits.append(
                                f"[tool {p.tool_name}({dict(p.tool_args) if p.tool_args else {}})]"
                            )
                        elif p.is_tool_result():
                            text_bits.append(
                                f"[tool result {p.tool_name}: {dict(p.tool_result) if p.tool_result else {}}]"
                            )
                    if text_bits:
                        stub_lines.append(f"{role}: " + "\n".join(text_bits)[:500])
                prompt = (
                    "Summarize this prior conversation in 5-10 sentences. "
                    "Focus on: what files exist now, what was decided, what's "
                    "still TODO. Keep it tight; this becomes the model's "
                    "memory replacement.\n\n---\n\n"
                    + "\n\n".join(stub_lines)
                )
                try:
                    msg = Message(role="user", parts=[Part.make_text(prompt)])
                    result = llm.ask(
                        model=current_model,
                        messages=[msg],
                        system_instruction="You summarize coding-session histories.",
                    )
                    summary = result.message.text()
                except Exception as exc:
                    print(f"[compact: summarization failed: {exc}]")
                    continue
                if not summary:
                    print("[compact: model returned empty summary; aborting]")
                    continue
                store.append_compact(
                    session, summary=summary, kept_recent=len(kept),
                    dropped=len(dropped), model=current_model,
                )
                # Reload history so this REPL session uses the compacted form
                history, _ = store.load_history(session, resume_max_messages)
                print(
                    f"[compacted: {len(dropped)} msgs -> {len(summary)}-char "
                    f"summary; {len(kept)} recent msgs preserved]"
                )
                continue
            if cmd == "checkpoints":
                import checkpoints as _ckpt
                if not _ckpt.is_initialized(cwd):
                    print(
                        "[shadow repo not initialized; will auto-init on "
                        "first /checkpoint or auto-checkpoint]"
                    )
                    continue
                ckpt_rows = _ckpt.list_checkpoints(cwd, limit=20)
                if not ckpt_rows:
                    ui.empty_listing("[no checkpoints yet]",
                                     kind="checkpoints")
                    continue
                table_rows = [
                    [r["short_sha"], r["ts"], r["label"]]
                    for r in ckpt_rows
                ]
                ui.table(
                    title="Recent shadow-git checkpoints (newest first)",
                    columns=["SHA", "TIMESTAMP", "LABEL"],
                    rows=table_rows,
                )
                continue
            if cmd == "checkpoint":
                import checkpoints as _ckpt
                label = rest.strip() or f"manual: session {session.id[:8]}"
                sha, msg = _ckpt.snapshot(cwd, label)
                if sha:
                    store.append_checkpoint(
                        session, sha=sha, label=label, phase="manual",
                    )
                    print(f"[checkpoint {sha[:10]} -- {label}]")
                else:
                    print(f"[checkpoint failed: {msg}]")
                continue
            if cmd == "restore":
                import checkpoints as _ckpt
                if not rest:
                    print("usage: /restore <short-sha or ref>")
                    continue
                sha = _ckpt.resolve_ref(cwd, rest)
                if sha is None:
                    print(f"[no checkpoint matching {rest!r}]")
                    continue
                preview = _ckpt.diff_summary(cwd, sha, "HEAD")
                print(f"About to restore working tree to {sha[:10]}.")
                print("Changes that will be UNDONE (relative to current HEAD):")
                print(preview if preview.strip() else "  (no diff output)")
                try:
                    ans = input(
                        "[restore/cancel] (type 'restore' to confirm): "
                    ).strip().lower()
                except EOFError:
                    ans = "cancel"
                if ans != "restore":
                    print("[cancelled]")
                    continue
                # Take a pre-restore safety snapshot so the user can
                # roll forward again if they change their mind.
                safety_sha, safety_msg = _ckpt.snapshot(
                    cwd, f"pre-restore-from {sha[:10]}",
                )
                if safety_sha:
                    store.append_checkpoint(
                        session, sha=safety_sha,
                        label=f"pre-restore-from {sha[:10]}",
                        phase="manual",
                    )
                    print(f"[safety snapshot {safety_sha[:10]} taken]")
                ok, msg = _ckpt.restore(cwd, sha)
                if ok:
                    print(f"[restored to {sha[:10]}; safety snapshot above to roll forward]")
                else:
                    print(f"[restore failed: {msg}]")
                continue
            if cmd == "undo":
                # Tier 2 #12: restore to the start of the Nth-most-recent turn.
                # N=1 -> most recent turn-start (default; "undo my last prompt").
                import checkpoints as _ckpt
                n = 1
                if rest:
                    try:
                        n = max(1, int(rest))
                    except ValueError:
                        print("usage: /undo [N]  (N defaults to 1)")
                        continue
                ts_events = store.recent_checkpoints(
                    session, phase="turn-start", limit=n + 5,
                )
                if len(ts_events) < n:
                    print(
                        f"[only {len(ts_events)} turn-start checkpoint(s) "
                        f"in this session; can't undo {n} turns]"
                    )
                    continue
                target = ts_events[n - 1]
                sha = target["sha"]
                label = target.get("label", "(no label)")
                preview = _ckpt.diff_summary(cwd, sha, "HEAD")
                print(
                    f"About to restore to start of turn {n} back: "
                    f"{sha[:10]} -- {label}"
                )
                print("Changes that will be UNDONE:")
                print(preview if preview.strip() else "  (no diff output)")
                try:
                    ans = input(
                        "[undo/cancel] (type 'undo' to confirm): "
                    ).strip().lower()
                except EOFError:
                    ans = "cancel"
                if ans != "undo":
                    print("[cancelled]")
                    continue
                safety_sha, _ = _ckpt.snapshot(
                    cwd, f"pre-undo-from {sha[:10]}",
                )
                if safety_sha:
                    store.append_checkpoint(
                        session, sha=safety_sha,
                        label=f"pre-undo-from {sha[:10]}",
                        phase="manual",
                    )
                    print(f"[safety snapshot {safety_sha[:10]} taken]")
                ok, msg = _ckpt.restore(cwd, sha)
                if ok:
                    print(
                        f"[undone -- restored to {sha[:10]}; "
                        f"use /restore {safety_sha[:10] if safety_sha else '<sha>'} "
                        f"to roll forward]"
                    )
                else:
                    print(f"[undo failed: {msg}]")
                continue
            if cmd == "style":
                # Tier 2 #23 -- output style overlay. The current
                # system_instruction was finalized at cli.main time, so
                # mid-REPL changes apply to NEW sessions (via /clear)
                # rather than the current one.
                import output_styles as _styles
                from settings import Settings as _S
                if settings is None:
                    settings = _S()
                if not rest:
                    available = _styles.list_available(cwd)
                    print(f"current style: {settings.output_style}")
                    print("available:")
                    for name, source in available:
                        print(f"  {name:<20}  ({source})")
                    continue
                # Validate by resolving (returns "" overlay if unknown,
                # but we still allow it -- user might be staging a name).
                _, source = _styles.resolve_overlay(rest, cwd)
                settings.output_style = rest
                print(
                    f"[output style set to {rest!r} ({source}); "
                    "applies to NEW sessions -- use /clear to apply now]"
                )
                continue
            if cmd == "effort":
                from settings import VALID_EFFORTS, Settings as _S
                if settings is None:
                    settings = _S()
                if not rest:
                    print(
                        f"current effort: {settings.effort}"
                        f"\nvalid: {', '.join(VALID_EFFORTS)}"
                    )
                    continue
                if rest not in VALID_EFFORTS:
                    print(f"unknown effort {rest!r}; valid: {', '.join(VALID_EFFORTS)}")
                    continue
                settings.effort = rest
                print(f"[effort set to {rest!r}]")
                continue
            if cmd == "mode":
                from settings import VALID_MODES
                if not rest:
                    print(
                        f"current mode: {settings.mode if settings else 'default'}"
                        f"\nvalid: {', '.join(VALID_MODES)}"
                    )
                    continue
                if rest not in VALID_MODES:
                    print(f"unknown mode {rest!r}; valid: {', '.join(VALID_MODES)}")
                    continue
                if settings is None:
                    from settings import Settings as _S
                    settings = _S(mode=rest)
                else:
                    settings.mode = rest
                print(f"[mode set to {rest!r}]")
                continue
            if cmd == "autobuild":
                # Tier 3: agent autobuild status + control.
                import agent_search as _search
                sub = rest.strip().split(None, 1)
                action = sub[0].lower() if sub else ""
                action_arg = sub[1].strip() if len(sub) > 1 else ""
                if settings is None:
                    from settings import Settings as _S
                    settings = _S()
                if not hasattr(settings, "raw") or not isinstance(
                        settings.raw, dict):
                    settings.raw = {}
                ab_cfg = settings.raw.setdefault("autobuild", {})
                if not action:
                    enabled = ab_cfg.get("enabled", True)
                    print(f"autobuild: {'on' if enabled else 'off'}")
                    docs = _search.discover_indexable_agents(cwd)
                    if not docs:
                        ui.empty_listing("(no agents in library yet)",
                                         kind="agents")
                    else:
                        ui.table(
                            title=f"Agent library ({len(docs)} total)",
                            columns=["NAME", "SOURCE", "DOMAIN",
                                     "DESCRIPTION"],
                            rows=[
                                [d.name, d.source, d.domain or "-",
                                 (d.description[:55] + "...")
                                 if len(d.description) > 55
                                 else d.description]
                                for d in docs
                            ],
                        )
                elif action == "on":
                    ab_cfg["enabled"] = True
                    print("[autobuild: on]")
                elif action == "off":
                    ab_cfg["enabled"] = False
                    print("[autobuild: off]")
                elif action == "approve":
                    if not action_arg:
                        print("usage: /autobuild approve <name>")
                        continue
                    import agent_builder as _ab
                    ok_, msg, live = _ab.approve_pending(cwd, action_arg)
                    print(f"[autobuild approve: {msg}]")
                elif action == "reject":
                    if not action_arg:
                        print("usage: /autobuild reject <name>")
                        continue
                    import agent_builder as _ab
                    ok_, msg = _ab.reject_pending(cwd, action_arg)
                    print(f"[autobuild reject: {msg}]")
                elif action == "pending":
                    import agent_builder as _ab
                    pending = _ab.list_pending(cwd)
                    if not pending:
                        ui.empty_listing(
                            "(no specialists awaiting approval)",
                            kind="pending_agents",
                        )
                    else:
                        ui.table(
                            title=f"Pending specialists ({len(pending)})",
                            columns=["NAME", "PATH"],
                            rows=[[p.stem, str(p)] for p in pending],
                        )
                elif action == "history":
                    if not action_arg:
                        print("usage: /autobuild history <name>")
                        continue
                    import agent_builder as _ab
                    versions = _ab.list_versions(cwd, action_arg)
                    if not versions:
                        ui.empty_listing(
                            f"(no archived versions for {action_arg!r})",
                            kind="agent_history",
                        )
                    else:
                        ui.table(
                            title=f"Versions of {action_arg} "
                                  f"({len(versions)})",
                            columns=["TIMESTAMP", "PATH"],
                            rows=[[v.stem, str(v)] for v in versions],
                        )
                elif action == "revert":
                    if not action_arg:
                        print("usage: /autobuild revert <name> [ts-prefix]")
                        continue
                    parts2 = action_arg.split(None, 1)
                    nm = parts2[0]
                    ts = parts2[1].strip() if len(parts2) > 1 else None
                    import agent_builder as _ab
                    ok_, msg = _ab.revert_to_version(cwd, nm, ts)
                    print(f"[autobuild revert: {msg}]")
                elif action == "search":
                    if not action_arg:
                        print("usage: /autobuild search <query>")
                        continue
                    hits = _search.search_agents(cwd, action_arg, limit=10)
                    if not hits:
                        ui.empty_listing(f"[no matches for {action_arg!r}]",
                                         kind="agents")
                    else:
                        ui.table(
                            title=f"BM25 matches for {action_arg!r}",
                            columns=["SCORE", "NAME", "SOURCE",
                                     "DESCRIPTION"],
                            rows=[
                                [f"{score:.3f}", doc.name, doc.source,
                                 (doc.description[:50] + "...")
                                 if len(doc.description) > 50
                                 else doc.description]
                                for doc, score in hits
                            ],
                        )
                else:
                    print(f"unknown /autobuild action: {action!r}")
                continue
            if cmd in ("loop", "schedule"):
                # Tier 2 #24: /loop and /schedule
                import schedule as _sched
                parts = rest.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"usage: /{cmd} <duration> <task>")
                    continue
                duration_str, task_text = parts[0], parts[1]
                try:
                    secs = _sched.parse_duration(duration_str)
                except ValueError as exc:
                    print(f"[bad duration: {exc}]")
                    continue

                def _make_cb(t: str):
                    """Returns a callback(iter_n) -> bool that runs `task_text` once."""
                    def cb(iter_n: int) -> bool:
                        nonlocal history, current_model
                        if not quiet:
                            print(f"\n[/{cmd} iter {iter_n}: {t[:80]}]",
                                  file=sys.stderr)
                        task_expanded, _refs = expand_file_refs(t, cwd)
                        try:
                            exit_code, metrics = run_loop(
                                task=task_expanded,
                                model=current_model, api_key=api_key,
                                max_iterations=max_iterations,
                                store=store, session=session,
                                initial_history=history,
                                verbose=not quiet, stream=stream,
                                system_instruction=system_instruction,
                                fire_session_start=False,
                                settings=settings, is_repl=True, ui=ui,
                                llm=llm,
                            )
                        except KeyboardInterrupt:
                            return False
                        history, _ = store.load_history(session, resume_max_messages)
                        if metrics.get("model") and metrics["model"] != current_model:
                            current_model = metrics["model"]
                        return True  # keep looping (only used by /loop)
                    return cb

                if cmd == "loop":
                    if not quiet:
                        print(
                            f"[/loop starting; interval={duration_str} ({secs:g}s); Ctrl-C to stop]",
                            file=sys.stderr,
                        )
                    stats = _sched.run_loop_with_interval(
                        _make_cb(task_text), secs,
                    )
                    if stats.interrupted:
                        print(f"[/loop interrupted after {stats.iterations} iteration(s)]")
                    elif stats.early_stopped:
                        print(f"[/loop stopped early after {stats.iterations} iteration(s)]")
                    else:
                        print(f"[/loop completed {stats.iterations} iteration(s)]")
                    if stats.errors:
                        print(f"  errors: {len(stats.errors)}")
                else:  # /schedule
                    if not quiet:
                        print(
                            f"[/schedule sleeping {duration_str} ({secs:g}s); Ctrl-C to cancel]",
                            file=sys.stderr,
                        )
                    stats = _sched.run_schedule_delayed(
                        _make_cb(task_text), secs,
                    )
                    if stats.interrupted:
                        print("[/schedule cancelled before run]")
                    else:
                        print("[/schedule completed]")
                continue
            if cmd == "skill":
                if not rest:
                    print("usage: /skill <name> [--refresh] [args...]")
                    continue
                import skills as _skills
                parts = rest.split()
                # --refresh anywhere in the args bypasses cache for this call
                use_cache = "--refresh" not in parts
                parts = [p for p in parts if p != "--refresh"]
                if not parts:
                    print("usage: /skill <name> [--refresh] [args...]")
                    continue
                skill_name = parts[0]
                skill_args = " ".join(parts[1:]) if len(parts) > 1 else ""
                sk = _skills.find_skill_by_name(cwd, skill_name)
                if sk is None:
                    print(f"no skill named {skill_name!r}; try /skills")
                    continue
                expanded = _skills.expand_skill_body(
                    sk, skill_args, cwd, use_cache=use_cache,
                )
                if not quiet:
                    print(
                        f"[invoking skill {skill_name!r} "
                        f"({len(expanded)} chars expanded)]",
                        file=sys.stderr,
                    )
                line = expanded  # fall through to UserPromptSubmit + run_loop
            else:
                print(f"unknown command: /{cmd}. /help for the list.")
                continue

        # UserPromptSubmit hook: can transform or block the prompt.
        import hooks as _hooks
        ups = _hooks.fire(
            "UserPromptSubmit", cwd,
            session_id=session.id, payload={"prompt": line},
        )
        if ups.block:
            print(f"[UserPromptSubmit hook blocked: {ups.reason}]",
                  file=sys.stderr)
            continue
        effective_prompt = ups.transformed_prompt if ups.transformed_prompt else line

        task_expanded, refs = expand_file_refs(effective_prompt, cwd)
        if refs and not quiet:
            print(
                f"[expanded {len(refs)} @-file reference(s): "
                f"{', '.join(r['token'] for r in refs)}]",
                file=sys.stderr,
            )

        is_first_turn = not history
        try:
            exit_code, metrics = run_loop(
                task=task_expanded,
                model=current_model,
                api_key=api_key,
                max_iterations=max_iterations,
                store=store,
                session=session,
                initial_history=history,
                verbose=not quiet,
                stream=stream,
                system_instruction=system_instruction,
                fire_session_start=is_first_turn,
                settings=settings,
                is_repl=True,
                ui=ui,
                llm=llm,
            )
        except KeyboardInterrupt:
            print("\n[interrupted; returning to prompt]", file=sys.stderr)
            continue

        history, _ = store.load_history(session, resume_max_messages)

        if metrics.get("model") and metrics["model"] != current_model:
            current_model = metrics["model"]

        if show_metrics:
            total = store.aggregate_metrics(session)
            sys.stderr.write(
                f"[turn] model={metrics['model']} iters={metrics['iterations']} "
                f"in_tok={metrics['total_input_tokens']} "
                f"out_tok={metrics['total_output_tokens']} "
                f"wall={metrics['wall_seconds']:.2f}s | "
                f"cumulative in_tok={total['input_tok']} out_tok={total['output_tok']}\n"
            )

    print("goodbye.")
    return 0
