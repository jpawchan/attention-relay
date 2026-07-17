#!/usr/bin/env python3
"""Repeatable end-to-end performance benchmarks for Baton (standard library only)."""

import argparse
import ast
import hashlib
import json
import os
import platform
import runpy
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

TASKS = 500
ARCHIVED = 500
BATON_ENVIRONMENT_KEYS = (
    "BATON_TASK_ID", "BATON_ATTEMPT", "BATON_LEASE", "BATON_DIR", "BATON_ROOT",
)
RECEIPT = {
    "task_id": "",
    "attempt": 1,
    "lease": "benchmark",
    "capsule_digest": "sha256:" + "a" * 64,
    "phases": {
        phase: {
            "first_at": "2026-01-01T00:00:00Z",
            "last_at": "2026-01-01T00:00:00Z",
            "count": 1,
        }
        for phase in ("edit", "verify", "report")
    },
}
SPEC = """# {id}: benchmark task

## Objective
Process benchmark task {id} deterministically.

## Acceptance criteria
- Preserve benchmark behavior.

## Context
Use M001 M002 M003 M004 M005 M006.

## Not allowed
- No semantic changes.

## Verification
- Run the benchmark.

## Decisions

## Review feedback
"""


def benchmark_environment(overrides=None):
    environment = os.environ.copy()
    for key in BATON_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    if overrides:
        environment.update({key: str(value) for key, value in overrides.items()})
    return environment


def run_checked(argv, cwd, env=None):
    result = subprocess.run(
        [str(item) for item in argv], cwd=cwd,
        env=benchmark_environment(env),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        raise RuntimeError("{} failed: {}".format(" ".join(map(str, argv)), result.stderr))


def suite_environment(base):
    """Give only the copied suite an explicit Python matching this process."""
    environment = os.environ.copy()
    for key in BATON_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    shim_dir = base / "suite-python"
    shim_dir.mkdir()
    (shim_dir / "python3").symlink_to(sys.executable)
    environment["PATH"] = str(shim_dir) + os.pathsep + environment.get("PATH", "")
    return environment


def git_project(path):
    path.mkdir()
    run_checked(("git", "init", "-q"), path)
    run_checked(("git", "config", "user.name", "Baton Benchmark"), path)
    run_checked(("git", "config", "user.email", "benchmark@example.invalid"), path)
    (path / "seed.txt").write_text("seed\n")
    run_checked(("git", "add", "seed.txt"), path)
    run_checked(("git", "commit", "-qm", "seed"), path)


def task_value(task_id, status="queued", history=None):
    return {
        "id": task_id,
        "title": "benchmark task " + task_id,
        "status": status,
        "attempt": 1,
        "tier": "benchmark",
        "scope": ["src/{}/**".format(task_id)],
        "depends_on": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "history": history or [],
    }


def finalized_evidence(task_id):
    """Build deterministic, nontrivial review evidence for one archived task."""
    changed_path = "src/{}/benchmark-output.txt".format(task_id)
    lease = "benchmark-{}-attempt-1".format(task_id)
    note = "benchmark evidence ready"
    result = {
        "status": "needs_review",
        "note": note,
        "at": "2026-01-01T00:00:01Z",
        "lease": lease,
        "changed_paths": [changed_path],
    }
    result_text = json.dumps(result, sort_keys=True) + "\n"
    report_lines = [
        "# {} finalized benchmark report".format(task_id),
        "",
        "## Result",
        "needs_review",
        "",
        "## Changes",
        "- Generated deterministic review evidence for `{}`.".format(changed_path),
        "- Preserved lifecycle, attempt, lease, and changed-path attribution.",
        "",
        "## Verification",
    ]
    report_lines.extend(
        "- Evidence check {:02d}: result, report, and diff metadata agree for {}."
        .format(index, task_id)
        for index in range(1, 25)
    )
    report_lines.extend((
        "",
        "## Decisions and risks",
        "- The fixture is synthetic, deterministic, and requires no network access.",
        "",
    ))
    diff_lines = [
        "diff --git a/{0} b/{0}".format(changed_path),
        "new file mode 100644",
        "index 0000000..{:07x}".format(int(task_id[1:5])),
        "--- /dev/null",
        "+++ b/{}".format(changed_path),
        "@@ -0,0 +1,48 @@",
    ]
    diff_lines.extend(
        "+{} benchmark review payload line {:02d}: ".format(task_id, index)
        + "deterministic finalized evidence exercises hashing and artifact reads"
        for index in range(1, 49)
    )
    return {
        "changed_path": changed_path,
        "lease": lease,
        "note": note,
        "result": result_text,
        "result_digest": "sha256:" + hashlib.sha256(result_text.encode()).hexdigest(),
        "report": "\n".join(report_lines),
        "diff": "\n".join(diff_lines) + "\n",
    }


def prepare_fixture(source, base):
    project = base / "project"
    git_project(project)
    run_checked((source, "init", project), project)
    runtime = project / ".baton"
    with (runtime / "config.toml").open("a", encoding="utf-8") as config:
        config.write(
            '\n[tiers.benchmark]\ncommand = "/usr/bin/true {prompt_file}"\n'
        )
    memory_lines = [
        "- M{:03d} [W] Benchmark memory summary {}".format(index, index)
        for index in range(1, 7)
    ]
    entries = [
        "### M{:03d} [W] Benchmark memory summary {}\nBody {}".format(index, index, index)
        for index in range(1, 7)
    ]
    (runtime / "memory.md").write_text(
        "# Memory\n\n## Index\n" + "\n".join(memory_lines)
        + "\n\n## Entries\n\n" + "\n\n".join(entries) + "\n"
    )
    tasks = runtime / "tasks"
    archive = runtime / "archive"
    work = runtime / "work"
    for number in range(1, TASKS + 1):
        task_id = "T{:04d}-benchmark".format(number)
        launched = {
            "at": "2026-01-01T00:00:00Z", "event": "launched",
            "attempt": 1, "capsule_chars": 700 + number % 200,
        }
        (tasks / (task_id + ".json")).write_text(
            json.dumps(task_value(task_id, history=[launched])) + "\n"
        )
        (tasks / (task_id + ".md")).write_text(SPEC.format(id=task_id))
        receipt_dir = work / task_id
        receipt_dir.mkdir()
        receipt = dict(RECEIPT, task_id=task_id)
        (receipt_dir / "attempt-1.briefs.json").write_text(json.dumps(receipt) + "\n")
    for number in range(TASKS + 1, TASKS + ARCHIVED + 1):
        task_id = "T{:04d}-benchmark".format(number)
        evidence = finalized_evidence(task_id)
        history = [
            {
                "at": "2026-01-01T00:00:00Z", "event": "launched",
                "attempt": 1, "capsule_chars": 700 + number % 200,
                "lease": evidence["lease"],
            },
            {
                "at": "2026-01-01T00:00:02Z", "event": "worker_exited",
                "attempt": 1, "status": "needs_review", "exit_code": 0,
                "note": evidence["note"],
                "declared_paths": [evidence["changed_path"]],
                "observed_paths": [evidence["changed_path"]],
                "result_digest": evidence["result_digest"],
            },
            {
                "at": "2026-01-01T00:00:03Z", "event": "accepted",
                "note": "benchmark fixture",
            },
        ]
        (archive / (task_id + ".json")).write_text(
            json.dumps(task_value(task_id, status="done", history=history)) + "\n"
        )
        receipt_dir = archive / (task_id + ".work")
        receipt_dir.mkdir()
        receipt = dict(RECEIPT, task_id=task_id)
        (receipt_dir / "attempt-1.briefs.json").write_text(json.dumps(receipt) + "\n")
        (receipt_dir / "attempt-1.result.json").write_text(evidence["result"])
        (receipt_dir / "attempt-1.report.md").write_text(evidence["report"])
        (receipt_dir / "attempt-1.diff").write_text(evidence["diff"])
    tracked = project / "tracked"
    tracked.mkdir()
    for number in range(300):
        (tracked / "file-{:04d}.txt".format(number)).write_text(("line {}\n".format(number)) * 20)
    run_checked(("git", "add", "tracked"), project)
    run_checked(("git", "commit", "-qm", "benchmark files"), project)
    for number in range(50):
        (tracked / "file-{:04d}.txt".format(number)).write_text("changed {}\n".format(number))
    for number in range(50):
        (tracked / "new-{:04d}.txt".format(number)).write_text("new {}\n".format(number))
    return project


def measured_rss(argv, cwd, env=None):
    script = (
        "import os,resource,sys,time\n"
        "started=time.perf_counter()\n"
        "pid=os.fork()\n"
        "if pid==0:\n"
        " os.chdir(sys.argv[1])\n"
        " null=os.open(os.devnull,os.O_RDWR)\n"
        " os.dup2(null,1); os.dup2(null,2); os.close(null)\n"
        " os.execvpe(sys.argv[2],sys.argv[2:],os.environ)\n"
        "_,status,usage=os.wait4(pid,0)\n"
        "print(repr((time.perf_counter()-started,usage.ru_utime+usage.ru_stime,usage.ru_maxrss)))\n"
        "raise SystemExit(os.waitstatus_to_exitcode(status))\n"
    )
    merged = benchmark_environment(env)
    result = subprocess.run(
        [sys.executable, "-c", script, str(cwd), *map(str, argv)],
        env=merged, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        raise RuntimeError("{} failed: {}".format(" ".join(map(str, argv)), result.stderr))
    wall, cpu, rss = ast.literal_eval(result.stdout.strip())
    if sys.platform != "darwin":
        rss *= 1024
    return wall, cpu, rss


def summarize(samples):
    walls = [item[0] for item in samples]
    cpus = [item[1] for item in samples]
    rss = [item[2] for item in samples]
    return {
        "samples": len(samples),
        "wall_median_s": statistics.median(walls),
        "wall_min_s": min(walls),
        "wall_max_s": max(walls),
        "wall_pstdev_s": statistics.pstdev(walls),
        "cpu_median_s": statistics.median(cpus),
        "peak_rss_median_bytes": int(statistics.median(rss)),
        "peak_rss_max_bytes": int(max(rss)),
    }


def benchmark(name, make_command, samples, warmups=1):
    for _ in range(warmups):
        argv, cwd, env = make_command()
        measured_rss(argv, cwd, env)
    values = []
    for _ in range(samples):
        argv, cwd, env = make_command()
        values.append(measured_rss(argv, cwd, env))
    print("completed {}".format(name), file=sys.stderr)
    return summarize(values)


def benchmark_seconds(name, action, samples, warmups=1):
    for _ in range(warmups):
        action()
    values = []
    for _ in range(samples):
        started = time.perf_counter()
        action()
        values.append(time.perf_counter() - started)
    print("completed {}".format(name), file=sys.stderr)
    return {
        "samples": len(values),
        "wall_median_s": statistics.median(values),
        "wall_min_s": min(values),
        "wall_max_s": max(values),
        "wall_pstdev_s": statistics.pstdev(values),
    }


def hot_path_benchmarks(source, project, base, samples):
    module = runpy.run_path(str(source), run_name="baton_performance_hot_paths")
    results = {"scheduler_distinct_scopes": {}}
    for count in (1000, 2000, 4000):
        tasks = [
            task_value("T{:04d}-scheduler".format(number))
            for number in range(1, count + 1)
        ]

        def pick(tasks=tasks, count=count):
            wave, skipped = module["pick_wave"](tasks, [], [], count, [])
            if len(wave) != count or skipped:
                raise RuntimeError("scheduler benchmark did not select every task")

        results["scheduler_distinct_scopes"][str(count)] = benchmark_seconds(
            "scheduler_distinct_scopes_{}".format(count), pick, samples,
        )

    def load_state():
        active = module["load_all_tasks"](str(project / ".baton"))
        archived = module["load_archived_tasks"](str(project / ".baton"))
        if len(active) != TASKS or len(archived) != ARCHIVED:
            raise RuntimeError("task-state benchmark fixture changed unexpectedly")

    results["task_state_active_archive_pass"] = benchmark_seconds(
        "task_state_active_archive_pass", load_state, samples,
    )

    create_project = base / "task-create-project"
    shutil.copytree(project, create_project)
    runtime = create_project / ".baton"
    globals_dict = module["cmd_task_create"].__globals__
    original_load = globals_dict["load_tasks_from"]
    original_require_orchestrator = globals_dict["require_orchestrator"]
    original_require_baton_dir = globals_dict["require_baton_dir"]
    original_say = globals_dict["say"]
    calls = []
    creation_number = 0

    def counted_load(directory, validate_history=True):
        calls[-1].append(Path(directory).name)
        return original_load(directory, validate_history)

    def create_task():
        nonlocal creation_number
        creation_number += 1
        calls.append([])
        module["cmd_task_create"](SimpleNamespace(
            title="benchmark creation {}".format(creation_number),
            scope=["created/{}/**".format(creation_number)],
            depends_on=["T1000-benchmark"], tier="benchmark",
        ))
        if calls[-1] != ["tasks", "archive"]:
            raise RuntimeError(
                "task create loaded task directories {}".format(calls[-1])
            )

    globals_dict["load_tasks_from"] = counted_load
    globals_dict["require_orchestrator"] = lambda: None
    globals_dict["require_baton_dir"] = lambda: str(runtime)
    globals_dict["say"] = lambda _message: None
    try:
        results["task_create_snapshot"] = benchmark_seconds(
            "task_create_snapshot", create_task, samples,
        )
    finally:
        globals_dict["load_tasks_from"] = original_load
        globals_dict["require_orchestrator"] = original_require_orchestrator
        globals_dict["require_baton_dir"] = original_require_baton_dir
        globals_dict["say"] = original_say
    results["task_create_snapshot"]["directory_loads_per_call"] = {
        "active": 1,
        "archive": 1,
        "total": 2,
    }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("framework/baton"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--suite-samples", type=int, default=3)
    parser.add_argument("--output", "--json-out", dest="output", type=Path)
    parser.add_argument("--skip-suite", action="store_true")
    parser.add_argument("--hot-paths-only", action="store_true")
    parser.add_argument("--mode", choices=("full", "hot"))
    args = parser.parse_args()
    if args.mode == "hot":
        args.hot_paths_only = True
    source = args.source.resolve()
    repo = args.repo.resolve()
    results = {
        "context": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "git": subprocess.check_output(("git", "--version"), text=True).strip(),
            "tasks": TASKS,
            "archived_tasks": ARCHIVED,
        },
        "benchmarks": {},
    }
    with tempfile.TemporaryDirectory(prefix="baton-performance-") as temporary:
        base = Path(temporary)
        project = prepare_fixture(source, base)
        results["hot_paths"] = hot_path_benchmarks(
            source, project, base, args.samples,
        )
        if args.hot_paths_only:
            encoded = json.dumps(results, indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.write_text(encoded)
            print(encoded, end="")
            return
        installed = project / ".baton" / "baton"
        env = benchmark_environment({"BATON_DIR": project / ".baton"})
        suite_repo = base / "suite"
        shutil.copytree(
            repo, suite_repo,
            ignore=shutil.ignore_patterns(
                ".git", ".attention-relay", ".baton", "__pycache__", "*.pyc",
            ),
        )
        suite_source = suite_repo / "framework" / "baton"
        suite_source.write_bytes(source.read_bytes())
        suite_source.chmod(0o755)
        commands = {
            "startup_help": lambda: ((source, "--help"), repo, None),
            "start_brief": lambda: (
                (installed, "orchestrator", "brief", "--phase", "start"), project, env,
            ),
            "large_status": lambda: ((installed, "status"), project, env),
            "large_validate": lambda: ((installed, "validate"), project, env),
            "capsule_memory_references": lambda: (
                (installed, "task", "capsule", "T0001-benchmark", "--raw"), project, env,
            ),
            "archive_stats": lambda: ((installed, "stats"), project, env),
        }
        for name, command in commands.items():
            results["benchmarks"][name] = benchmark(name, command, args.samples)

        init_counter = 0

        def init_command():
            nonlocal init_counter
            init_counter += 1
            target = base / "init-{:03d}".format(init_counter)
            git_project(target)
            return (source, "init", target), target, None

        results["benchmarks"]["init"] = benchmark("init", init_command, args.samples)

        probe = (
            "import runpy,sys\n"
            "m=runpy.run_path(sys.argv[1],run_name='baton_performance_probe')\n"
            "before=m['git_snapshot'](sys.argv[2])\n"
            "after=m['git_snapshot'](sys.argv[2])\n"
            "paths=m['git_changed_paths'](sys.argv[2],before,after)\n"
            "m['git_paths_diff'](sys.argv[2],before,after,paths)\n"
        )
        snapshot_command = lambda: (
            (sys.executable, "-c", probe, installed, project), project, env,
        )
        results["benchmarks"]["snapshot_diff"] = benchmark(
            "snapshot_diff", snapshot_command, args.samples,
        )

        if not args.skip_suite:
            suite_env = suite_environment(base)
            suite_command = lambda: (
                (sys.executable, suite_repo / "tests" / "test_baton.py"),
                suite_repo, suite_env,
            )
            results["benchmarks"]["full_test_suite"] = benchmark(
                "full_test_suite", suite_command, args.suite_samples, warmups=0,
            )
    encoded = json.dumps(results, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
