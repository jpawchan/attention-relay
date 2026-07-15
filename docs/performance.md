# Baton performance

This document records the profiling and benchmarks for T006. The benchmark is intentionally standard-library-only and creates disposable Git repositories; it does not read or modify the active `.baton` runtime.

## Environment

Measurements were taken on 2026-07-13 on:

- MacBook Air (MacBookAir10,1), Apple M1, 8 cores (4 performance and 4 efficiency), 8 GB RAM
- macOS 26.5 (build 25F71), arm64
- Python 3.11.1
- Apple Git 2.50.1 (Apple Git-155)
- no new runtime or benchmark dependency

The machine was otherwise idle for the final paired runs. The pre-change source and tests were copied before the implementation edits into a disposable tree. The same commands were then run from that tree and the post-change tree. Fixture creation is outside timed regions.

## Workloads and commands

`tools/benchmark_performance.py` builds one fixture with 500 active tasks, 500 archived tasks and phase receipts, six referenced memory entries, 300 tracked files, 50 modified files, and 50 untracked files. It measures each command in a fresh child process with `perf_counter`, `wait4` CPU time, and per-child `ru_maxrss`. On macOS, `ru_maxrss` is already bytes.

The following command was run unchanged from the root of each source tree. There was one warm-up and seven recorded samples for each workload:

```console
python3 tools/benchmark_performance.py --repo . --source framework/baton \
  --samples 7 --skip-suite --output /tmp/baton-performance.json
```

The benchmark covers:

- `framework/baton --help` (startup/parser/help)
- disposable `baton init`
- installed `orchestrator brief --phase start`
- `status` and `validate` over 500 active tasks
- capsule compilation for a task referencing six memory entries
- `stats` over 500 active plus 500 archived tasks and 1,000 receipt files
- two exact Git snapshots, changed-path discovery, and a binary diff over the 300-file fixture

The full suite was measured separately without a warm-up because a run takes about 2.4 minutes. The command executed by the sampler was unchanged in each source tree:

```console
python3 tests/test_baton.py
```

The sampler invoked that command three times through the benchmark's `measured_rss` function and summarized it with the same `summarize` function. This keeps wall, CPU, and peak-RSS collection identical to the shorter workloads.

For a single command that reproduces every workload, including three suite samples, run:

```console
python3 tools/benchmark_performance.py --repo . --source framework/baton \
  --samples 7 --suite-samples 3 --output /tmp/baton-performance.json
```

## Results

Wall values are medians. `sd` is population standard deviation across wall samples. CPU and RSS are medians. Negative wall deltas are faster; negative RSS deltas use less peak memory. The first eight rows have 7 samples; the suite has 3.

| Workload | Wall before | Wall after | Wall delta | Before/after sd | CPU before | CPU after | Peak RSS before | Peak RSS after | RSS delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| startup/help | 55.504 ms | 57.131 ms | +2.9% | 0.290 / 4.962 ms | 53.107 ms | 54.593 ms | 28.72 MiB | 30.25 MiB | +1,568 KiB |
| init | 99.545 ms | 101.993 ms | +2.5% | 1.082 / 0.992 ms | 92.360 ms | 94.451 ms | 29.45 MiB | 30.36 MiB | +928 KiB |
| start brief | 110.800 ms | 97.634 ms | -11.9% | 0.660 / 0.601 ms | 108.441 ms | 95.130 ms | 31.03 MiB | 31.61 MiB | +592 KiB |
| large status | 140.097 ms | 99.461 ms | -29.0% | 0.612 / 0.685 ms | 137.691 ms | 96.952 ms | 32.06 MiB | 31.58 MiB | -496 KiB |
| large validate | 209.473 ms | 184.617 ms | -11.9% | 0.746 / 0.674 ms | 202.139 ms | 176.580 ms | 32.81 MiB | 33.36 MiB | +560 KiB |
| capsule + 6 memory refs | 95.172 ms | 81.463 ms | -14.4% | 0.533 / 0.748 ms | 92.750 ms | 79.079 ms | 29.92 MiB | 30.45 MiB | +544 KiB |
| archive stats | 178.237 ms | 165.528 ms | -7.1% | 1.260 / 0.621 ms | 175.853 ms | 163.213 ms | 31.55 MiB | 32.16 MiB | +624 KiB |
| snapshot + diff | 221.990 ms | 224.474 ms | +1.1% | 5.400 / 0.932 ms | 205.096 ms | 207.204 ms | 30.61 MiB | 31.92 MiB | +1,344 KiB |
| full test suite | 142.752 s | 146.399 s | +2.6% | 0.356 / 1.444 s | 84.497 s | 86.395 s | 89.42 MiB | 92.95 MiB | +3,616 KiB |

The measured wall-time gains claimed here are start brief (11.9%), large status (29.0%), large validate (11.9%), capsule preview (14.4%), and archive stats (7.1%). Their before/after ranges did not overlap. The RSS medians and maxima in the table are raw process-level observations, not a demonstrated memory improvement. Independent peak-RSS reruns were inconclusive and noisy, so no peak-RSS effect size is claimed. Source inspection and `test_status_reuses_loaded_tasks_when_rendering_next_actions` verify only the implementation fact that status no longer builds and retains a second parsed task list.

No gain is claimed for startup/help, init, snapshot/diff, or the full suite. Their deltas are small relative to process-level and suite-level variation or represent a changed suite workload. In particular, the post-change suite includes two new focused tests, so its 2.6% increase is reported rather than interpreted as a production-path regression. RSS moved in both directions between process runs; none of those changes are attributed to the implementation.

## Scheduler and task-create hot paths

T004 added a focused `--hot-paths-only` mode. It imports the runtime once, uses one warm-up and seven recorded `perf_counter` samples, and excludes interpreter startup and disposable-fixture construction from the timed regions. The scheduler workload gives every queued task a distinct `src/TNNNN-scheduler/**` scope and sets `max_parallel` to the task count. The state fixture contains 500 active and 500 archived tasks. The task-create workload instruments `load_tasks_from` while creating a real task in a disposable copy and validating an archived dependency.

These measurements were taken on 2026-07-15 under WSL2 (Linux 6.18.33.2, x86_64), Python 3.11.4, and Git 2.50.1. Because this host's default `python3` is older than 3.11 and the runtime uses an `env python3` shebang, the exact focused command was:

```console
tmp=$(mktemp -d)
ln -s "$(command -v python3.11)" "$tmp/python3"
PATH="$tmp:$PATH" python3.11 tools/benchmark_performance.py \
  --hot-paths-only --samples 7 --output /tmp/baton-hot-paths.json
rm -rf "$tmp"
```

The before scheduler values are the captured pre-T004 baseline on this host. The speedup ratios are approximate because those baseline values were rounded. The after values are medians from the command above.

| Distinct queued tasks | Before | After | Approximate speedup |
| ---: | ---: | ---: | ---: |
| 1,000 | 0.71 s | 0.003941 s | 180x |
| 2,000 | 2.85 s | 0.008240 s | 346x |
| 4,000 | 10.72 s | 0.016666 s | 643x |

The active+archive load itself remained comparable: the captured baseline for one 1,000-task pass was about 0.058 s, and the post-change median was 0.060821 s. The optimization removes redundant passes rather than claiming faster JSON parsing. Before T004, task creation made three complete passes (six directory loads), measured at about 0.177 s for state loading alone. After T004, instrumentation records exactly one active and one archive directory load per creation; the complete focused task-create timed region, including validation, ID allocation, locking, and writes, had a 0.071383 s median. Those last two timings have different boundaries, so they demonstrate the eliminated I/O and its practical effect rather than a precise end-to-end percentage.

## Profiling evidence

A 500-active/500-archived fixture was generated with `prepare_fixture`. The following commands were run against the installed baseline and post-change scripts:

```console
BATON_DIR=/tmp/baton-profile/project/.baton \
  python3 -m cProfile -o /tmp/baton-status.prof \
  /tmp/baton-profile/project/.baton/baton status >/dev/null
BATON_DIR=/tmp/baton-profile/project/.baton \
  python3 -m cProfile -o /tmp/baton-validate.prof \
  /tmp/baton-profile/project/.baton/baton validate >/dev/null
BATON_DIR=/tmp/baton-profile/project/.baton \
  python3 -m cProfile -o /tmp/baton-stats.prof \
  /tmp/baton-profile/project/.baton/baton stats >/dev/null
python3 -c 'import pstats; pstats.Stats("/tmp/baton-status.prof").strip_dirs().sort_stats("cumulative").print_stats(30)'
```

| Profile | Before | After | Call-count change |
| --- | ---: | ---: | ---: |
| status | 148.025 ms | 75.518 ms (-49.0%) | 275,128 to 101,760 (-63.0%) |
| validate | 242.663 ms | 194.508 ms (-19.8%) | 424,448 to 271,094 (-36.1%) |
| stats | 174.191 ms | 156.980 ms (-9.9%) | 268,985 to 228,401 (-15.1%) |

The profiles identified three concrete bottlenecks:

1. Every stateful command walked every managed runtime entry and then called path helpers that repeated `lstat`. `runtime_paths_are_safe` took about 40.5-40.8 ms in all three baseline profiles. A `scandir` traversal that retains the complete symlink gate and traversal order reduced it to 20.7-21.8 ms.
2. `status` parsed all 500 task JSON files twice: once for status and once for next actions. The two `load_tasks_from` calls cost 36.1 ms and retained both task sets at peak. Passing the command's already-loaded snapshot to next-action rendering reduced this to one 19.8 ms load.
3. `status` and `validate` revalidated and `shlex`-parsed the identical worker command for every task. Baseline cumulative `configured_tier` time was 37.1 ms for status (500 calls) and 39.1 ms for validate (501 calls). A command-local cache now validates each distinct tier once and also preserves cached validation errors. It is not persistent and cannot serve stale config.

The validate profile also showed four Git subprocesses at about 42-49 ms cumulative. Stats was dominated by the required 2,000 JSON reads (task state plus receipts). Those measurements informed the rejected changes below.

## Production-safety constraints

The optimized runtime traversal still visits every managed file and directory, rejects top-level and nested symlinks, and preserves directory-before-file and depth-first error ordering. It uses `lstat`/`DirEntry` metadata instead of repeated path probes; it does not skip the security gate.

The tier result cache exists only inside one command invocation. Config is still read on every invocation, all configured limits and display metadata are validated, and invalid tiers still produce task-specific errors. No filesystem cache or mtime heuristic was introduced.

Status now renders counts, task rows, and next actions from one consistent freshly loaded snapshot. Standalone next-action callers still load current state. No lock was added or widened. Atomic writes, lock ordering, capsule freshness, snapshots, Git scope enforcement, and error gates were not changed.

## Rejected optimizations

- Persistent TOML, task, memory, or capsule caches: rejected because invalidation would weaken freshness and review/security gates. Startup parsing was not a measured bottleneck.
- Skipping or sampling the managed-tree symlink scan: rejected even though it would be faster, because it weakens the runtime path security invariant.
- Combining or removing Git snapshot/diff subprocesses: rejected because snapshot exactness, unborn-HEAD behavior, staged removals, submodule checks, and current error behavior depend on the existing commands. Snapshot/diff showed no stable gain opportunity.
- Replacing JSON/TOML with a third-party parser: rejected because Baton is standard-library-only and file/syscall costs, not parser throughput alone, dominated the measured paths.
- Parallel task/receipt reads: rejected because the files are small, thread scheduling would add overhead, and parallel failures could change deterministic first-error behavior.
- Caching capsule memory maps or pre-rendered capsules: rejected because capsule compilation itself was small in `cProfile`; the measured capsule improvement came from the required runtime scan, not capsule rendering.
- Removing stats sorts or materializing less receipt evidence: rejected because the bounded deterministic output and exact coverage denominator require the data, and the profiles showed required file reads as the dominant remaining work.
