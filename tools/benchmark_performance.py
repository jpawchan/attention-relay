#!/usr/bin/env python3
"""Repeatable end-to-end performance benchmarks for Baton (standard library only)."""

import argparse
import ast
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

TASKS = 500
ARCHIVED = 500
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


def run_checked(argv, cwd, env=None):
    result = subprocess.run(
        [str(item) for item in argv], cwd=cwd, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        raise RuntimeError("{} failed: {}".format(" ".join(map(str, argv)), result.stderr))


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
        "tier": "default",
        "scope": ["src/{}/**".format(task_id)],
        "depends_on": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "history": history or [],
    }


def prepare_fixture(source, base):
    project = base / "project"
    git_project(project)
    run_checked((source, "init", project), project)
    runtime = project / ".baton"
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
        history = [
            {
                "at": "2026-01-01T00:00:00Z", "event": "launched",
                "attempt": 1, "capsule_chars": 700 + number % 200,
            },
            {
                "at": "2026-01-01T00:00:01Z", "event": "worker_exited",
                "status": "failed", "note": "worker_timeout",
            },
        ]
        (archive / (task_id + ".json")).write_text(
            json.dumps(task_value(task_id, status="failed", history=history)) + "\n"
        )
        receipt_dir = archive / (task_id + ".work")
        receipt_dir.mkdir()
        receipt = dict(RECEIPT, task_id=task_id)
        (receipt_dir / "attempt-1.briefs.json").write_text(json.dumps(receipt) + "\n")
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
    merged = os.environ.copy()
    if env:
        merged.update(env)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("framework/baton"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--suite-samples", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-suite", action="store_true")
    args = parser.parse_args()
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
        installed = project / ".baton" / "baton"
        env = dict(os.environ, BATON_DIR=str(project / ".baton"))
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
            suite_command = lambda: (
                (sys.executable, suite_repo / "tests" / "test_baton.py"), suite_repo, None,
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
