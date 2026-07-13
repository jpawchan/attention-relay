# Baton correctness audit

Date: 2026-07-13

## Executive summary

The complete production CLI, normative specification, manuals, configuration,
tests, recent Git history, and activation-footprint tooling were reviewed before
classifying defects. The baseline suite passed all 106 tests. Seven defects were
confirmed with deterministic fresh-project reproductions, each run twice:

| ID | Severity | Summary |
| --- | --- | --- |
| B1 | medium | Exact changed-path declarations reject or alter valid POSIX filenames because they are parsed as scope globs. |
| B2 | medium | `validate` trusts the top-level JSON and history-entry shapes, producing tracebacks or a false `ok`. |
| B3 | medium | The review-report gate treats empty fenced blocks as nonblank Changes and Verification bodies. |
| B4 | medium | `memory add` accepts values that corrupt the strict memory grammar and can create unindexed entries. |
| B5 | medium | A multiline task title can inject task-spec sections and replace the Objective used by capsule compilation. |
| B6 | low | Tier display metadata accepts command flags when punctuation immediately precedes the flag. |
| B7 | medium | A report changed after `task finish` is not structure-checked again and can reach `done`. |

No production code, tests, task state, dependencies, or history were changed by
this audit. Temporary reproduction drivers and projects were created outside the
repository and removed or left under the operating system's temporary directory.

## Review basis and method

### Material read

The review covered all 4,060 lines of `framework/baton`, all 3,857 lines of
`tests/test_baton.py`, `SPEC.md`, `README.md`, `summary.md`,
`framework/orchestrator.md`, `framework/worker.md`, `framework/memory.md`,
`framework/config.example.toml`, `docs/context-placement.md`,
`docs/context-footprint.md`, all three framework prompts, `skill/SKILL.md`, the
CI workflow, `tools/measure_context.py`, and `tests/test_context_footprint.py`.
The byte-equality test covers the remainder of the normative SPEC embedded in
`prompts/create-framework.md`.

Recent history was inspected through `d357401`, `6026134`, `53fa914`,
`7aa017c`, `fcd33a0`, `e18f482`, `6be5c3c`, `98840d9`, `149ff5c`, and
`4697fc9`, including patches affecting the CLI, tests, SPEC, manuals, and config.
This was important because `e18f482` fixed an earlier five-defect review and the
later commits substantially changed handoff and tier behavior.

### Baseline before conclusions

Exact command:

```text
python3 tests/test_baton.py
```

Result:

```text
Ran 106 tests in 132.335s
OK
```

### Reproduction convention

The commands below are the exact commands used for both reruns. The temporary
standard-library driver `/tmp/baton_audit_probe.py` (and its small companion
`/tmp/baton_audit_extra.py`) initialized a new temporary Git repository, ran the
current checkout's `framework/baton init`, used synthetic inputs only, printed
the listed fields, and cleaned the project. It did not read credentials or print
worker logs. Each `for i in 1 2` command produced the two identical result blocks
shown for its defect. Inputs and state transitions are also spelled out below so
the regression can be recreated directly in `BatonTests` without that driver.

## Confirmed defects

### B1 — exact changed paths are parsed as scope patterns

Severity: medium.

Disposition: fixed. `test_changed_paths_preserve_literal_posix_filename_characters`
reproduces the failure through a real worker and covers brackets, glob characters,
leading/trailing spaces, and a literal backslash. The verified root cause was
unchanged; changed paths now use a dedicated canonical literal-path validator and
never pass through scope/glob normalization.

Violated invariant: SPEC lines 187–190 require every worker to declare each
*exact* changed path and compare that declaration with the observed scoped diff.
The scope-language restriction on character classes at SPEC lines 148–151 is a
restriction on patterns, not on literal filenames. A task scoped to `src/**`
can legitimately change the POSIX filename `src/[id].txt`, but no worker can
submit that exact path.

Exact reproduction input:

1. Initialize a fresh project, explicitly configure a test tier, and create a
   valid task in that tier scoped to `src/**`.
2. Lease attempt 1 and obtain a report-phase finish token.
3. Run `task finish ... --status failed --brief TOKEN --changed 'src/[id].txt'`.
4. The bounded generated-input comparison also called
   `normalize_changed_paths` with `src/[id].txt`, `src/what?.txt`,
   `src/star*.txt`, `src/ trailing.txt `, and `src/café-東京-😀.txt`.

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_extra.py exact-path; done
RUN=1
finish_rc=1
finish_stderr=error: scope supports *, **, and ? but not character classes
RUN=2
finish_rc=1
finish_stderr=error: scope supports *, **, and ? but not character classes
```

The companion generated-input result was identical on both runs:

```text
normalize 'src/[id].txt' -> ERROR scope supports *, **, and ? but not character classes
normalize 'src/what?.txt' -> ERROR changed paths must be exact project-relative paths
normalize 'src/star*.txt' -> ERROR changed paths must be exact project-relative paths
normalize 'src/ trailing.txt ' -> ['src/ trailing.txt']
normalize 'src/café-東京-😀.txt' -> ['src/café-東京-😀.txt']
```

Observed versus expected: finish rejects literal bracket, question-mark, and
asterisk filenames and silently removes trailing whitespace. It should preserve
and accept each safe project-relative literal path byte-for-byte (subject to
filesystem decoding), then let finalization compare it with Git's observed path.
The ordinary Unicode filename is correctly preserved.

Root-cause data flow:

- `cmd_task_finish` passes every `--changed` value to
  `normalize_changed_paths` (`framework/baton:1830-1843`).
- `normalize_changed_paths` delegates literal paths to `normalize_scope`
  (`framework/baton:1117-1128`).
- `normalize_scope` strips leading/trailing whitespace and applies scope-only
  syntax bans for backslashes, `..`, brackets, and malformed `**`
  (`framework/baton:1021-1047`).
- `normalize_changed_paths` then rejects `*` and `?` after that scope parsing.
  Thus an exact filename is incorrectly interpreted as a glob expression before
  being stored in the result.

Affected siblings: literal names containing `[` or `]`, `*`, `?`, a backslash
(on Linux/macOS POSIX filesystems), and leading or trailing whitespace. The same
path-normalization function is used by manually written worker results through
`worker_changed_paths` during finalization (`framework/baton:2943-2952`), so
bypassing the CLI does not avoid the mismatch.

Minimal regression test: a real stub worker under scope `src/**` creates
`src/[id].txt`, reports exactly that path, and must reach `needs_review` with
identical declared and observed lists. Parameterize sibling literal names,
including trailing whitespace where the test filesystem supports it.

Robust fix direction: add a dedicated literal changed-path validator. It should
reject absolute paths, empty paths, NUL, traversal components, and noncanonical
separators as appropriate, but must not trim or interpret legal filename
characters as pattern syntax. Keep scope normalization separate.

### B2 — malformed task JSON escapes validation

Severity: medium.

Disposition: fixed. `test_validate_rejects_non_object_task_state_and_malformed_history`
covers a top-level array; numeric, null, array, and string history members; and
missing or incorrectly typed required history fields. The verified root cause was
unchanged. Task loading now rejects shapes unsafe for lifecycle consumers with a
concise domain error, while `validate` loads mapping-shaped state in diagnostic mode
and reports all history-record problems without invoking those consumers.

Violated invariant: `validate` is the documented task-state checker and SPEC
lines 63–83 define an object with a list of history records. It must report
malformed state deterministically rather than traceback, and it must not print
`ok` for state that crashes a subsequent documented command.

Exact reproduction input:

1. Replace a fresh task state file with the valid JSON value `[]`; run
   `.baton/baton validate`.
2. In a fresh valid task object, replace `history` with `[1]`; run `validate`,
   then `orchestrator brief --phase close --goal next`.

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py validate-json; done
RUN=1
list_state_rc=1
list_state_stderr_last=AttributeError: 'list' object has no attribute 'get'
history_entry_rc=0
history_entry_stdout=ok: 1 active task(s)
close_rc=1
close_stderr_last=AttributeError: 'int' object has no attribute 'get'
RUN=2
list_state_rc=1
list_state_stderr_last=AttributeError: 'list' object has no attribute 'get'
history_entry_rc=0
history_entry_stdout=ok: 1 active task(s)
close_rc=1
close_stderr_last=AttributeError: 'int' object has no attribute 'get'
```

Observed versus expected: a top-level array emits a Python traceback. A history
list containing a number passes validation, after which close emits another
traceback. Both should produce bounded `PROBLEM:` diagnostics and exit 1 without
a traceback.

Root-cause data flow:

- `read_json` correctly decodes any JSON value (`framework/baton:950-960`).
- `load_tasks_from` appends that value without requiring a mapping
  (`framework/baton:986-999`).
- `cmd_validate` immediately builds `known` with `task.get`, so a top-level list
  raises `AttributeError` (`framework/baton:3649-3657`). `main` does not catch
  `AttributeError` (`framework/baton:4050-4056`).
- For an object, `task_problems` checks only that `history` itself is a list; it
  never checks each entry (`framework/baton:3486-3508`).
- `orchestrator_close_brief` later assumes every entry is a mapping and calls
  `entry.get` (`framework/baton:2356-2370`). Similar assumptions occur in
  `latest_worker_exit`, stats, and decision rendering.

Affected siblings: `task list`, `status`, `stats`, dependency traversal,
review/decision rendering, and close can fail on non-object task values or
non-object history entries. Invalid history field types are caught, but invalid
list members and their required field types are not.

Minimal regression test: write `[]` as one task state and assert `validate`
returns one bounded problem with no traceback. Separately parameterize history
members `1`, `null`, `[]`, and strings; validation must reject all and close must
not be needed to discover them.

Robust fix direction: validate the top-level JSON shape at the load/validation
boundary and validate every history record as a mapping before any consumer
uses it. Validation should aggregate shape problems rather than invoking normal
lifecycle consumers on malformed objects. Other commands should still fail with
a concise domain error if called before validation.

### B3 — empty fenced report sections satisfy the nonblank gate

Severity: medium.

Disposition: fixed. `test_report_empty_fenced_core_sections_are_rejected` proves
empty backtick and tilde fences do not satisfy Changes or Verification and that a
rejected finish preserves its token for a corrected report. The verified root cause
was unchanged; opening and closing fence delimiters are no longer counted as body
content.

Violated invariant: SPEC lines 477–486 require nonblank Result, Changes, and
Verification bodies. Empty Markdown code fences in Changes and Verification
contain no body content or evidence, but are accepted as nonblank.

Exact reproduction report:

````text
# report

## Result
needs_review

## Changes
```
```

## Verification
~~~
~~~

## Decisions and risks
- none
````

(The two backtick lines above are literal fence delimiters; there is no line
between them.)

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py empty-fences; done
RUN=1
finish_rc=0
finish_stdout=T001-audit-task submitted needs_review
result_written=True
RUN=2
finish_rc=0
finish_stdout=T001-audit-task submitted needs_review
result_written=True
```

Observed versus expected: `task finish --status needs_review` writes a result.
It should reject both empty core sections and preserve the finish token for a
corrected report.

Root-cause data flow:

- `cmd_task_finish` calls `report_section_problems` before writing the result
  (`framework/baton:1813-1829`).
- On an opening fence, `report_section_problems` sets fence state but then falls
  through and appends that delimiter line to the current section
  (`framework/baton:871-901`). Closing delimiters are suppressed while in fence
  state.
- The body check is only `any(line.strip() for line in body)`
  (`framework/baton:903-910`), so the opening delimiter itself makes an otherwise
  empty section appear nonblank.

Affected siblings: both backtick and tilde fences, with any supported opening
length and indentation, in Changes or Verification. Result cannot exploit this
alone because its first nonblank line must equal the submitted status.

Minimal regression test: add the exact report above to the existing report-gate
finish fixture and assert rejection names both empty sections, no result exists,
and the same token can be reused after adding actual body text.

Robust fix direction: parse section content into Markdown-relevant content rather
than counting fence delimiters. At minimum, do not append opening/closing fence
syntax as body content and require a nonblank line inside a fenced block or a
nonblank ordinary line outside it.

### B4 — `memory add` can create malformed and unindexed memory

Severity: medium.

Disposition: fixed.
`test_memory_add_rejects_structural_values_and_show_requires_indexed_id` covers blank
and multiline summaries, body-injected entry headings, byte-for-byte preservation on
rejection, and an unindexed synthetic heading. The verified root cause was unchanged;
add validates the strict representable grammar before locking/writing, and show now
resolves the id through the strict index before matching its canonical heading.

Violated invariant: SPEC lines 623–640 define a strict, ordered memory index with
one line per id, and the CLI promises working add/index/show commands. A
successful `memory add` must not make its own output unreadable or create an id
that is absent from the index.

Exact reproduction inputs:

- Summary: `line one\nline two`; body: `body`.
- Separate sibling input: summary `valid summary`; body
  `real body\n### M999 [W] injected heading\nsynthetic body`.

Exact twice-run commands and results:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py memory-add; done
RUN=1
add_rc=0 add_stdout='added M001'
index_rc=1 index_stderr="error: memory index line 10 is malformed; expected '- M### [W|O|B] summary': 'line two'"
validate_rc=1
validate_stdout=PROBLEM: memory: memory index line 10 is malformed; expected '- M### [W|O|B] summary': 'line two'
RUN=2
add_rc=0 add_stdout='added M001'
index_rc=1 index_stderr="error: memory index line 10 is malformed; expected '- M### [W|O|B] summary': 'line two'"
validate_rc=1
validate_stdout=PROBLEM: memory: memory index line 10 is malformed; expected '- M### [W|O|B] summary': 'line two'
```

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_extra.py memory-heading; done
RUN=1
add_rc=0
show_M001_rc=0 contains_synthetic=False
show_M999_rc=0 stdout='### M999 [W] injected heading\nsynthetic body'
RUN=2
add_rc=0
show_M001_rc=0 contains_synthetic=False
show_M999_rc=0 stdout='### M999 [W] injected heading\nsynthetic body'
```

Observed versus expected: add reports success, then its multiline summary breaks
`memory index` and `validate`. A body heading truncates M001 and makes
`memory show M999` succeed even though M999 was never indexed. Add should reject
values that cannot be represented in the grammar, or escape/encode them without
changing logical structure.

Root-cause data flow:

- `cmd_memory_add` accepts `args.summary` and `args.body` verbatim and interpolates
  them into both the index line and entry Markdown (`framework/baton:3818-3839`).
- No validation is applied before the atomic write.
- `memory_index_entries` later requires each index line to fully match its strict
  regular expression (`framework/baton:3763-3793`), so a summary newline creates
  an invalid extra line.
- `cmd_memory_show` locates any `^### M...` heading and stops at the next one,
  without requiring the id to exist in the index (`framework/baton:3805-3815`).
  A body can therefore create a synthetic entry boundary.

Affected siblings: blank summaries, summaries with leading/trailing newlines,
and bodies containing any line beginning `### M`. Embedded `## Entries` text does
not alter the already selected partition during the same add, but can make later
human editing and parsing ambiguous.

Minimal regression tests: assert add rejects a blank or multiline summary
without changing `memory.md`; assert a body containing an entry-heading-shaped
line is either safely representable as body text or rejected; assert `memory
show` cannot return an id absent from the strict index.

Robust fix direction: define and enforce argument grammar before writing: summary
must be a nonblank single line compatible with the index; entry bodies must not
create structural entry headings unless an explicit escaping format is added.
Resolve `memory show` through the parsed index and exact canonical entry boundary,
not an unrestricted heading search.

### B5 — multiline titles inject task-spec sections

Severity: medium.

Disposition: fixed. `test_task_create_rejects_multiline_title_section_injection`
reproduces Objective injection, verifies no task artifacts are created, and retains a
valid Unicode title path. The verified root cause was unchanged; task titles are now
required to be nonblank, single-line, control-free text before id allocation.

Violated invariant: task creation should produce one canonical task template,
and capsule compilation should derive Objective from the generated task spec's
Objective section. A title is task metadata, not an alternate source of task
sections.

Exact reproduction title:

```text
normal title

## Objective
Injected objective from title
```

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py title-injection; done
RUN=1
create_rc=0
objective_heading_count=2
compiled_objective='Injected objective from title'
RUN=2
create_rc=0
objective_heading_count=2
compiled_objective='Injected objective from title'
```

Observed versus expected: creation succeeds, the generated spec has two
`## Objective` headings, and the capsule section parser chooses the title-injected
one. Creation should reject a structurally unsafe title or render it as inert
single-line metadata, leaving exactly one generated Objective placeholder.

Root-cause data flow:

- `cmd_task_create` checks only `args.title.strip()`
  (`framework/baton:1385-1389`).
- It stores the raw title and interpolates it into `TASK_MD_TEMPLATE`'s first
  heading (`framework/baton:1157-1178`, `1417-1434`).
- `task_spec_sections` scans every top-level `##` heading and uses `setdefault`,
  preserving the first occurrence (`framework/baton:1191-1198`). The injected
  Objective precedes the template Objective.
- `context_capsule_components` consumes that first section
  (`framework/baton:1242-1262`), so title text can change launch criteria.

Affected siblings: injected Acceptance criteria, Context, Not allowed,
Verification, Decisions, or Review feedback headings; raw newlines/control text
also affects creation/list/status output and the task line in the launch capsule.
`task return --reason` and `task decide --answer` also interpolate caller text
into Markdown, but this audit did not classify those trusted free-form fields as
defects because the SPEC does not require them to be single-line.

Minimal regression test: create with the exact title above and assert a concise
rejection with no state/spec files created. Also retain a valid Unicode single-line
title test.

Robust fix direction: validate titles as nonblank, single-line, control-free text
before id allocation and persistence, or use one canonical escaping scheme for
all Markdown and terminal renderings. Do not silently flatten a title unless the
stored JSON and displayed title use the same canonical value.

### B6 — punctuation bypasses tier display flag rejection

Severity: low.

Disposition: fixed. `test_tier_display_rejects_command_flags_after_punctuation`
covers semicolon, parenthesis, and whitespace boundaries while retaining ordinary
hyphenated prose. The verified root cause was unchanged; the flag boundary now treats
any preceding non-alphanumeric character as a token boundary.

Violated invariant: SPEC lines 606–611 require every display value to contain no
command flags. The validator rejects a flag at string start or after whitespace,
but accepts the same flag after shell punctuation.

Exact TOML input:

```text
[commands]
worker = "/usr/bin/true {prompt_file}"
[limits]
max_parallel = 1
worker_timeout_minutes = 1
capsule_max_chars = 4000
[tiers.audit]
[tiers.audit.display]
model = "label;--provider synthetic"
```

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py tier-flag; done
RUN=1
validate_rc=0 validate_stdout='ok: 0 active task(s)'
tiers_rc=0
flag_rendered=True
RUN=2
validate_rc=0 validate_stdout='ok: 0 active task(s)'
tiers_rc=0
flag_rendered=True
```

Observed versus expected: `validate` accepts the configuration and `tiers`
renders `--provider synthetic`. The display value should be rejected under the
explicit no-command-flags rule.

Root-cause data flow:

- `validated_display_metadata` applies
  `re.search(r"(?:^|\s)--?[A-Za-z0-9]", item)`
  (`framework/baton:298-325`).
- `;` is neither start-of-string nor whitespace, so the flag is missed.
- The value then flows through `worker_display_label`, `resolved_task_label`,
  JSON display enrichment, launch prompt metadata, `status`, and `tiers`
  (`framework/baton:328-336`, `444-461`, `2767-2808`, `3306-3334`).

Affected siblings: flags following `;`, `(`, `)`, `,`, `/`, and other
non-whitespace punctuation in all five display fields. This is display-only and
does not change `worker_argv`, which limits severity.

Minimal regression test: parameterize `x;--flag`, `(--flag)`, and the currently
rejected `x --flag` across one display field; all must fail `validate`, while
ordinary hyphenated prose remains valid.

Robust fix direction: define a token boundary suitable for human labels rather
than shell whitespace alone, or reject flag-shaped `--name` substrings wherever
they occur unless explicitly escaped. Keep the current control, length, and
redaction checks.

### B7 — post-finish report drift bypasses the report gate

Severity: medium.

Disposition: fixed. `test_finalization_rejects_report_drift_after_finish` covers the
real worker post-finish lifecycle, and
`test_review_and_accept_reject_structurally_invalid_report_drift` covers drift before
review and after a review brief, including token preservation and a corrected fresh
brief. The verified root cause was unchanged; one report-gate validator is now reused
at finish, finalization, review briefing, and acceptance while the existing evidence
manifest and one-use token checks remain in force.

Violated invariant: with `report_requires_sections = true`, SPEC lines 477–487
require a needs-review report to have the exact sections and nonblank core
bodies. A task whose report is replaced after finish can reach `needs_review`,
receive a review token, and be accepted as `done` with only `# malformed after
finish` as its report.

Exact reproduction input and lifecycle:

1. A real stub worker writes a valid structured report.
2. It obtains a report brief token and successfully runs `task finish --status
   needs_review --brief TOKEN` with no changed paths.
3. Before exiting, it overwrites `attempt-1.report.md` with exactly
   `# malformed after finish\n` and exits zero.
4. The orchestrator runs a review brief and accepts with its token.

Exact twice-run command and result:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py report-drift; done
RUN=1
run_rc=0 post_run_status=needs_review
review_rc=0
accept_rc=0 final_status=done
RUN=2
run_rc=0 post_run_status=needs_review
review_rc=0
accept_rc=0 final_status=done
```

Observed versus expected: the malformed report survives finalization and review
and the task becomes done. At minimum, finalization should reject a needs-review
submission whose final report no longer satisfies the enabled gate. Review or
accept should also refuse later structural drift, while preserving the existing
hash-manifest behavior for otherwise valid edits.

Root-cause data flow:

- `cmd_task_finish` validates report structure, writes the result, and deliberately
  leaves the task running (`framework/baton:1771-1846`; lifecycle requirement at
  SPEC lines 108–110).
- The worker remains able to change the report until it exits.
- `finalize_task` re-reads and validates the result but checks the report only
  with `report_is_ready`, which tests regular/nonempty, not its sections
  (`framework/baton:2955-3009`, especially `2998-3000`).
- `build_review_evidence_manifest` hashes report/result/diff and validates changed
  paths but not report structure (`framework/baton:793-848`).
- `orchestrator_review_brief` issues a token for those hashes
  (`framework/baton:2194-2234`), and `cmd_task_accept` checks manifest equality
  but not report semantics (`framework/baton:1649-1695`). A stable malformed
  report therefore satisfies freshness while violating the report gate.

Affected siblings: a report changed after worker finalization but before the
review brief behaves the same way; replacing a valid report with any nonempty
regular UTF-8 or non-UTF-8 file reaches review hashing (non-UTF-8 content is
hashable). Normal evidence changes *after* review are correctly rejected by the
manifest, so this is a semantic revalidation gap rather than a hash-drift gap.

Minimal regression test: add the exact real-worker lifecycle above and assert
final status `failed` with a stable reason such as `invalid_review_report`.
Separately mutate the report after finalization and assert review/accept refuses
it without consuming a valid token until the report is corrected and freshly
briefed.

Robust fix direction: factor the enabled report gate into one reusable validator
and apply it to the final report at finalization. Reapply it before issuing a
review token (and/or atomically during accept under the task lock) so later drift
cannot bless semantically invalid evidence. Preserve one-use tokens and existing
manifest equality; hashing alone is not a substitute for shape validation.

## Categories checked with no additional confirmed defect

### Unicode filenames

A real worker created and declared `café/東京-😀.md` under scope `café/**`.
Both runs reached `needs_review` with identical exact declared and observed
lists:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_unicode_check2.py; done
RUN=1
run_rc=0 status=needs_review
declared=['café/東京-😀.md']
observed=['café/東京-😀.md']
RUN=2
run_rc=0 status=needs_review
declared=['café/東京-😀.md']
observed=['café/東京-😀.md']
```

No defect was found for ordinary non-ASCII filenames. B1 is limited to legal
literal names that collide with scope syntax or trimming.

### Scope matching and scheduling overlap

A bounded implementation comparison generated one- and two-segment patterns
from literals, Unicode segments, dotfiles, `*`, `?`, `**`, `a*`, and `b?`, then
enumerated paths to test every pair that `scopes_overlap` classified as safe to
co-schedule. Both runs checked 2,250 non-overlap pairs with no shared matching
path:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_checks.py scope; done
RUN=1
nonoverlap_pairs_checked=2250 counterexamples=[]
RUN=2
nonoverlap_pairs_checked=2250 counterexamples=[]
```

Exact-directory prefix behavior, case folding, dotfiles, and `**` recursion were
also covered by the baseline. No false-safe overlap defect was found.

### Concurrent lifecycle changes, interruptions, worker exits, and timeouts

The following exact targeted command was run twice:

```text
python3 tests/test_baton.py \
  BatonTests.test_concurrent_run_claims_task_once \
  BatonTests.test_separate_run_processes_serialize_snapshot_windows \
  BatonTests.test_stale_finalizer_cannot_overwrite_a_new_lease \
  BatonTests.test_interrupt_stops_workers_without_waiting_for_timeout \
  BatonTests.test_sigterm_stops_parallel_groups_with_one_shared_grace_period \
  BatonTests.test_timeout_kills_worker_process_group \
  BatonTests.test_timeout_overrides_valid_submission
```

Each run reported `Ran 7 tests` and `OK` (14.579s and 14.422s). Duplicate claims,
execution-lock snapshot serialization, stale leases, SIGINT/SIGTERM cleanup,
shared grace timing, descendant process-group timeout, and timeout precedence all
behaved as specified. No additional defect was found.

### Review-evidence drift

B7 covers semantic report drift. The existing hash-manifest drift paths were
separately run twice with
`test_review_evidence_mutations_reject_without_consuming_token` and
`test_review_brief_warns_on_memory_drift_and_shows_launch_capsule`; both passed.
Report/result/diff/capsule mutations after a review brief were rejected without
token consumption, and launch-capsule display on memory drift was correct. No
hash-manifest mismatch defect was found.

### Archive preflight, rollback, and interruption

A deterministic injected failure on the second `shutil.move` was run twice. In
both runs the error propagated, both task files were restored, and archive was
empty:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_probe.py archive-rollback; done
RUN=1
outcome='synthetic move failure'
active=['T001-audit-task.json', 'T001-audit-task.md'] archived=[]
RUN=2
outcome='synthetic move failure'
active=['T001-audit-task.json', 'T001-audit-task.md'] archived=[]
```

The destination-preflight and SIGTERM-deferral tests were also run twice and
passed. No reproducible archive rollback or interruption defect was found.

### Hook input

Empty input, malformed JSON, compact SessionStart JSON, and a JSON array for
UserPromptSubmit were exercised twice:

```text
for i in 1 2; do echo RUN=$i; python3 /tmp/baton_audit_checks.py hooks; done
RUN=1
empty_rc=0 stderr_empty=True compact_notice=False
malformed_rc=0 stderr_empty=True compact_notice=False
compact_rc=0 stderr_empty=True compact_notice=True
user_array_rc=0 event=UserPromptSubmit
RUN=2
empty_rc=0 stderr_empty=True compact_notice=False
malformed_rc=0 stderr_empty=True compact_notice=False
compact_rc=0 stderr_empty=True compact_notice=True
user_array_rc=0 event=UserPromptSubmit
```

The output cap edge cases and missing/broken-runtime fail-open behavior also
passed in the baseline. No hook-input defect was found.

### TOML limits and tier routing beyond B6

Global and per-tier `nan`/infinite/non-number timeouts, booleans in numeric
fields, unknown tiers, reserved `default`, limits-only inheritance, per-tier
timeouts/capsule budgets, display controls, length bounds, redaction, and routing
visibility were inspected. The nonfinite timeout test was rerun twice and passed.
No routing or limit defect was found. B6 is the only confirmed tier-metadata gap.

### Log-tail handling

No worker log content was included in this audit. Synthetic canary assignments
for common credential-label shapes were passed directly to `sanitize_log_text`;
all were replaced with `[redacted]`. Existing ANSI/OSC, C0/C1, byte-window,
line-count, line-length, and opt-in tests passed. No additional sanitizer defect
was confirmed.

### Activation measurement

Exact command sequence:

```text
python3 tools/measure_context.py --json > /tmp/baton-measure-1.json
python3 tools/measure_context.py --json > /tmp/baton-measure-2.json
cmp /tmp/baton-measure-1.json /tmp/baton-measure-2.json
python3 tests/test_context_footprint.py
```

Result: the JSON files were byte-identical; the focused suite ran 4 tests and
reported `OK`. Both measurements reported 15,124 Unicode characters, 15,126
UTF-8 bytes, 334 lines, SHA-256
`f3ca7044b52318effe0e371048e12b4fff4927be928a9d1b11827fefe80d0616`,
and provider-recorded differentials of 3,426 and 5,323 tokens. No stale-evidence,
boundary, determinism, or activation-count defect was found.

## Risks and deliberate tradeoffs not classified as defects

- Baton workers share one operating-system identity and can directly edit runtime
  result/token files. The SPEC expressly says role checks are not a security
  sandbox. Direct same-user bypasses were therefore not labeled defects without
  a separate cooperative CLI path; B7 is classified because it occurs through a
  fully valid documented `task finish` lifecycle.
- Unicode case folding is implemented, but Unicode normalization (NFC/NFD) is not.
  The documentation promises case folding, not canonical-equivalence matching,
  and no violated invariant was demonstrated.
- Tier names themselves are not bounded or control-filtered. Display metadata is
  explicitly bounded and safe, while the SPEC currently requires tier names only
  to be nonblank. This is an output-hardening risk, not a confirmed contract
  violation.
- Review evidence can theoretically change in the very small interval between a
  final manifest read and state write by an unrelated same-user process. The
  deterministic sequential drift gate worked, and the same-user/non-sandbox
  limitation is explicit; no reproducible cooperative lifecycle failure was
  established beyond B7.
- Archive rollback suppresses a secondary error while attempting restoration.
  The injected primary-move failure rolled back completely. Filesystem failure of
  both the forward move and rollback remains an operational risk, not a
  reproduced defect.
- Hook stdin is read with a 64-KiB character bound. Normal host payloads, malformed
  input, and compact-source input behaved correctly; no documented requirement
  for larger hook payloads was found.

## Regression priority

Recommended implementation order for the separate fix task:

1. B7, because a default-on review gate can be absent from final accepted
   evidence.
2. B5 and B4, because successful public commands can alter canonical Markdown
   structure.
3. B1, because valid repository filenames can make successful worker submission
   impossible.
4. B2, to make the diagnostic command safe on malformed state.
5. B3, to close an evidence-quality gate edge case.
6. B6, as bounded display hardening.

Each fix should retain the currently passing concurrency, timeout, archive,
Unicode, hook, activation, and review-manifest checks listed above.

## Final verification

After writing this audit, the required command was rerun:

```text
python3 tests/test_baton.py
Ran 106 tests in 125.594s
OK
```

`git diff --check -- docs/bug-audit.md` passed. The task-scoped status is exactly:

```text
?? docs/bug-audit.md
```

The repository is a shared worktree and already contained tracked and untracked
changes from other tasks before this audit began (including the Baton rename,
manual/SPEC/test edits, and context-footprint artifacts). Consequently the
literal repository-wide `git diff --name-only` is not limited to this task and,
because this new report is untracked, does not list it. Comparing the initial and
final status shows this task added only `docs/bug-audit.md`; no pre-existing path
was modified, staged, reverted, or cleaned by this audit.
