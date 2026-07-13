# Baton project guide

## What and why

Baton is a standard-library Python CLI for delegating scoped coding tasks to separate agent processes. One orchestrator creates tasks, runs dependency-ready workers in parallel waves, and reviews each report and Git diff.

A generated Critical Context Capsule appears at both edges of every worker prompt; action-time briefs gate `task finish` and `task accept` with one-use tokens; orchestrator sessions receive phase briefs and a bounded state handoff; and optional Claude Code hooks restore current state after compaction. The design is grounded, with explicit limits, in `docs/research-synthesis.md` and `docs/context-placement.md`; its revision-specific activation cost and direct-execution break-even are measured in `docs/context-footprint.md`.

Baton coordinates external worker CLIs. It is not an agent model, package manager, patch queue, or security sandbox.

## Current state

- The release-candidate implementation and documentation use Baton as the canonical name and target `https://github.com/jpawchan/baton`; the GitHub rename is intentionally deferred until local verification is complete.
- The current CLI includes generated dual-edge capsules, phase receipts and one-use gates, bounded cross-session handoffs, strict difficulty tiers, read-only statistics, and optional compaction-aware Claude Code hooks.
- The seven malformed-input and report-integrity defects documented in `docs/bug-audit.md` are fixed with regression coverage. The performance changes and their measured limits are recorded in `docs/performance.md`.
- The end-to-end suite contains 121 tests; run it rather than relying on this count after later edits. A framework-owned `baton orchestrate` process remains deliberately out of scope.
- The repository's live, Git-ignored `.baton/` directory is dogfooding state and audit history, not project source; do not edit or delete it casually.

## Run and verify

Requirements: Python 3.11+, Git on `PATH`, macOS or Linux. No dependency install, build step, server, or database exists.

```bash
cd <repo-root>
python3 framework/baton --help
python3 -m py_compile framework/baton tests/test_baton.py tools/measure_context.py tests/test_context_footprint.py
python3 tests/test_baton.py
python3 tests/test_context_footprint.py
```

Expected: the help usage line includes `stats` and `tiers`; py_compile is silent; the primary suite runs 121 tests and the focused context-footprint suite runs four tests, with both unittest summaries ending in `OK`. The expected `[T001-lease-guard] stale finalizer ignored` probe diagnostic may follow the primary suite (temp Git repos and stub workers, no network or live agent calls).

If you run the suite from inside a Baton-leased worker process, unset the inherited worker env first or fixtures will reject orchestrator commands:

```bash
env -u BATON_TASK_ID -u BATON_ATTEMPT -u BATON_LEASE -u BATON_DIR -u BATON_ROOT python3 tests/test_baton.py
```

Disposable end-to-end smoke (verified this session). The `cd "$tmp"` matters:
runtime discovery is `BATON_DIR` env first, else a walk UP from the current
directory — running a temp project's `baton` from inside this repo would
silently target this repo's own runtime instead.

```bash
tmp=$(mktemp -d) && git -C "$tmp" init -q && git -C "$tmp" config user.name T && git -C "$tmp" config user.email t@example.invalid
echo seed > "$tmp/seed.txt" && git -C "$tmp" add -A && git -C "$tmp" commit -qm seed
./framework/baton init "$tmp"
(cd "$tmp" && .baton/baton orchestrator brief --phase start && .baton/baton validate)
rm -rf "$tmp"
```

Expected: init ends with `next: have your agent read .baton/orchestrator.md and run .baton/baton orchestrator brief --phase start`; the start brief prints the orchestrator role, a `Harness memory:` section, a `Difficulty levels:` section (fresh installs have no level tiers), and `Next actions:`; validate prints `ok: 0 active task(s)`.
Do not smoke-test a real worker unless the configured worker CLI and its credentials work locally.

## Stack

| Layer | Verified implementation |
| --- | --- |
| Language | Python 3.11+; the entire production CLI is the single file `framework/baton`. |
| Dependencies | Python standard library only; no manifest or lockfile exists. |
| CLI | `argparse` subcommands built in `build_parser()`. |
| Concurrency | `ThreadPoolExecutor` launches one wave of worker subprocesses; POSIX `fcntl.flock` locks; `secrets.token_hex` for gate tokens. |
| Processes | `subprocess.Popen(..., start_new_session=True)`; process-group signalling on timeout/interrupt. |
| Configuration | TOML via `tomllib`; runtime state is JSON records plus Markdown specs/reports/briefs/handoff. |
| Version control | Git CLI snapshots with a temporary `GIT_INDEX_FILE`; no Git library. |
| Tests | `unittest` end-to-end cases in `tests/test_baton.py` with temp repos and embedded stub workers. |
| CI | `.github/workflows/ci.yml`: push+PR, Ubuntu/macOS × Python 3.11/3.13, `checkout@v7`, `setup-python@v6`, 10-minute timeout. |
| License | MIT (`LICENSE`). |

Baton itself makes no HTTP requests. The configured worker command (default: Hermes with `--ignore-rules`) is the only connection to an agent CLI.

## Repository map

| Path | Role |
| --- | --- |
| `framework/baton` | Entire production CLI: paths, config, capsule compiler, tasks, briefs/tokens, scopes, Git snapshots, runner, handoff, hooks, validation, archive, memory, parser. |
| `framework/orchestrator.md` | Orchestrator manual: phase briefs, task creation, waves, token-gated review, handoff, failure handling, memory. |
| `framework/worker.md` | Worker contract: capsule re-reads, phase briefs, scope rules, report shape, token-gated finish. |
| `framework/config.example.toml` | Default worker command (memory-clean Hermes), tiers, limits, gates; copied to runtime `config.toml` on init. |
| `framework/memory.md` | Empty indexed-memory template copied on first initialization. |
| `tests/test_baton.py` | Canonical 121-test end-to-end suite and all stub worker fixtures. |
| `SPEC.md` | Normative behavioral contract; embedded byte-identically in `prompts/create-framework.md`. |
| `prompts/create-framework.md` | Standalone generation prompt with the embedded exact SPEC copy (BEGIN SPEC / END SPEC markers). |
| `prompts/improve-framework.md` | Review prompt naming required v1 safety and v2 capsule/token/handoff/hook checks. |
| `prompts/use-framework.md` | Short instruction that activates an installed orchestrator (read manual → start brief → memory choices). |
| `skill/SKILL.md` | Portable skill metadata, install command, invariants. |
| `docs/context-placement.md` | Research rationale, linked sources, rejected alternatives, limits, and experiment requirements for capsule edge placement. |
| `docs/research-synthesis.md` | Primary-source-grounded long-context synthesis, claim mapping, and limits. |
| `docs/context-footprint.md` | Reproducible activation footprint, provider differentials, and break-even guidance. |
| `docs/bug-audit.md` | Correctness audit with reproductions and fix dispositions. |
| `docs/performance.md` | Profiling method, benchmark evidence, and rejected optimizations. |
| `docs/github-description.txt` | Short public repository description. |
| `tools/` | Context-measurement and performance-benchmark scripts plus recorded provider evidence. |
| `tests/test_context_footprint.py` | Activation-footprint reproducibility checks. |
| `README.md` | Public explanation, evidence, requirements, install, usage, and repository map. |
| `summary.md` | This guide. |
| `.github/workflows/ci.yml` | Only CI workflow. |

### Code regions in `framework/baton` (by function, top to bottom)

| Concern | Start here |
| --- | --- |
| Runtime discovery, safety | `find_baton_dir`, `runtime_paths_are_safe`, `require_baton_dir`; `BATON_DIRNAME = ".baton"`. |
| Locks and atomic state | `file_lock`, `task_lock`, `atomic_write`, `atomic_json`, `lock_path`. |
| Config | `load_config`, `cfg_get`, the `configured_*` readers (including `configured_tier` and the default-off phase-sequence gate), `validate_worker_template`, `command_template`, `worker_argv`; difficulty-level onboarding via `conventional_level_names` + `difficulty_levels_lines`. |
| Paths and review evidence | `report_path`, `result_path`, `diff_path`, `sha256_regular_file`, `build_review_evidence_manifest`, streaming `attempt_diff_summary`, `sanitize_log_text` + bounded `bounded_log_tail`, `brief_token_path` (finish-brief-token.json), `review_token_path` (review-brief-token.json), and phase receipts via `phase_receipts_path` + `read_phase_receipts` (attempt-N.briefs.json). |
| Capsule | `CAPSULE_SECTIONS`, `task_spec_sections`, `memory_index_entries`, `context_capsule_components` + `compile_context_capsule` (deterministic, budgeted, placeholder- and memory-reference-validating), `stored_context_capsule_components` (launch-snapshot parsing), `report_section_problems` (report gate parser). |
| Task lifecycle commands | `cmd_task_create`, `cmd_task_list/show`, `cmd_task_capsule` (read-only preview, `--raw`), `cmd_task_accept` (review-token + evidence gate), `cmd_task_return/decide/cancel` (invalidate review token), `cmd_task_finish` (finish-token + report-shape gates), `cmd_task_brief` (worker phases, receipts, report token), `cmd_task_unlock`. |
| Next-actions capsule | `flatten_bounded_text`, `decision_question`, `render_next_actions`, `say_next_actions` (tails `status`, `task show`, real `run`; globally budgets five review/decision/overflow lines). |
| Orchestrator briefs | `orchestrator_start_brief` (consumes handoff under the `orchestrator-handoff` lock), `orchestrator_plan_brief`, `orchestrator_review_brief` (issues review token), `orchestrator_run_brief`, `working_tree_state` + `render_handoff` + `orchestrator_close_brief` (pre-lock close snapshot and 4000-character goal/outcome/warning/notes/avoid handoff), `cmd_orchestrator_brief`. |
| Claude Code hooks | `claude_code_hook_fragment`, `cmd_hooks_claude_code` (print/merge, idempotent), `cap_hook_output` (hard 9000-char cap, fail-open), `claude_user_prompt_output`, `cmd_hook_event`. |
| Git snapshots and scopes | `git_snapshot`, `git_changed_paths`, `git_tree_diff`, `normalize_scope`, `scopes_overlap`, `path_in_scopes`. |
| Worker launch and waves | `WORKER_PROMPT`, `build_prompt` (capsule sandwich), `prepare_worker` (writes attempt-N.prompt.md + attempt-N.brief.md with sha256 digest), `run_one_worker`, `pick_wave`, `finalize_task`, `cmd_run`, `run_wave`. |
| Validation, tiers, stats, archive, memory, CLI | `task_problems` (includes strict tier and per-tier queued-capsule checks), read-only `cmd_tiers`/`cmd_stats`, `cmd_validate`, `cmd_archive`, `cmd_memory_*`, `cmd_init`, `build_parser`, `main`. |

## How it works

Runtime layout after `.baton/baton init <git-root>` (all Git-ignored):

```text
<git-root>/.baton/
├── baton, orchestrator.md, worker.md, memory.md, config.toml
├── orchestrator-handoff.md      written by close brief, consumed by start brief
├── tasks/<id>.json + <id>.md    state records and hand-edited specs
├── work/<id>/attempt-N.{prompt.md,brief.md,briefs.json,log,report.md,result.json,diff}
│   └── {finish,review}-brief-token.json   one-use gate tokens
├── archive/                     done/cancelled tasks
└── .locks/                      scheduler, execution, memory, per-task, orchestrator-handoff
```

End-to-end flow with the v2 edge mechanisms marked:

```text
orchestrator brief --phase start      <- beginning edge: role + handoff + Harness memory + optional difficulty ask + next actions
   | task create -> edit spec (Objective/Acceptance criteria/... are the capsule source)
   v
run: pick_wave -> prepare_worker compiles capsule
   |   launch prompt = CAPSULE + mechanics + CAPSULE   <- both worker edges
   v
worker: task brief --phase edit|verify|report          <- bounded receipts; report issues token
   |    task finish --brief TOKEN                      <- token + needs_review report-shape gates (default on)
   v
finalize: attempt diff vs wave snapshot, scope check
   v
orchestrator brief --phase review ID -> diff stat/history + token/evidence manifest <- decision edge
   |    task accept --brief TOKEN verifies evidence               <- gate (default on)
   v
status/show/run output ends with "Next actions:"       <- recency edge, any harness
orchestrator brief --phase close --goal TEXT [--note TEXT]... [--avoid TEXT]... -> handoff written <- next session edge
```

Statuses: `queued → running → needs_review → done`, or `needs_decision`/`blocked`/`failed → queued` (after decide/repair/return). Workers can submit only the four `WORKER_FINAL` statuses; only `task accept` records `done`.
Scope enforcement, temp-index Git snapshots, leases, and archive semantics are inherited from v1 unchanged: every changed path outside the wave's scopes blocks the wave; declared `--changed` paths must equal the observed scoped diff case-insensitively.

Claude Code integration (opt-in): `.baton/baton hooks claude-code [--write]` prints or merges two matcher-free hooks into the project's `.claude/settings.json` — SessionStart runs `hook-event session-start` (start brief as stdout → session context, including explicit state re-injection after automatic or manual compaction, but without repeating the Difficulty levels ask after compaction) and UserPromptSubmit runs `hook-event user-prompt-submit` (JSON `additionalContext` with the Next-actions capsule). Both cap output at 9000 chars and emit nothing (exit 0) on any error.

## Configuration

`.baton/config.toml` (user-managed; source default is `framework/config.example.toml`):

| Key | Purpose |
| --- | --- |
| `commands.worker` | Worker argv template with exactly one `{prompt}` or `{prompt_file}` argument; default is Hermes with `--ignore-rules` (memory-clean). |
| `tiers.<name>.command` | Optional per-tier command override; non-default task tiers must be configured and limits-only tiers inherit the default command. |
| `tiers.<name>.worker_timeout_minutes` | Optional per-tier worker timeout override; unset inherits the global timeout. |
| `tiers.<name>.capsule_max_chars` | Optional per-tier capsule budget override; unset inherits the global budget. |
| `tiers.<name>.display` | Optional bounded safe `model`, `harness`, `effort`, `engineering_role`, and `fallback` declarations; missing metadata displays `unlabeled worker` and metadata never changes routing. |
| `limits.max_parallel` | Wave size (default 3). |
| `limits.worker_timeout_minutes` | Worker timeout; 0 disables. |
| `limits.capsule_max_chars` | Capsule budget (default 4000); overflow is a launch/validate error, never truncation. |
| `gates.finish_requires_brief` | Default true: `task finish` needs a fresh report-phase brief token. |
| `gates.report_requires_sections` | Default true: `needs_review` reports need the exact worker.md sections, nonblank core bodies, and matching Result status. |
| `gates.accept_requires_brief` | Default true: `task accept` needs a fresh review-phase brief token. |
| `gates.phase_sequence_requires_briefs` | Default false: optionally require edit → verify → report receipts; a new edit after report invalidates the finish token. |

Environment variables (all read/written in `framework/baton`): `BATON_DIR` (runtime override in, worker export out), `BATON_TASK_ID`, `BATON_ATTEMPT`, `BATON_LEASE`, `BATON_ROOT` (worker exports; their presence marks a process as a leased worker and blocks orchestrator commands). There is no `.env`; worker credentials belong to the external agent CLI.

Every task creation requires an explicit validated tier; even `default` must be
named rather than silently selected. Requested coding routes are hard = GPT 5.6
Sol/high/elite senior, medium = GPT 5.6 Sol/medium/elite senior, and easy = Claude
Code Opus 4.8/xhigh/senior with GPT 5.6 Terra/high only when Claude usage is
exhausted. Until all three matching tables exist, the start brief prints
missing-only routing skeletons and `.baton/baton tiers` appends a missing-level
hint. Configuration and tier selection remain explicit user and orchestrator
actions.

## Landmines

- `SPEC.md` is normative and embedded byte-identically in `prompts/create-framework.md` between `BEGIN SPEC`/`END SPEC`; a test fails on drift. Change SPEC → regenerate the embedded copy in the same change.
- The capsule is always GENERATED from the spec's existing sections (`Objective`, `Acceptance criteria`, `Not allowed`, `Verification`, latest feedback/decision) plus summaries for up to six worker-visible memory ids referenced only in `Context`. Never add a hand-edited capsule section, copy full memory bodies, or duplicate criteria; the stored launch capsule is the immutable audit snapshot and review warns on input drift.
- Template-placeholder specs refuse to launch and fail `validate`. Test fixtures must write real Objective/Acceptance criteria before `run`.
- The finish, report-structure, and accept gates default ON; the phase-sequence gate defaults OFF. Phase receipts are always recorded. Stub workers that submit `needs_review` must write the exact worker.md report shape, call `task brief --phase report`, and pass the token to `finish`; orchestrator fixtures need `orchestrator brief --phase review ID` tokens for `accept` (or set the relevant gate key false in the fixture's config.toml).
- Gate tokens are one-use and bound to (task, attempt, lease)/(task, attempt, review-evidence manifest); issuance, evidence verification, and consumption happen under the task lock. Do not weaken bindings — replay across attempts/leases must fail, and evidence mismatches must not consume review tokens.
- The `orchestrator-handoff` lock is a leaf: start holds it for handoff consumption; close validates flags, loads active/archive state, gathers candidates, and checks Git before locking, then holds it only for previous-handoff read, dedupe/render, and atomic write. Never acquire task/scheduler locks while holding it.
- Handoff `done` entries dedupe by task id against the previous handoff (same-second boundary). Don't simplify to a pure timestamp comparison; whole-second `now()` makes `>` and `>=` both wrong alone.
- Every close brief requires a fresh explicit nonblank `--goal`; never restore goal inheritance. Goal and up to five repeatable `--avoid` values use `flatten_bounded_text(..., 200)`. Up to three trusted `--note` values use 160 characters, omit blanks/duplicates and the empty section, and must not contain secrets; durable facts belong in memory or this guide. Done outcomes come only from the matched accepted-event note and use 120 characters. The writer drops outcome suffixes, then reduces done/decisions, then next/unresolved with accurate overflow markers to stay at most 4000 characters.
- `cap_hook_output` returning `""` (and adapters emitting nothing, exit 0) is deliberate fail-open, spec'd behavior — don't "fix" silence into errors, and keep every emission ≤ 9000 chars including edge lines.
- `hooks claude-code --write` must merge idempotently (detected by exact command string) and never drop existing entries; refusal on invalid JSON is intentional (no partial writes).
- `--ignore-rules` in the default Hermes worker command is deliberate memory hygiene (keeps model config). Do not swap in `--safe-mode` (drops user config, loses the model) or `hermes memory reset` (destructive).
- `claude --bare` conflicts with the hook integration (it disables hooks); the start brief and README state this — keep the warning when editing either.
- Worker-facing command examples must use `python3 .baton/baton ...` or `.baton/baton ...`; bare `baton` is not on PATH in installed projects.
- Runtime discovery is `BATON_DIR` env first, else a walk up from the CURRENT directory — never the invoked binary's location. Invoking another project's `baton` from inside this repo targets this repo's runtime; `cd` into the intended project first (see the smoke).
- Run the suite with `BATON_*` unset if inside a leased worker (see Run and verify).
- v1 invariants still apply: stdlib only; no Windows (`fcntl`, process groups); init target must be `git rev-parse --show-toplevel`; no submodules/Gitlinks; keep temp-index snapshots (not `git diff HEAD`); scopes case-fold; workers share one tree (no isolation); `accept` records review, `return` never reverts; don't hand-edit task JSON; archive preflight+rollback and signal masking stay; task numbers never reuse across archive.
- `worker_timeout_minutes` default is 60: long-thinking workers on hard tasks can hit it; prefer smaller tasks or a deliberate per-tier override over raising it globally.
- An external provider failure (for example, HTTP 429 quota) after a fully valid submission preserves the submitted status and records a `worker_exit_N_after_submission` warning. Before accepting, reviewers must inspect the prominent review-brief warning and linked attempt log; failures before submission still surface as `failed` with `worker_exit_N` and require a return/retry.

## Guide self-test routes

| Plausible task | Guide-only starting route |
| --- | --- |
| Fix a capsule validation message | `compile_context_capsule` in `framework/baton`; capsule tests in `tests/test_baton.py`; SPEC.md + embedded copy only if wording is normative. |
| Add a new orchestrator brief phase | `orchestrator_*_brief` functions + `cmd_orchestrator_brief` + `build_parser` in `framework/baton`; `framework/orchestrator.md`; SPEC.md + embedded copy; new tests. |
| Change the default capsule budget | `configured_capsule_max_chars` in `framework/baton`; `framework/config.example.toml`; SPEC.md + embedded copy; budget tests in `tests/test_baton.py`. |
| Add a field to `.baton/baton stats` output | `cmd_stats` + `stats_count_lines` in `framework/baton` (receipts via `read_phase_receipts`); SPEC.md stats sentences + embedded copy; stats fixture tests in `tests/test_baton.py`. |

Last updated 2026-07-13 — Documentation rewrite against the release-candidate implementation, research synthesis, activation measurement, correctness audit, and performance report.
