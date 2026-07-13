#!/usr/bin/env python3
"""End-to-end tests for Baton."""

import hashlib
import io
import json
import os
import re
import runpy
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BATON = ROOT / "framework" / "baton"
AUTHOR_EMAIL = "78247292+jpawchan@users.noreply.github.com"

GOOD_WORKER = r'''
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(os.environ["BATON_ROOT"])
rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
task = json.loads((rd / "tasks" / f"{tid}.json").read_text())

starts = os.environ.get("STARTS")
if starts:
    with open(starts, "a", encoding="utf-8") as f:
        f.write(tid + "\n")

barrier = os.environ.get("BARRIER")
if barrier:
    barrier_dir = Path(barrier)
    barrier_dir.mkdir(parents=True, exist_ok=True)
    (barrier_dir / tid).write_text("ready\n")
    deadline = time.monotonic() + 3
    while len(list(barrier_dir.iterdir())) < int(os.environ.get("BARRIER_SIZE", "2")):
        if time.monotonic() > deadline:
            raise SystemExit("parallel barrier timed out")
        time.sleep(0.01)

scope = (task.get("scope") or ["work/**"])[0]
prefix = scope.split("*")[0].rstrip("/") or "work"
target = root / prefix
target.mkdir(parents=True, exist_ok=True)
target_file = target / f"{tid}.txt"
target_file.write_text(f"attempt {attempt}\n")
changed = [target_file.relative_to(root).as_posix()]

outside = os.environ.get("WRITE_OUTSIDE")
outside_task = os.environ.get("WRITE_OUTSIDE_TASK")
if outside and (not outside_task or outside_task == tid):
    outside_path = root / outside
    outside_path.parent.mkdir(parents=True, exist_ok=True)
    outside_path.write_text(f"changed by {tid}\n")
    changed.append(Path(outside).as_posix())

marker = os.environ.get("FINISH_MARKER")
if marker:
    changed.append((target / "after-finish.txt").relative_to(root).as_posix())

report = rd / "work" / tid / f"attempt-{attempt}.report.md"
report.parent.mkdir(parents=True, exist_ok=True)
brief = subprocess.run(
    [sys.executable, str(rd / "baton"), "task", "brief", tid, "--phase", "report"],
    cwd=root, check=True, capture_output=True, text=True,
)
token = next(line.removeprefix("Brief token: ") for line in brief.stdout.splitlines()
             if line.startswith("Brief token: "))
status = os.environ.get("SUBMIT_STATUS", "needs_review")
report.write_text(
    f"# {tid} report\n\n## Result\n{status}\n\n## Changes\n- updated task output\n\n"
    "## Verification\n- worker completed\n\n## Decisions and risks\n- none\n"
)
finish = [sys.executable, str(rd / "baton"), "task", "finish", tid,
          "--status", status, "--brief", token]
for path in changed:
    finish.extend(["--changed", path])
subprocess.run(finish, cwd=root, check=True)

self_accept = os.environ.get("SELF_ACCEPT_RESULT")
if self_accept:
    result = subprocess.run([sys.executable, str(rd / "baton"), "task", "accept", tid],
                            cwd=root)
    Path(self_accept).write_text(str(result.returncode))

if marker:
    Path(marker).write_text("finished\n")
    time.sleep(0.5)
    (target / "after-finish.txt").write_text("late but in scope\n")
if os.environ.get("SLEEP_AFTER_FINISH"):
    time.sleep(float(os.environ["SLEEP_AFTER_FINISH"]))
if os.environ.get("EXIT_CODE"):
    raise SystemExit(int(os.environ["EXIT_CODE"]))
'''

NO_CHANGE_WORKER = r'''
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["BATON_ROOT"])
rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
report = rd / "work" / tid / f"attempt-{attempt}.report.md"
report.parent.mkdir(parents=True, exist_ok=True)
brief = subprocess.run(
    [sys.executable, str(rd / "baton"), "task", "brief", tid, "--phase", "report"],
    cwd=root, check=True, capture_output=True, text=True,
)
token = next(line.removeprefix("Brief token: ") for line in brief.stdout.splitlines()
             if line.startswith("Brief token: "))
report.write_text(
    "# no-change report\n\n## Result\nneeds_review\n\n## Changes\n- no changes\n\n"
    "## Verification\n- worker completed\n\n## Decisions and risks\n- none\n"
)
subprocess.run([sys.executable, str(rd / "baton"), "task", "finish", tid,
                "--status", "needs_review", "--brief", token], cwd=root, check=True)
'''

TIMEOUT_WORKER = r'''
import os
from pathlib import Path
import subprocess
import sys
import time

marker = os.environ["LATE_MARKER"]
subprocess.Popen([sys.executable, "-c",
                  "import pathlib,time; time.sleep(0.6); pathlib.Path(%r).write_text('late')" % marker])
time.sleep(10)
'''


TIER_TIMEOUT_WORKER = r'''
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(os.environ["BATON_ROOT"])
rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
task = json.loads((rd / "tasks" / f"{tid}.json").read_text())
if task["tier"] == "short":
    time.sleep(10)

report = rd / "work" / tid / f"attempt-{attempt}.report.md"
report.parent.mkdir(parents=True, exist_ok=True)
brief = subprocess.run(
    [sys.executable, str(rd / "baton"), "task", "brief", tid, "--phase", "report"],
    cwd=root, check=True, capture_output=True, text=True,
)
token = next(line.removeprefix("Brief token: ") for line in brief.stdout.splitlines()
             if line.startswith("Brief token: "))
report.write_text(
    "# tier timeout report\n\n## Result\nneeds_review\n\n## Changes\n- no changes\n\n"
    "## Verification\n- worker completed\n\n## Decisions and risks\n- none\n"
)
subprocess.run([sys.executable, str(rd / "baton"), "task", "finish", tid,
                "--status", "needs_review", "--brief", token], cwd=root, check=True)
'''


RESULT_WITHOUT_REPORT_WORKER = r'''
import json
import os
from pathlib import Path

rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
path = rd / "work" / tid / f"attempt-{attempt}.result.json"
path.write_text(json.dumps({
    "status": "needs_review", "note": "manual", "at": "now",
    "lease": os.environ["BATON_LEASE"], "changed_paths": [],
}))
'''

MALFORMED_OUTPUT_WORKER = r'''
import json
import os
from pathlib import Path

rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
report = rd / "work" / tid / f"attempt-{attempt}.report.md"
report.mkdir()
result = rd / "work" / tid / f"attempt-{attempt}.result.json"
result.write_text(json.dumps({
    "status": "needs_review", "note": {"not": "text"}, "at": "now",
    "lease": os.environ["BATON_LEASE"],
}))
'''

NON_UTF8_RESULT_WORKER = r'''
import os
from pathlib import Path

rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
path = rd / "work" / tid / f"attempt-{attempt}.result.json"
path.write_bytes(b"\xff\xfe")
'''


OVERSIZED_INTEGER_RESULT_WORKER = r'''
import json
import os
from pathlib import Path

rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
path = rd / "work" / tid / f"attempt-{attempt}.result.json"
path.write_text(
    '{"status":"failed","note":"otherwise valid","at":"now","lease":'
    + json.dumps(os.environ["BATON_LEASE"])
    + ',"changed_paths":[],"oversized":' + "9" * 5000 + "}\n"
)
'''


STAGE_WORKER = r'''
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["BATON_ROOT"])
rd = Path(os.environ["BATON_DIR"])
tid = os.environ["BATON_TASK_ID"]
attempt = os.environ["BATON_ATTEMPT"]
path = root / "new" / "staged.txt"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("staged\n")
subprocess.run(["git", "add", str(path)], cwd=root, check=True)
report = rd / "work" / tid / f"attempt-{attempt}.report.md"
report.parent.mkdir(parents=True, exist_ok=True)
brief = subprocess.run(
    [sys.executable, str(rd / "baton"), "task", "brief", tid, "--phase", "report"],
    cwd=root, check=True, capture_output=True, text=True,
)
token = next(line.removeprefix("Brief token: ") for line in brief.stdout.splitlines()
             if line.startswith("Brief token: "))
report.write_text(
    "# staged report\n\n## Result\nneeds_review\n\n## Changes\n- staged file\n\n"
    "## Verification\n- worker completed\n\n## Decisions and risks\n- none\n"
)
subprocess.run([sys.executable, str(rd / "baton"), "task", "finish", tid,
                "--status", "needs_review", "--brief", token,
                "--changed", "new/staged.txt"],
               cwd=root, check=True)
'''


class BatonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="baton-test-")
        self.base = Path(self.temp.name)
        self.worker_number = 0

    def tearDown(self):
        self.temp.cleanup()

    def command(self, argv, cwd, env=None, check=False, timeout=15):
        merged = os.environ.copy()
        if env:
            merged.update({k: str(v) for k, v in env.items()})
        result = subprocess.run(
            [str(arg) for arg in argv], cwd=cwd, env=merged, text=True,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
        )
        if check and result.returncode:
            self.fail(
                f"command failed ({result.returncode}): {' '.join(map(str, argv))}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def git(self, project, *args, check=True):
        return self.command(["git", *args], project, check=check)

    def make_project(self, name="project", commit=True, initialize=True):
        project = self.base / name
        project.mkdir()
        self.git(project, "init", "-q")
        self.git(project, "config", "user.name", "JPawchan")
        self.git(project, "config", "user.email", AUTHOR_EMAIL)
        if commit:
            (project / "seed.txt").write_text("seed\n")
            self.git(project, "add", "seed.txt")
            self.git(project, "commit", "-qm", "seed")
        if initialize:
            self.command([SOURCE_BATON, "init", project], project, check=True)
        return project

    def baton(self, project, *args, env=None, check=False, timeout=15):
        return self.command(
            [project / ".baton" / "baton", *args], project,
            env=env, check=check, timeout=timeout,
        )

    def write_worker(self, body):
        self.worker_number += 1
        path = self.base / f"worker-{self.worker_number}.py"
        path.write_text(body)
        return path

    def configure(self, project, worker, max_parallel=3,
                  timeout_minutes: int | float = 1, capsule_max_chars=4000):
        command = f"{sys.executable} {worker} {{prompt_file}}"
        config = (
            "[commands]\n"
            f"worker = {json.dumps(command)}\n\n"
            "[tiers.test]\n\n"
            "[limits]\n"
            f"max_parallel = {max_parallel}\n"
            f"capsule_max_chars = {capsule_max_chars}\n"
            f"worker_timeout_minutes = {timeout_minutes}\n"
        )
        (project / ".baton" / "config.toml").write_text(config)

    def task_create_command(self, title, scope=None, depends_on=None, tier="test"):
        args = ["task", "create", "--title", title]
        for item in scope or []:
            args += ["--scope", item]
        for item in depends_on or []:
            args += ["--depends-on", item]
        if tier is not None:
            args += ["--tier", tier]
        return args

    def ensure_test_tier(self, project):
        config_path = project / ".baton" / "config.toml"
        try:
            config = tomllib.loads(config_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return
        if "test" not in config.get("tiers", {}):
            config_path.write_text(config_path.read_text() + (
                '\n[tiers.test]\ncommand = "/usr/bin/true {prompt_file}"\n'
            ))

    def create_task(self, project, title, scope=None, depends_on=None, tier="test"):
        if tier == "test":
            self.ensure_test_tier(project)
        args = self.task_create_command(title, scope, depends_on, tier)
        result = self.baton(project, *args, check=True)
        task_id = result.stdout.split()[1]
        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        content = spec.read_text().replace(
            "Replace this line with one clear outcome.",
            f"Complete the {title} task.",
        ).replace(
            "- Add observable requirements.",
            "- The targeted task behavior is verified.",
        )
        spec.write_text(content)
        return task_id

    def write_memory(self, project, entries):
        runtime = project / ".baton"
        index = "\n".join(
            f"- {memory_id} [{audience}] {summary}"
            for memory_id, audience, summary, _body in entries
        )
        bodies = "\n\n".join(
            f"### {memory_id} [{audience}] {summary}\n{body}"
            for memory_id, audience, summary, body in entries
        )
        (runtime / "memory.md").write_text(
            "# Memory\n\n## Index\n" + index + "\n\n## Entries\n\n" + bodies + "\n"
        )

    def try_create_task(self, project, title, scope=None, depends_on=None, tier="test"):
        if tier == "test":
            self.ensure_test_tier(project)
        args = self.task_create_command(title, scope, depends_on, tier)
        return self.baton(project, *args)

    def state(self, project, task_id):
        path = project / ".baton" / "tasks" / f"{task_id}.json"
        return json.loads(path.read_text())

    def lease_task(self, project, task_id, lease):
        runtime = project / ".baton"
        state_path = runtime / "tasks" / f"{task_id}.json"
        task = json.loads(state_path.read_text())
        task["status"] = "running"
        task["runner"] = {"pid": None, "started_at": "now", "lease": lease}
        state_path.write_text(json.dumps(task))
        spec = (runtime / "tasks" / f"{task_id}.md").read_text()
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_brief_probe")
        memory_entries = module["memory_index_entries"](
            (runtime / "memory.md").read_text()
        )
        capsule = module["compile_context_capsule"](task, spec, memory_entries)
        digest = hashlib.sha256(capsule.encode()).hexdigest()
        brief = runtime / "work" / task_id / f"attempt-{task['attempt']}.brief.md"
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text(f"Content digest: sha256:{digest}\n\n{capsule}")
        return {
            "BATON_TASK_ID": task_id,
            "BATON_ATTEMPT": str(task["attempt"]),
            "BATON_LEASE": lease,
            "BATON_DIR": runtime,
            "BATON_ROOT": project,
        }

    def report_brief_token(self, project, task_id, env):
        brief = self.baton(
            project, "task", "brief", task_id, "--phase", "report",
            env=env, check=True,
        )
        token = next(
            line.removeprefix("Brief token: ")
            for line in brief.stdout.splitlines()
            if line.startswith("Brief token: ")
        )
        return brief, token

    def report_text(self, status="needs_review", newline="\n"):
        lines = [
            "# task report", "", "## Result", status, "", "## Changes",
            "- test changes", "", "## Verification", "- test verification",
            "", "## Decisions and risks", "- none", "",
        ]
        return newline.join(lines)

    def prepare_finish(self, name):
        project = self.make_project(name)
        task_id = self.create_task(project, name)
        env = self.lease_task(project, task_id, name + "-lease")
        _brief, token = self.report_brief_token(project, task_id, env)
        work = project / ".baton" / "work" / task_id
        return project, task_id, env, work / "attempt-1.report.md", token

    def review_brief_token(self, project, task_id, env=None, include_log_tail=False):
        args = ["orchestrator", "brief", "--phase", "review", task_id]
        if include_log_tail:
            args.append("--include-log-tail")
        brief = self.baton(
            project, *args, env=env, check=True,
        )
        token = next(
            line.removeprefix("Review token: ")
            for line in brief.stdout.splitlines()
            if line.startswith("Review token: ")
        )
        return brief, token

    def accept_task(self, project, task_id):
        _brief, token = self.review_brief_token(project, task_id)
        return self.baton(
            project, "task", "accept", task_id, "--brief", token, check=True,
        )

    def test_init_requires_git_and_creates_only_runtime_files(self):
        plain = self.base / "plain"
        plain.mkdir()
        result = self.command([SOURCE_BATON, "init", plain], plain)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((plain / ".baton").exists())

        project = self.make_project()
        initialized = self.command([SOURCE_BATON, "init", project], project, check=True)
        self.assertIn(
            "next: have your coding agent read .baton/orchestrator.md",
            initialized.stdout,
        )
        self.assertNotIn("orchestrator brief --phase start", initialized.stdout)
        lines = (project / ".gitignore").read_text().splitlines()
        self.assertEqual(lines.count(".baton/"), 1)
        runtime = project / ".baton"
        self.assertTrue(os.access(runtime / "baton", os.X_OK))
        self.assertTrue((runtime / "config.toml").exists())
        self.assertFalse((runtime / "config.example.toml").exists())

        with (runtime / "config.toml").open("rb") as source:
            fresh_config = tomllib.load(source)
        self.assertNotIn("worker", fresh_config.get("commands", {}))
        self.assertNotIn("tiers", fresh_config)
        for forbidden in ("model", "provider", "reasoning", "fallback"):
            self.assertNotIn(forbidden, fresh_config)

        config = runtime / "config.toml"
        memory = runtime / "memory.md"
        config.write_text("# preserved config\n")
        memory.write_text("# preserved memory\n")
        self.command([SOURCE_BATON, "init", project, "--force"], project, check=True)
        self.assertEqual(config.read_text(), "# preserved config\n")
        self.assertEqual(memory.read_text(), "# preserved memory\n")

        nested = project / "nested"
        nested.mkdir()
        nested_result = self.command([SOURCE_BATON, "init", nested], nested)
        self.assertNotEqual(nested_result.returncode, 0)
        self.assertFalse((nested / ".baton").exists())

        symlink_project = self.make_project("symlink-project", initialize=False)
        external = self.base / "external"
        external.mkdir()
        (external / "sentinel").write_text("unchanged\n")
        (symlink_project / ".baton").symlink_to(
            external, target_is_directory=True,
        )
        escaped = self.command(
            [SOURCE_BATON, "init", symlink_project], symlink_project,
        )
        self.assertNotEqual(escaped.returncode, 0)
        self.assertEqual(
            sorted(path.name for path in external.iterdir()), ["sentinel"],
        )

        subrepo = self.base / "subrepo"
        subrepo.mkdir()
        self.git(subrepo, "init", "-q")
        self.git(subrepo, "config", "user.name", "JPawchan")
        self.git(subrepo, "config", "user.email", AUTHOR_EMAIL)
        (subrepo / "lib.txt").write_text("library\n")
        self.git(subrepo, "add", "lib.txt")
        self.git(subrepo, "commit", "-qm", "library")
        submodule_project = self.make_project("submodule-project", initialize=False)
        self.git(
            submodule_project, "-c", "protocol.file.allow=always",
            "submodule", "add", "-q", str(subrepo), "vendor",
        )
        self.git(submodule_project, "commit", "-qam", "add submodule")
        unsupported = self.command(
            [SOURCE_BATON, "init", submodule_project], submodule_project,
        )
        self.assertNotEqual(unsupported.returncode, 0)
        self.git(submodule_project, "rm", "--cached", "-q", "vendor")
        staged_removal = self.command(
            [SOURCE_BATON, "init", submodule_project], submodule_project,
        )
        self.assertNotEqual(staged_removal.returncode, 0)
        self.assertFalse((submodule_project / ".baton").exists())

    def test_runtime_safety_rejects_nested_file_and_directory_symlinks(self):
        for target_is_directory in (False, True):
            with self.subTest(target_is_directory=target_is_directory):
                project = self.make_project(
                    "runtime-symlink-{}".format(
                        "directory" if target_is_directory else "file"
                    )
                )
                external = self.base / (
                    "external-directory" if target_is_directory else "external-file"
                )
                if target_is_directory:
                    external.mkdir()
                else:
                    external.write_text("outside runtime\n")
                link = project / ".baton" / "work" / "nested-link"
                link.symlink_to(external, target_is_directory=target_is_directory)

                rejected = self.baton(project, "status")
                self.assertEqual(rejected.returncode, 1)
                self.assertIn(
                    "managed runtime paths cannot be symlinks:",
                    rejected.stderr,
                )
                self.assertIn("nested-link", rejected.stderr)

    def test_status_reuses_loaded_tasks_when_rendering_next_actions(self):
        project = self.make_project("status-load-count")
        self.create_task(project, "status load count", ["status/**"])
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_status_load_probe")
        globals_dict = module["cmd_status"].__globals__
        original = globals_dict["load_all_tasks"]
        calls = []

        def counted_load(baton_dir, validate_history=True):
            calls.append((baton_dir, validate_history))
            return original(baton_dir, validate_history)

        globals_dict["load_all_tasks"] = counted_load
        previous_directory = os.getcwd()
        previous_baton_dir = os.environ.get("BATON_DIR")
        try:
            os.chdir(project)
            os.environ["BATON_DIR"] = str(project / ".baton")
            with redirect_stdout(io.StringIO()):
                module["cmd_status"](SimpleNamespace())
        finally:
            globals_dict["load_all_tasks"] = original
            os.chdir(previous_directory)
            if previous_baton_dir is None:
                os.environ.pop("BATON_DIR", None)
            else:
                os.environ["BATON_DIR"] = previous_baton_dir
        self.assertEqual(len(calls), 1)

    def test_scope_normalization_and_input_validation(self):
        project = self.make_project()
        first = self.create_task(project, "plain scope", ["src/**"])
        second = self.create_task(project, "dot scope", ["./src/**"])
        dry = self.baton(project, "run", "--dry-run", check=True)
        self.assertIn(first, dry.stdout)
        self.assertIn(f"skip {second}: scope conflicts", dry.stdout)

        upper = self.create_task(project, "upper scope", ["Case/**"])
        lower = self.create_task(project, "lower scope", ["case/**"])
        case_dry = self.baton(project, "run", upper, lower, "--dry-run", check=True)
        self.assertIn(f"would run: {upper}", case_dry.stdout)
        self.assertIn(f"skip {lower}: scope conflicts", case_dry.stdout)

        whole = self.create_task(project, "whole", ["."])
        self.assertEqual(self.state(project, whole)["scope"], [])
        absolute_scope = str(self.base / "absolute") + "/**"
        for bad in ("../src/**", absolute_scope, "src/[ab].py", "src/**x/file"):
            result = self.try_create_task(project, "bad scope", [bad])
            self.assertNotEqual(result.returncode, 0, bad)
        rejected_id = self.baton(
            project, "task", "create", "--title", "bad", "--id", "T999-bad",
        )
        self.assertNotEqual(rejected_id.returncode, 0)
        secret = project / "secret.json"
        secret.write_text('{"sentinel": "do-not-read"}\n')
        traversal = self.baton(project, "task", "show", "../../secret")
        self.assertNotEqual(traversal.returncode, 0)
        self.assertNotIn("do-not-read", traversal.stdout)
        for bad_id in ("T000-lower", "T1-bad", "../T001-bad"):
            result = self.baton(project, "task", "show", bad_id)
            self.assertNotEqual(result.returncode, 0, bad_id)
        empty_title = self.baton(
            project, "task", "create", "--title", "", "--scope", "empty/**",
        )
        self.assertNotEqual(empty_title.returncode, 0)
        truncated = self.create_task(project, "x" * 39 + " next", ["slug/**"])
        self.assertEqual(truncated, "T006-" + "x" * 39)
        for value in ("0", "-1"):
            result = self.baton(project, "run", "--dry-run", "--max-parallel", value)
            self.assertNotEqual(result.returncode, 0, value)

    def test_task_create_rejects_multiline_title_section_injection(self):
        project = self.make_project()
        runtime = project / ".baton"
        title = "normal title\n\n## Objective\nInjected objective from title"
        rejected = self.baton(
            project, "task", "create", "--title", title, "--tier", "test",
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("single-line", rejected.stderr)
        self.assertEqual(list((runtime / "tasks").iterdir()), [])

        unicode_title = "aperçu 東京 😀"
        task_id = self.create_task(project, unicode_title)
        self.assertEqual(self.state(project, task_id)["title"], unicode_title)
        spec = runtime / "tasks" / f"{task_id}.md"
        self.assertEqual(spec.read_text().count("## Objective\n"), 1)

    def test_task_create_rejects_unicode_line_separators_without_artifacts(self):
        for separator in ("\u2028", "\u2029"):
            for variant, title in (
                    ("embedded", f"safe{separator}unsafe"),
                    ("trailing", f"trailing{separator}")):
                with self.subTest(separator=hex(ord(separator)), variant=variant):
                    project = self.make_project(
                        f"unicode-title-{ord(separator):x}-{variant}"
                    )
                    runtime = project / ".baton"
                    rejected = self.baton(
                        project, "task", "create", "--title", title,
                        "--tier", "test",
                    )
                    self.assertEqual(rejected.returncode, 1)
                    self.assertIn("single-line", rejected.stderr)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertEqual(list((runtime / "tasks").iterdir()), [])

    def test_parallel_wave_reports_diffs_and_lifecycle(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        one = self.create_task(project, "alpha", ["alpha/**"])
        two = self.create_task(project, "beta", ["beta/**"])
        barrier = self.base / "barrier"
        run = self.baton(project, "run", env={"BARRIER": barrier}, check=True)
        self.assertIn(one, run.stdout)
        for task_id in (one, two):
            self.assertEqual(self.state(project, task_id)["status"], "needs_review")
            work = project / ".baton" / "work" / task_id
            self.assertTrue((work / "attempt-1.report.md").stat().st_size)
            diff = (work / "attempt-1.diff").read_text()
            self.assertIn(f"{task_id}.txt", diff)
        self.accept_task(project, one)
        self.accept_task(project, two)

    def test_attempt_diff_starts_at_attempt_baseline(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        first = self.create_task(project, "first", ["same/**"])
        self.baton(project, "run", check=True)
        self.accept_task(project, first)

        human = project / "same" / "human.txt"
        human.write_text("already here\n")
        second = self.create_task(project, "second", ["same/**"], [first])
        self.baton(project, "run", check=True)
        diff = (project / ".baton" / "work" / second / "attempt-1.diff").read_text()
        self.assertIn(f"{second}.txt", diff)
        self.assertNotIn(f"{first}.txt", diff)
        self.assertNotIn("human.txt", diff)

        self.baton(project, "task", "return", second, "--reason", "retry", check=True)
        no_change = self.write_worker(NO_CHANGE_WORKER)
        self.configure(project, no_change)
        self.baton(project, "run", second, check=True)
        retry_diff = project / ".baton" / "work" / second / "attempt-2.diff"
        self.assertEqual(retry_diff.read_text(), "")

    def test_scope_violation_blocks_acceptance_even_when_file_was_dirty(self):
        project = self.make_project()
        outside = project / "outside.txt"
        outside.write_text("before\n")
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "scoped", ["inside/**"])
        run = self.baton(project, "run", env={"WRITE_OUTSIDE": "outside.txt"}, check=True)
        self.assertIn("scope violation", run.stdout.lower())
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "blocked")
        self.assertIn("outside.txt", state["scope_violations"])
        violations_diff = (
            project / ".baton" / "work" / task_id
            / "attempt-1.violations.diff"
        )
        self.assertIn("outside.txt", violations_diff.read_text())
        accept = self.baton(project, "task", "accept", task_id)
        self.assertNotEqual(accept.returncode, 0)
        returned = self.baton(
            project, "task", "return", task_id, "--reason", "retry",
        )
        self.assertNotEqual(returned.returncode, 0)
        outside.write_text("before\n")
        self.baton(
            project, "task", "return", task_id,
            "--reason", "outside file restored", check=True,
        )
        self.assertEqual(self.state(project, task_id)["status"], "queued")

    def test_dotfile_scope_matches_dotfile_paths(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "workflow", [".github/**"])
        self.baton(project, "run", task_id, check=True)
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")
        diff = project / ".baton" / "work" / task_id / "attempt-1.diff"
        self.assertIn(f".github/{task_id}.txt", diff.read_text())

    def test_changed_paths_preserve_literal_posix_filename_characters(self):
        worker = self.write_worker(GOOD_WORKER.replace(
            'target_file = target / f"{tid}.txt"',
            'target_file = target / os.environ["LITERAL_NAME"]',
        ))
        names = (
            "[id].txt", "what?.txt", "star*.txt", " trailing.txt ",
            "back\\slash.txt",
        )
        for index, name in enumerate(names):
            with self.subTest(name=name):
                project = self.make_project(f"literal-path-{index}")
                self.configure(project, worker)
                task_id = self.create_task(project, f"literal path {index}", ["src/**"])
                self.baton(
                    project, "run", task_id, env={"LITERAL_NAME": name}, check=True,
                )
                state = self.state(project, task_id)
                self.assertEqual(state["status"], "needs_review")
                worker_exit = state["history"][-1]
                expected = ["src/" + name]
                self.assertEqual(worker_exit["declared_paths"], expected)
                self.assertEqual(worker_exit["observed_paths"], expected)

    def test_needs_decision_round_trip(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "decision", ["decision/**"])
        self.baton(
            project, "run", task_id,
            env={"SUBMIT_STATUS": "needs_decision"}, check=True,
        )
        self.assertEqual(self.state(project, task_id)["status"], "needs_decision")
        self.baton(
            project, "task", "decide", task_id,
            "--answer", "Use option A", check=True,
        )
        self.assertEqual(self.state(project, task_id)["attempt"], 2)
        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        self.assertIn("Use option A", spec.read_text())

    def test_decision_question_text_is_sanitized_flattened_and_exactly_bounded(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_decision_text_probe")
        flatten = module["flatten_bounded_text"]
        raw = (
            "\x1b]terminal title\x07 First\r\n\t\x1b[31msecond\x1b[0m"
            "\v\f\x85third\x00tail " + "x" * 200
        )
        clean = "First second thirdtail " + "x" * 200
        bounded = flatten(raw, 32)
        self.assertEqual(bounded, clean[:31] + "…")
        self.assertEqual(len(bounded), 32)
        self.assertEqual(flatten("  one\n\ttwo  ", 160), "one two")
        self.assertEqual(flatten({"not": "text"}, 160), "")
        self.assertEqual(flatten("", 160), "")

        history_note = "Question recovered from history?"
        task = {
            "last_note": "Current worker question?",
            "history": [{
                "event": "worker_exited", "status": "needs_decision",
                "note": history_note,
            }],
        }
        self.assertEqual(module["decision_question"](task), "Current worker question?")
        task["last_note"] = {"not": "text"}
        self.assertEqual(module["decision_question"](task), history_note)
        task["history"][0]["note"] = {"not": "text"}
        self.assertEqual(module["decision_question"](task), "")

    def test_next_actions_and_status_inline_bounded_worker_questions(self):
        project = self.make_project()
        reviews = [self.create_task(project, f"review {index}") for index in range(4)]
        decisions = [self.create_task(project, f"decision {index}") for index in range(3)]
        runtime = project / ".baton"
        raw_question = (
            "Choose\n\x1b[31moption\x1b[0m \x00\x85 carefully: " + "x" * 200
        )

        for task_id in reviews:
            path = runtime / "tasks" / f"{task_id}.json"
            task = json.loads(path.read_text())
            task["status"] = "needs_review"
            path.write_text(json.dumps(task))
        for index, task_id in enumerate(decisions):
            path = runtime / "tasks" / f"{task_id}.json"
            task = json.loads(path.read_text())
            question = raw_question if index == 0 else f"Question {index}?"
            task["status"] = "needs_decision"
            task["last_note"] = question
            task["history"].append({
                "event": "worker_exited", "status": "needs_decision", "note": question,
            })
            path.write_text(json.dumps(task))

        status = self.baton(project, "status", check=True)
        self.assertNotIn("\x1b", status.stdout)
        self.assertNotIn("\x00", status.stdout)
        self.assertIn(" - worker question: Choose option carefully: ", status.stdout)
        actions = status.stdout.rsplit("Next actions:\n", 1)[1].splitlines()
        self.assertLessEqual(len(actions), 5)
        self.assertTrue(all(line.startswith("- review") for line in actions[:3]))
        self.assertEqual(actions[2], "- review: +2 more")
        self.assertTrue(actions[3].startswith(
            f"- decide {decisions[0]}: worker question: Choose option carefully: ",
        ))
        rendered_question = actions[3].split("worker question: ", 1)[1]
        self.assertEqual(len(rendered_question), 160)
        self.assertTrue(rendered_question.endswith("…"))
        self.assertEqual(actions[4], "- decide: +2 more")

        fallback_project = self.make_project("decision-fallback")
        fallback = self.create_task(fallback_project, "missing question")
        fallback_path = (
            fallback_project / ".baton" / "tasks" / f"{fallback}.json"
        )
        fallback_task = json.loads(fallback_path.read_text())
        fallback_task["status"] = "needs_decision"
        fallback_task["last_note"] = {"not": "text"}
        fallback_task["history"].append({
            "event": "worker_exited", "status": "needs_decision", "note": None,
        })
        fallback_path.write_text(json.dumps(fallback_task))
        fallback_status = self.baton(fallback_project, "status", check=True)
        self.assertIn(f"\n- decide {fallback}\n", fallback_status.stdout)
        self.assertNotIn("worker question:", fallback_status.stdout)

    def test_start_brief_bounds_questions_and_recommends_a_real_decision_id(self):
        project = self.make_project()
        decisions = [self.create_task(project, f"start decision {index}") for index in range(5)]
        runtime = project / ".baton"
        for index, task_id in enumerate(decisions):
            path = runtime / "tasks" / f"{task_id}.json"
            task = json.loads(path.read_text())
            question = f"Worker\nquestion \x1b[31m{index}\x1b[0m?"
            task["status"] = "needs_decision"
            task["last_note"] = question
            task["history"].append({
                "event": "worker_exited", "status": "needs_decision", "note": question,
            })
            path.write_text(json.dumps(task))

        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        decision_block = started.stdout.split("Needs decision: ", 1)[1].split(
            "Needs review:", 1,
        )[0]
        self.assertIn("+1 more", decision_block.splitlines()[0])
        question_lines = [
            line for line in decision_block.splitlines() if "worker question:" in line
        ]
        self.assertEqual(len(question_lines), 2)
        self.assertEqual(
            question_lines[0], f"- {decisions[0]}: worker question: Worker question 0?",
        )
        self.assertEqual(
            question_lines[1], f"- {decisions[1]}: worker question: Worker question 1?",
        )
        self.assertIn(
            f"Recommended next command: .baton/baton task decide {decisions[0]} --answer ANSWER",
            started.stdout,
        )
        self.assertNotIn(".baton/baton task decide +1 more", started.stdout)

    def test_start_brief_onboards_only_until_all_conventional_routes_are_valid(self):
        project = self.make_project()
        question = (
            "Which model and reasoning level should Baton use for hard, medium, "
            "and easy tasks? You can specify each one or ask me to derive the "
            "settings from the current orchestrator."
        )
        ui_rule = (
            "Ask this as a persistent plain-text question that remains visible "
            "until answered. Never use a transient form; expiration or dismissal "
            "is not an answer and must not be treated as selecting any option."
        )

        def routing_section(output):
            marker = "\nWorker routing:\n"
            self.assertEqual(output.count(marker), 1)
            body = output.split(marker, 1)[1].split("\n\n", 1)[0]
            return ["Worker routing:", *body.splitlines()]

        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        ).stdout
        section = routing_section(started)
        self.assertIn(
            "- Current safe settings: hard: not configured; medium: not configured; easy: not configured.",
            section,
        )
        self.assertEqual(sum(question in line for line in section), 1)
        self.assertEqual(sum(ui_rule in line for line in section), 1)
        self.assertNotIn("Harness memory:", started)
        self.assertNotIn("GPT", "\n".join(section))
        self.assertNotIn("Claude", "\n".join(section))
        self.assertNotIn("command =", "\n".join(section))

        config = project / ".baton" / "config.toml"
        config.write_text(
            '[tiers.hard]\ncommand = "/usr/bin/true {prompt_file}"\n'
            '[tiers.medium]\ncommand = "/missing/worker {prompt_file}"\n'
            '[tiers.easy]\ncommand = "/usr/bin/true {prompt_file}"\n'
        )
        partial = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        ).stdout
        partial_section = routing_section(partial)
        self.assertIn(
            "- Current safe settings: hard: unlabeled worker; medium: not configured; easy: unlabeled worker.",
            partial_section,
        )
        self.assertEqual(sum(question in line for line in partial_section), 1)

        config.write_text(config.read_text().replace("/missing/worker", "/usr/bin/true"))
        complete = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        ).stdout
        complete_section = routing_section(complete)
        self.assertIn(
            "- Current safe settings: hard: unlabeled worker; medium: unlabeled worker; easy: unlabeled worker.",
            complete_section,
        )
        self.assertNotIn(question, "\n".join(complete_section))
        self.assertTrue(any(
            "change these settings at any time" in line for line in complete_section
        ))

    def test_worker_role_and_live_runner_guards(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "guarded", ["guarded/**"])
        marker = self.base / "finished"
        self_accept = self.base / "self-accept"
        proc = subprocess.Popen(
            [str(project / ".baton" / "baton"), "run", task_id],
            cwd=project,
            env=dict(os.environ, FINISH_MARKER=str(marker), SELF_ACCEPT_RESULT=str(self_accept)),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        self.assertEqual(self.state(project, task_id)["status"], "running")
        self.assertNotEqual(self.baton(project, "task", "accept", task_id).returncode, 0)
        dry = self.baton(project, "run", task_id, "--dry-run")
        self.assertIn("status is running", dry.stdout)
        stdout, stderr = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, stdout + stderr)
        self.assertNotEqual(self_accept.read_text(), "0")
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")
        diff = project / ".baton" / "work" / task_id / "attempt-1.diff"
        self.assertIn("after-finish.txt", diff.read_text())

    def test_worker_phase_briefs_and_default_finish_gate(self):
        project = self.make_project()
        task_id = self.create_task(project, "brief gate", ["brief/**"])
        env = self.lease_task(project, task_id, "lease-one")
        runtime = project / ".baton"
        token_path = runtime / "work" / task_id / "finish-brief-token.json"

        unleased = self.baton(project, "task", "brief", task_id, "--phase", "edit")
        self.assertNotEqual(unleased.returncode, 0)
        for phase, heading in (("edit", "Edit"), ("verify", "Verify")):
            output = self.baton(
                project, "task", "brief", task_id, "--phase", phase,
                env=env, check=True,
            )
            self.assertTrue(output.stdout.startswith("# Critical Context Capsule\n"))
            self.assertIn(f"## {heading} phase checklist", output.stdout)
            self.assertNotIn("Brief token:", output.stdout)
            self.assertFalse(token_path.exists())

        first_brief, first_token = self.report_brief_token(project, task_id, env)
        second_brief, second_token = self.report_brief_token(project, task_id, env)
        self.assertTrue(first_brief.stdout.startswith("# Critical Context Capsule\n"))
        self.assertIn("## Report phase checklist", second_brief.stdout)
        self.assertNotEqual(first_token, second_token)
        report = runtime / "work" / task_id / "attempt-1.report.md"
        report.write_text(self.report_text())

        finish = ["task", "finish", task_id, "--status", "needs_review"]
        for token in (None, "foreign-token", first_token):
            command = finish + (["--brief", token] if token else [])
            rejected = self.baton(project, *command, env=env)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("report-phase brief token is required", rejected.stderr)

        self.baton(project, *finish, "--brief", second_token, env=env, check=True)
        self.assertFalse(token_path.exists())
        result = runtime / "work" / task_id / "attempt-1.result.json"
        result.unlink()
        replay = self.baton(
            project, *finish, "--brief", second_token, env=env,
        )
        self.assertNotEqual(replay.returncode, 0)
        self.assertIn("report-phase brief token is required", replay.stderr)

    def test_phase_brief_receipts_are_bounded_and_malformed_files_are_replaced(self):
        project = self.make_project()
        task_id = self.create_task(project, "brief receipts", ["receipts/**"])
        env = self.lease_task(project, task_id, "receipt-lease")
        receipt_path = (
            project / ".baton" / "work" / task_id
            / "attempt-1.briefs.json"
        )
        receipt_path.write_text('{"phases": ["malformed"], "token": "must-disappear"}\n')

        self.baton(
            project, "task", "brief", task_id, "--phase", "edit",
            env=env, check=True,
        )
        first_size = receipt_path.stat().st_size
        first = json.loads(receipt_path.read_text())
        self.assertEqual(
            set(first), {"task_id", "attempt", "lease", "capsule_digest", "phases"},
        )
        self.assertEqual(first["task_id"], task_id)
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(first["lease"], "receipt-lease")
        self.assertRegex(first["capsule_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(set(first["phases"]), {"edit"})
        self.assertEqual(first["phases"]["edit"]["count"], 1)
        self.assertNotIn("token", receipt_path.read_text())

        self.baton(
            project, "task", "brief", task_id, "--phase", "edit",
            env=env, check=True,
        )
        second = json.loads(receipt_path.read_text())
        self.assertEqual(receipt_path.stat().st_size, first_size)
        self.assertEqual(second["phases"]["edit"]["count"], 2)
        self.assertEqual(
            second["phases"]["edit"]["first_at"],
            first["phases"]["edit"]["first_at"],
        )

    def test_oversized_integer_phase_receipt_is_replaced(self):
        project = self.make_project()
        task_id = self.create_task(project, "oversized receipt", ["receipts/**"])
        env = self.lease_task(project, task_id, "oversized-receipt-lease")
        work = project / ".baton" / "work" / task_id
        receipt_path = work / "attempt-1.briefs.json"
        digest = (work / "attempt-1.brief.md").read_text().splitlines()[0].removeprefix(
            "Content digest: ",
        )
        receipt_path.write_text(
            '{"task_id":' + json.dumps(task_id)
            + ',"attempt":1,"lease":"oversized-receipt-lease","capsule_digest":'
            + json.dumps(digest)
            + ',"phases":{"edit":{"first_at":"now","last_at":"now","count":'
            + "9" * 5000 + "}}}\n"
        )

        self.baton(
            project, "task", "brief", task_id, "--phase", "edit",
            env=env, check=True,
        )
        replaced = json.loads(receipt_path.read_text())
        self.assertEqual(set(replaced["phases"]), {"edit"})
        self.assertEqual(replaced["phases"]["edit"]["count"], 1)

    def test_phase_sequence_gate_enforces_order_and_edit_invalidates_report_token(self):
        project = self.make_project()
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text().replace(
            "phase_sequence_requires_briefs = false",
            "phase_sequence_requires_briefs = true",
        ))
        task_id = self.create_task(project, "phase sequence", ["sequence/**"])
        env = self.lease_task(project, task_id, "sequence-lease")

        verify = self.baton(
            project, "task", "brief", task_id, "--phase", "verify", env=env,
        )
        self.assertEqual(
            verify.stderr,
            f"error: phase sequence requires an edit brief; run `.baton/baton task brief "
            f"{task_id} --phase edit`\n",
        )
        report = self.baton(
            project, "task", "brief", task_id, "--phase", "report", env=env,
        )
        self.assertEqual(report.stderr, verify.stderr)

        self.baton(
            project, "task", "brief", task_id, "--phase", "edit",
            env=env, check=True,
        )
        report = self.baton(
            project, "task", "brief", task_id, "--phase", "report", env=env,
        )
        self.assertEqual(
            report.stderr,
            f"error: phase sequence requires a verify brief; run `.baton/baton task brief "
            f"{task_id} --phase verify`\n",
        )
        self.baton(
            project, "task", "brief", task_id, "--phase", "verify",
            env=env, check=True,
        )
        _brief, stale_token = self.report_brief_token(project, task_id, env)
        token_path = (
            project / ".baton" / "work" / task_id
            / "finish-brief-token.json"
        )
        self.assertTrue(token_path.exists())
        self.baton(
            project, "task", "brief", task_id, "--phase", "edit",
            env=env, check=True,
        )
        self.assertFalse(token_path.exists())
        stale = self.baton(
            project, "task", "finish", task_id, "--status", "failed",
            "--brief", stale_token, env=env,
        )
        self.assertIn("fresh report-phase brief token is required", stale.stderr)
        _brief, fresh_token = self.report_brief_token(project, task_id, env)
        self.baton(
            project, "task", "finish", task_id, "--status", "failed",
            "--brief", fresh_token, env=env, check=True,
        )

    def test_phase_sequence_gate_defaults_off_and_never_blocks_briefs(self):
        project = self.make_project()
        task_id = self.create_task(project, "phase sequence off", ["sequence-off/**"])
        env = self.lease_task(project, task_id, "sequence-off-lease")
        self.report_brief_token(project, task_id, env)
        self.baton(
            project, "task", "brief", task_id, "--phase", "verify",
            env=env, check=True,
        )
        receipt_path = (
            project / ".baton" / "work" / task_id
            / "attempt-1.briefs.json"
        )
        self.assertEqual(
            set(json.loads(receipt_path.read_text())["phases"]), {"report", "verify"},
        )

    def test_finish_gate_can_be_disabled(self):
        project = self.make_project()
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text().replace(
            "finish_requires_brief = true", "finish_requires_brief = false",
        ))
        task_id = self.create_task(project, "gate off", ["off/**"])
        env = self.lease_task(project, task_id, "gate-off-lease")
        report = (
            project / ".baton" / "work" / task_id
            / "attempt-1.report.md"
        )
        report.write_text(self.report_text())
        self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            env=env, check=True,
        )

    def test_report_missing_heading_preserves_token_and_same_token_refinishes(self):
        project, task_id, env, report, token = self.prepare_finish("missing-heading")
        report.write_text(self.report_text().replace(
            "\n## Decisions and risks\n- none\n", "\n",
        ))
        work = report.parent
        token_path = work / "finish-brief-token.json"
        result_path = work / "attempt-1.result.json"
        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state_before = state_path.read_bytes()
        token_before = token_path.read_bytes()
        command = [
            "task", "finish", task_id, "--status", "needs_review",
            "--brief", token,
        ]

        rejected = self.baton(project, *command, env=env)
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(
            rejected.stderr,
            "error: report rejected: missing required report section "
            "`## Decisions and risks`; fix the report to match the worker.md template, "
            "then rerun `task finish` with the same `--brief` token\n",
        )
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(token_path.read_bytes(), token_before)
        self.assertFalse(result_path.exists())

        report.write_text(self.report_text())
        self.baton(project, *command, env=env, check=True)
        self.assertFalse(token_path.exists())
        self.assertEqual(json.loads(result_path.read_text())["status"], "needs_review")

    def test_report_empty_verification_body_is_rejected(self):
        project, task_id, env, report, token = self.prepare_finish("empty-verification")
        report.write_text(self.report_text().replace("- test verification", ""))
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("report section `## Verification` has an empty body", rejected.stderr)
        self.assertIn("same `--brief` token", rejected.stderr)

    def test_report_empty_fenced_core_sections_are_rejected(self):
        project, task_id, env, report, token = self.prepare_finish("empty-fences")
        report.write_text(
            "# report\n\n## Result\nneeds_review\n\n## Changes\n```\n```\n\n"
            "## Verification\n~~~\n~~~\n\n## Decisions and risks\n- none\n"
        )
        command = [
            "task", "finish", task_id, "--status", "needs_review",
            "--brief", token,
        ]
        rejected = self.baton(project, *command, env=env)
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("report section `## Changes` has an empty body", rejected.stderr)
        self.assertIn("report section `## Verification` has an empty body", rejected.stderr)
        self.assertFalse((report.parent / "attempt-1.result.json").exists())
        self.assertTrue((report.parent / "finish-brief-token.json").exists())

        report.write_text(self.report_text())
        self.baton(project, *command, env=env, check=True)

    def test_report_result_must_match_submitted_status(self):
        project, task_id, env, report, token = self.prepare_finish("result-mismatch")
        report.write_text(self.report_text(status="failed"))
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn(
            "report section `## Result` starts with 'failed', not submitted status "
            "'needs_review'",
            rejected.stderr,
        )

    def test_report_heading_inside_fence_does_not_count(self):
        project, task_id, env, report, token = self.prepare_finish("fenced-heading")
        report.write_text(
            "# task report\n\n## Result\nneeds_review\n\n## Changes\n- changes\n\n"
            "```markdown\n## Verification\n- fake verification\n```\n\n"
            "## Decisions and risks\n- none\n"
        )
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("missing required report section `## Verification`", rejected.stderr)

    def test_report_heading_inside_three_space_indented_fence_does_not_count(self):
        project, task_id, env, report, token = self.prepare_finish("indented-fence")
        report.write_text(
            "# task report\n\n## Result\nneeds_review\n\n## Changes\n- changes\n\n"
            "   ```\n## Verification\n- fake verification\n   ````\n\n"
            "## Decisions and risks\n- none\n"
        )
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("missing required report section `## Verification`", rejected.stderr)

    def test_report_fence_closes_only_with_matching_character(self):
        project, task_id, env, report, token = self.prepare_finish("fence-character")
        report.write_text(
            "# task report\n\n## Result\nneeds_review\n\n## Changes\n- changes\n\n"
            "```\n~~~\n## Verification\n- fake verification\n```\n\n"
            "## Decisions and risks\n- none\n"
        )
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("missing required report section `## Verification`", rejected.stderr)
        self.assertNotIn("missing required report section `## Decisions", rejected.stderr)

    def test_report_fence_closes_only_at_opening_length_or_longer(self):
        project, task_id, env, report, token = self.prepare_finish("fence-length")
        report.write_text(
            "# task report\n\n## Result\nneeds_review\n\n## Changes\n- changes\n\n"
            "````\n```\n## Verification\n- fake verification\n````\n\n"
            "## Decisions and risks\n- none\n"
        )
        rejected = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("missing required report section `## Verification`", rejected.stderr)
        self.assertNotIn("missing required report section `## Decisions", rejected.stderr)

    def test_crlf_structured_report_is_accepted(self):
        project, task_id, env, report, token = self.prepare_finish("crlf-report")
        report.write_bytes(self.report_text(newline="\r\n").encode("utf-8"))
        self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env, check=True,
        )

    def test_report_section_gate_off_accepts_free_form_report(self):
        project, task_id, env, report, token = self.prepare_finish("section-gate-off")
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text().replace(
            "report_requires_sections = true", "report_requires_sections = false",
        ))
        report.write_text("free-form review report\n")
        self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", token, env=env, check=True,
        )

    def test_non_review_statuses_skip_report_section_gate(self):
        for status in ("needs_decision", "blocked", "failed"):
            with self.subTest(status=status):
                project, task_id, env, _report, token = self.prepare_finish(
                    "unstructured-" + status.replace("_", "-"),
                )
                self.baton(
                    project, "task", "finish", task_id, "--status", status,
                    "--brief", token, env=env, check=True,
                )

    def test_unreadable_review_reports_reject_without_consuming_token(self):
        for kind in ("missing", "directory", "bad-utf8"):
            with self.subTest(kind=kind):
                project, task_id, env, report, token = self.prepare_finish(
                    "unreadable-" + kind,
                )
                if kind == "directory":
                    report.mkdir()
                    expected = "report file is not a regular file"
                elif kind == "bad-utf8":
                    report.write_bytes(b"\xff\xfe")
                    expected = "report file is not valid UTF-8"
                else:
                    expected = "report file is missing"
                token_path = report.parent / "finish-brief-token.json"
                rejected = self.baton(
                    project, "task", "finish", task_id, "--status", "needs_review",
                    "--brief", token, env=env,
                )
                self.assertEqual(rejected.returncode, 1)
                self.assertIn("report rejected: " + expected, rejected.stderr)
                self.assertTrue(token_path.exists())

    def test_non_boolean_report_section_gate_fails_validate(self):
        project = self.make_project("invalid-report-gate")
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text().replace(
            "report_requires_sections = true", 'report_requires_sections = "yes"',
        ))
        validation = self.baton(project, "validate")
        self.assertEqual(validation.returncode, 1)
        self.assertIn(
            "config: report_requires_sections must be true or false",
            validation.stdout,
        )

    def test_non_boolean_phase_sequence_gate_fails_validate(self):
        project = self.make_project("invalid-phase-sequence-gate")
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text().replace(
            "phase_sequence_requires_briefs = false",
            'phase_sequence_requires_briefs = "yes"',
        ))
        validation = self.baton(project, "validate")
        self.assertEqual(validation.returncode, 1)
        self.assertIn(
            "config: phase_sequence_requires_briefs must be true or false",
            validation.stdout,
        )

    def test_return_then_retry_invalidates_report_brief_token(self):
        project = self.make_project()
        task_id = self.create_task(project, "retry brief", ["retry/**"])
        first_env = self.lease_task(project, task_id, "first-lease")
        _brief, old_token = self.report_brief_token(project, task_id, first_env)

        runtime = project / ".baton"
        state_path = runtime / "tasks" / f"{task_id}.json"
        task = json.loads(state_path.read_text())
        task["status"] = "needs_review"
        task.pop("runner")
        state_path.write_text(json.dumps(task))
        self.baton(
            project, "task", "return", task_id, "--reason", "retry token",
            check=True,
        )

        second_env = self.lease_task(project, task_id, "second-lease")
        report = runtime / "work" / task_id / "attempt-2.report.md"
        report.write_text("# retry report\n")
        stale = self.baton(
            project, "task", "finish", task_id, "--status", "needs_review",
            "--brief", old_token, env=second_env,
        )
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("report-phase brief token is required", stale.stderr)

    def test_orchestrator_review_brief_accept_gate_and_worker_denial(self):
        project = self.make_project()
        self.configure(project, self.write_worker(GOOD_WORKER))
        task_id = self.create_task(project, "review gate", ["review/**"])
        self.baton(project, "run", task_id, check=True)

        missing = self.baton(project, "task", "accept", task_id)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("review-phase brief token is required", missing.stderr)
        brief, first_token = self.review_brief_token(project, task_id)
        self.assertTrue(brief.stdout.startswith("# Critical Context Capsule\n"))
        self.assertIn("attempt-1.report.md", brief.stdout)
        self.assertIn("attempt-1.result.json", brief.stdout)
        self.assertIn("attempt-1.diff", brief.stdout)
        self.assertIn(f"review/{task_id}.txt", brief.stdout)
        self.assertIn("Phase briefs: edit=0 verify=0 report=1", brief.stdout)
        for artifact in ("Report", "Result", "Diff"):
            self.assertRegex(brief.stdout, rf"- {artifact}: .* \(sha256:[0-9a-f]{{12}}\)")
        token_record = json.loads((
            project / ".baton" / "work" / task_id
            / "review-brief-token.json"
        ).read_text())
        self.assertEqual(token_record["token"], first_token)
        self.assertEqual(token_record["task_id"], task_id)
        self.assertEqual(token_record["attempt"], 1)
        self.assertEqual(
            set(token_record["evidence"]),
            {"capsule", "report", "result", "diff", "declared", "observed"},
        )
        for name in ("capsule", "report", "result", "diff"):
            self.assertRegex(token_record["evidence"][name], r"^sha256:[0-9a-f]{64}$")
        _replacement, current_token = self.review_brief_token(project, task_id)
        for token in ("wrong", first_token):
            rejected = self.baton(
                project, "task", "accept", task_id, "--brief", token,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("review-phase brief token is required", rejected.stderr)

        worker_env = {
            "BATON_TASK_ID": task_id, "BATON_ATTEMPT": "1", "BATON_LEASE": "worker",
        }
        denied = self.baton(
            project, "orchestrator", "brief", "--phase", "review", task_id,
            env=worker_env,
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

        self.baton(
            project, "task", "accept", task_id, "--brief", current_token, check=True,
        )
        token_path = (
            project / ".baton" / "work" / task_id
            / "review-brief-token.json"
        )
        self.assertFalse(token_path.exists())
        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state["status"] = "needs_review"
        state_path.write_text(json.dumps(state))
        replay = self.baton(
            project, "task", "accept", task_id, "--brief", current_token,
        )
        self.assertNotEqual(replay.returncode, 0)
        self.assertIn("review-phase brief token is required", replay.stderr)

    def test_attempt_diff_summary_uses_observed_paths_and_exact_patch_state(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_diff_stat_probe")
        patch = self.base / "attempt.diff"
        patch.write_bytes(
            b"diff --git a/added.txt b/added.txt\n"
            b"new file mode 100644\nindex 0000000..1111111\n"
            b"--- /dev/null\n+++ b/added.txt\n@@ -0,0 +1,2 @@\n"
            b"+alpha\n++++ b/not-a-file.txt\n"
            b"diff --git a/deleted.txt b/deleted.txt\n"
            b"deleted file mode 100644\nindex 2222222..0000000\n"
            b"--- a/deleted.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n"
            b"-gone one\n-gone two\n"
            b"diff --git a/modified.txt b/modified.txt\n"
            b"index 3333333..4444444 100644\n--- a/modified.txt\n+++ b/modified.txt\n"
            b"@@ -1 +1 @@\n-before\n+after\n"
            b"diff --git a/mode.txt b/mode.txt\nold mode 100644\nnew mode 100755\n"
            b"diff --git a/image.bin b/image.bin\nnew file mode 100644\n"
            b"index 0000000..5555555\nGIT binary patch\nliteral 1\nKcmZQz00IC2\n"
            b"diff --git a/outside.txt b/outside.txt\n"
            b"--- a/outside.txt\n+++ b/outside.txt\n@@ -0,0 +1 @@\n+ignore me\n"
        )
        observed = [
            "modified.txt", "phantom.txt", "mode.txt", "image.bin",
            "deleted.txt", "added.txt",
        ]
        summary = module["attempt_diff_summary"](patch, observed)
        self.assertEqual(summary["added"], 3)
        self.assertEqual(summary["removed"], 3)
        self.assertEqual(summary["files"], [
            {"path": "added.txt", "added": 2, "removed": 0, "label": "add"},
            {"path": "deleted.txt", "added": 0, "removed": 2, "label": "delete"},
            {"path": "image.bin", "added": 0, "removed": 0, "label": "binary"},
            {"path": "mode.txt", "added": 0, "removed": 0, "label": "mode"},
            {"path": "modified.txt", "added": 1, "removed": 1, "label": "modify"},
            {"path": "phantom.txt", "added": 0, "removed": 0, "label": "~"},
        ])
        missing = module["attempt_diff_summary"](
            self.base / "missing.diff", ["still-observed.txt"],
        )
        self.assertEqual(
            missing["files"],
            [{"path": "still-observed.txt", "added": 0, "removed": 0, "label": "~"}],
        )

    def test_review_brief_prior_attempts_and_opt_in_sanitized_log_tail(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        task_id = self.create_task(project, "review context", ["context/**"])
        self.baton(project, "run", task_id, check=True)
        runtime = project / ".baton"
        work = runtime / "work" / task_id
        state_path = runtime / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state["attempt"] = 5
        state_path.write_text(json.dumps(state))
        for suffix in ("brief.md", "report.md", "result.json", "diff"):
            (work / f"attempt-5.{suffix}").write_bytes(
                (work / f"attempt-1.{suffix}").read_bytes()
            )
        for attempt in range(2, 5):
            (work / f"attempt-{attempt}.report.md").write_text(f"report {attempt}\n")
            (work / f"attempt-{attempt}.diff").write_text(f"diff {attempt}\n")

        secret = "do-not-leak-environment-value"
        lines = [f"older-{number}" for number in range(14)] + [
            "\x1b[31mred\x1b[0m",
            "\x1b]0;hidden title\x07visible",
            "controls:\x00\x08clean\tkept",
            f"REVIEW_SECRET={secret} standalone {secret}",
            "{'PASSWORD': 'dict-secret'} Bearer bearer-secret",
            "L" * 300,
            "last-line",
        ]
        (work / "attempt-5.log").write_bytes(
            b"X" * 70000 + b"\n" + "\n".join(lines).encode("utf-8") + b"\n"
        )

        default, _token = self.review_brief_token(project, task_id)
        self.assertIn("Diff stat: no changes", default.stdout)
        self.assertNotIn("Untrusted worker log tail", default.stdout)
        self.assertNotIn("last-line", default.stdout)
        prior = default.stdout.split("Prior attempt artifacts (most recent first):\n", 1)[1]
        prior = prior.split("Review checklist:", 1)[0]
        for attempt in (4, 3, 2):
            self.assertIn(f"attempt-{attempt}.report.md", prior)
            self.assertIn(f"attempt-{attempt}.diff", prior)
        self.assertNotIn("attempt-1.report.md", prior)
        self.assertIn("- +1 older attempt", prior)
        self.assertLess(prior.index("attempt-4.report.md"), prior.index("attempt-3.report.md"))

        included, _token = self.review_brief_token(
            project, task_id, env={"REVIEW_SECRET": secret}, include_log_tail=True,
        )
        block = included.stdout.split("Untrusted worker log tail (opt-in):", 1)[1]
        block = "Untrusted worker log tail (opt-in):" + block.split(
            "Review checklist:", 1,
        )[0].rstrip("\n")
        self.assertLessEqual(len(block), 1500)
        self.assertLessEqual(len(block.splitlines()) - 1, 15)
        self.assertIn("red", block)
        self.assertIn("visible", block)
        self.assertIn("controls:clean\tkept", block)
        self.assertIn("REVIEW_SECRET=[redacted]", block)
        self.assertIn("standalone [redacted]", block)
        self.assertIn("last-line", block)
        self.assertNotIn("hidden title", block)
        self.assertNotIn(secret, block)
        self.assertNotIn("dict-secret", block)
        self.assertNotIn("bearer-secret", block)
        self.assertNotIn("\x1b", block)
        self.assertNotIn("\x00", block)
        self.assertTrue(any(len(line) == 240 for line in block.splitlines()))

        (work / "attempt-5.log").unlink()
        unavailable, _token = self.review_brief_token(
            project, task_id, include_log_tail=True,
        )
        self.assertIn(
            "Untrusted worker log tail (opt-in):\nlog tail unavailable",
            unavailable.stdout,
        )
        rejected = self.baton(
            project, "orchestrator", "brief", "--phase", "start",
            "--include-log-tail",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "--include-log-tail is valid only for the review phase", rejected.stderr,
        )

    def test_sanitize_log_text_redacts_lowercase_and_mixed_case_labels(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_log_sanitizer_probe")
        sanitize = module["sanitize_log_text"]
        self.assertEqual(sanitize("password: hunter2\n"), "password: [redacted]\n")
        labels = (
            "password", "passwd", "pwd", "secret", "token", "key", "api_key",
            "apikey", "auth", "bearer", "credential", "cookie", "session",
        )
        for label in labels:
            mixed_case = label.title()
            for separator in (":", "="):
                with self.subTest(label=mixed_case, separator=separator):
                    self.assertEqual(
                        sanitize(f"{mixed_case}{separator} hunter2\n"),
                        f"{mixed_case}{separator} [redacted]\n",
                    )

    def test_review_token_invalidated_by_return_and_accept_gate_off(self):
        project = self.make_project()
        self.configure(project, self.write_worker(GOOD_WORKER))
        task_id = self.create_task(project, "return review", ["return-review/**"])
        self.baton(project, "run", task_id, check=True)
        _brief, stale_token = self.review_brief_token(project, task_id)
        token_path = (
            project / ".baton" / "work" / task_id
            / "review-brief-token.json"
        )
        self.baton(
            project, "task", "return", task_id, "--reason", "try again", check=True,
        )
        self.assertFalse(token_path.exists())
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        self.baton(project, "run", task_id, check=True)
        invalidated = self.baton(
            project, "task", "accept", task_id, "--brief", stale_token,
        )
        self.assertNotEqual(invalidated.returncode, 0)

        gate_off = self.make_project("gate-off-accept")
        self.configure(gate_off, self.write_worker(GOOD_WORKER))
        config = gate_off / ".baton" / "config.toml"
        config.write_text(config.read_text() + "\n[gates]\naccept_requires_brief = false\n")
        gate_off_id = self.create_task(gate_off, "accept gate off", ["gate-off/**"])
        self.baton(gate_off, "run", gate_off_id, check=True)
        gate_off_report = (
            gate_off / ".baton" / "work" / gate_off_id
            / "attempt-1.report.md"
        )
        gate_off_report.write_text(gate_off_report.read_text() + "changed without brief\n")
        self.baton(gate_off, "task", "accept", gate_off_id, check=True)

    def test_review_evidence_mutations_reject_without_consuming_token(self):
        for artifact in ("report.md", "result.json", "diff"):
            with self.subTest(artifact=artifact):
                project = self.make_project("mutated-" + artifact.replace(".", "-"))
                self.configure(project, self.write_worker(GOOD_WORKER))
                task_id = self.create_task(project, "mutate " + artifact, ["mutate/**"])
                self.baton(project, "run", task_id, check=True)
                _brief, token = self.review_brief_token(project, task_id)
                token_path = (
                    project / ".baton" / "work" / task_id
                    / "review-brief-token.json"
                )
                evidence_path = (
                    token_path.parent / f"attempt-1.{artifact}"
                )
                evidence_path.write_text(evidence_path.read_text() + "\n")

                rejected = self.baton(
                    project, "task", "accept", task_id, "--brief", token,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(
                    "review evidence changed; run a fresh review brief",
                    rejected.stderr,
                )
                self.assertEqual(json.loads(token_path.read_text())["token"], token)
                self.assertEqual(self.state(project, task_id)["status"], "needs_review")

                _fresh, fresh_token = self.review_brief_token(project, task_id)
                self.baton(
                    project, "task", "accept", task_id,
                    "--brief", fresh_token, check=True,
                )

    def test_review_and_accept_reject_structurally_invalid_report_drift(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        task_id = self.create_task(project, "semantic report drift", ["drift/**"])
        self.baton(project, "run", task_id, check=True)
        work = project / ".baton" / "work" / task_id
        report = work / "attempt-1.report.md"
        valid_report = report.read_text()
        token_path = work / "review-brief-token.json"

        report.write_text("# malformed before review\n")
        review = self.baton(
            project, "orchestrator", "brief", "--phase", "review", task_id,
        )
        self.assertEqual(review.returncode, 1)
        self.assertIn("report rejected", review.stderr)
        self.assertFalse(token_path.exists())

        report.write_text(valid_report)
        _brief, stale_token = self.review_brief_token(project, task_id)
        report.write_text("# malformed after review brief\n")
        rejected = self.baton(
            project, "task", "accept", task_id, "--brief", stale_token,
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("report rejected", rejected.stderr)
        self.assertEqual(json.loads(token_path.read_text())["token"], stale_token)
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")

        report.write_text(valid_report)
        _fresh, fresh_token = self.review_brief_token(project, task_id)
        self.baton(
            project, "task", "accept", task_id, "--brief", fresh_token,
            check=True,
        )

    def test_review_manifest_uses_launch_capsule_and_accepts_empty_diff(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        task_id = self.create_task(project, "empty evidence diff", ["empty/**"])
        self.baton(project, "run", task_id, check=True)
        work = project / ".baton" / "work" / task_id
        self.assertEqual((work / "attempt-1.diff").read_text(), "")
        (work / "attempt-1.briefs.json").unlink()
        brief, token = self.review_brief_token(project, task_id)
        self.assertIn("Diff stat: no changes", brief.stdout)
        self.assertIn("Phase briefs: none recorded", brief.stdout)

        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            f"Complete the empty evidence diff task.",
            "Complete the edited specification task.",
        ))
        self.baton(
            project, "task", "accept", task_id, "--brief", token, check=True,
        )

    def test_review_manifest_fresh_compile_accepts_without_stored_attempt_brief(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        task_id = self.create_task(project, "fresh review capsule", ["fresh/**"])
        self.baton(project, "run", task_id, check=True)
        work = project / ".baton" / "work" / task_id
        (work / "attempt-1.brief.md").unlink()

        brief, token = self.review_brief_token(project, task_id)
        self.assertTrue(brief.stdout.startswith("# Critical Context Capsule\n"))
        self.assertTrue((work / "review-brief-token.json").exists())
        self.baton(
            project, "task", "accept", task_id, "--brief", token, check=True,
        )
        self.assertEqual(self.state(project, task_id)["status"], "done")

    def test_review_brief_requires_regular_complete_evidence(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_review_hash_probe")
        digest_file = self.base / "digest.bin"
        digest_file.write_bytes(b"x" * (1024 * 1024 + 17))
        self.assertEqual(
            module["sha256_regular_file"](digest_file),
            hashlib.sha256(digest_file.read_bytes()).hexdigest(),
        )
        with self.assertRaises(OSError):
            module["sha256_regular_file"](self.base)
        digest_link = self.base / "digest-link"
        digest_link.symlink_to(digest_file)
        with self.assertRaises(OSError):
            module["sha256_regular_file"](digest_link)

        for missing in ("report.md", "result.json", "diff"):
            with self.subTest(missing=missing):
                project = self.make_project("missing-" + missing.replace(".", "-"))
                self.configure(project, self.write_worker(GOOD_WORKER))
                task_id = self.create_task(project, "missing " + missing, ["missing/**"])
                self.baton(project, "run", task_id, check=True)
                work = project / ".baton" / "work" / task_id
                (work / f"attempt-1.{missing}").unlink()
                rejected = self.baton(
                    project, "orchestrator", "brief", "--phase", "review", task_id,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertFalse((work / "review-brief-token.json").exists())

        project = self.make_project("symlink-report")
        self.configure(project, self.write_worker(GOOD_WORKER))
        task_id = self.create_task(project, "symlink report", ["symlink/**"])
        self.baton(project, "run", task_id, check=True)
        work = project / ".baton" / "work" / task_id
        report = work / "attempt-1.report.md"
        external = self.base / "external-report.md"
        external.write_text(report.read_text())
        report.unlink()
        report.symlink_to(external)
        rejected = self.baton(
            project, "orchestrator", "brief", "--phase", "review", task_id,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("symlink", rejected.stderr.lower())
        self.assertFalse((work / "review-brief-token.json").exists())

    def test_review_brief_survives_fresh_capsule_compile_failure(self):
        project = self.make_project()
        self.configure(project, self.write_worker(GOOD_WORKER))
        self.write_memory(project, [("M001", "W", "Launch-only fact", "Full body")])
        task_id = self.create_task(project, "stored capsule fallback", ["fallback/**"])
        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            "List the paths and facts the worker needs. Reference memory ids when useful.",
            "Memory: M001.",
        ))
        self.baton(project, "run", task_id, check=True)
        self.write_memory(project, [])

        brief, token = self.review_brief_token(project, task_id)
        self.assertIn("Launch-only fact", brief.stdout)
        self.assertEqual(brief.stdout.count("WARNING:"), 1)
        self.assertIn("referenced memory id M001 is missing", brief.stdout)
        self.assertLess(len(next(
            line for line in brief.stdout.splitlines() if line.startswith("WARNING:")
        )), 600)
        self.baton(
            project, "task", "accept", task_id, "--brief", token, check=True,
        )

        no_launch = self.make_project("no-launch-capsule")
        task_id = self.create_task(no_launch, "no launch compile", ["none/**"])
        runtime = no_launch / ".baton"
        state_path = runtime / "tasks" / f"{task_id}.json"
        task = json.loads(state_path.read_text())
        task["status"] = "needs_review"
        state_path.write_text(json.dumps(task))
        work = runtime / "work" / task_id
        work.mkdir(parents=True)
        (work / "attempt-1.report.md").write_text("report\n")
        (work / "attempt-1.result.json").write_text(json.dumps({"changed_paths": []}))
        (work / "attempt-1.diff").write_text("")
        spec = runtime / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            f"Complete the no launch compile task.",
            "Replace this line with one clear outcome.",
        ))
        failed = self.baton(
            no_launch, "orchestrator", "brief", "--phase", "review", task_id,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("template placeholder", failed.stderr)
        self.assertFalse((work / "review-brief-token.json").exists())

    def test_start_brief_never_asks_about_harness_memory_or_fresh_sessions(self):
        project = self.make_project()
        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        ).stdout
        self.assertNotIn("Harness memory:", started)
        self.assertNotIn("fresh harness session", started)
        self.assertNotIn("use your existing harness memory", started)

    def test_compaction_reinjection_uses_the_same_route_validity_rule(self):
        project = self.make_project()
        runtime = project / ".baton"
        compact = subprocess.run(
            [runtime / "baton", "hook-event", "session-start"],
            cwd=project, input='{"source":"compact"}', text=True,
            capture_output=True,
        )
        self.assertEqual(compact.returncode, 0)
        self.assertIn("Which model and reasoning level should Baton use", compact.stdout)
        self.assertNotIn("Harness memory:", compact.stdout)

        (runtime / "config.toml").write_text("".join(
            f'[tiers.{name}]\ncommand = "/usr/bin/true {{prompt_file}}"\n'
            for name in ("hard", "medium", "easy")
        ))
        compact = subprocess.run(
            [runtime / "baton", "hook-event", "session-start"],
            cwd=project, input='{"source":"compact"}', text=True,
            capture_output=True,
        )
        self.assertEqual(compact.returncode, 0)
        self.assertNotIn("Which model and reasoning level should Baton use", compact.stdout)
        self.assertIn("change these settings at any time", compact.stdout)

    def test_close_brief_counts_worker_launches_across_retries_and_archives(self):
        project = self.make_project()
        runtime = project / ".baton"
        active = [
            {
                "id": "T900-hard", "title": "hard", "status": "done", "tier": "hard",
                "history": [
                    {"event": "launched", "attempt": 1},
                    {"event": "worker_exited", "attempt": 1},
                    {"event": "launched", "attempt": 2},
                    None,
                    {"event": 7},
                ],
            },
            {
                "id": "T901-easy", "title": "easy", "status": "queued", "tier": "easy",
                "history": [{"event": "launched"}] * 3,
            },
            {
                "id": "T902-custom", "title": "custom", "status": "done",
                "tier": "private-route", "history": [{"event": "launched"}],
            },
            {
                "id": "T905-malformed", "title": "malformed", "status": "done",
                "tier": "hard", "history": "launched",
            },
            {
                "id": "T906-unhashable", "title": "unhashable", "status": "done",
                "tier": [], "history": [{"event": "launched"}],
            },
        ]
        archived = [
            {
                "id": "T903-medium", "title": "medium", "status": "done",
                "tier": "medium", "history": [{"event": "launched"}],
            },
            {
                "id": "T904-default", "title": "default", "status": "done",
                "tier": "default", "history": [{"event": "launched"}],
            },
        ]
        expected = (
            "I used 9 workers for this Baton runtime so far: 2 for hard tasks, "
            "1 for a medium task, 3 for easy tasks, and 3 for other levels."
        )
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_worker_count_probe")
        self.assertEqual(
            module["worker_usage_sentence"]([]),
            "I used 0 workers for this Baton runtime so far: 0 for hard tasks, "
            "0 for medium tasks, and 0 for easy tasks.",
        )
        self.assertEqual(
            module["worker_usage_sentence"]([{
                "tier": "hard", "history": [{"event": "launched"}],
            }]),
            "I used 1 worker for this Baton runtime so far: 1 for a hard task, "
            "0 for medium tasks, and 0 for easy tasks.",
        )
        self.assertEqual(
            module["worker_usage_sentence"]([{
                "tier": [], "history": [{"event": "launched"}],
            }]),
            "I used 1 worker for this Baton runtime so far: 0 for hard tasks, "
            "0 for medium tasks, 0 for easy tasks, and 1 for other level.",
        )
        self.assertEqual(module["worker_usage_sentence"](active + archived), expected)
        self.assertEqual(
            module["worker_usage_sentence"]([], for_request=True),
            "I used 0 workers for this request: 0 on hard, 0 on medium, and 0 on easy.",
        )
        self.assertEqual(
            module["worker_usage_sentence"]([{
                "tier": [], "history": [{"event": "launched"}],
            }], for_request=True),
            "I used 1 worker for this request: 0 on hard, 0 on medium, "
            "0 on easy, and 1 on other levels.",
        )
        emitted = []
        module["orchestrator_close_brief"].__globals__["say"] = emitted.append
        module["orchestrator_close_brief"](
            runtime, active, archived, "next goal", [], [], False,
        )
        self.assertIn(expected, emitted)

        for task in active:
            (runtime / "tasks" / (task["id"] + ".json")).write_text(json.dumps(task))
        for task in archived:
            (runtime / "archive" / (task["id"] + ".json")).write_text(json.dumps(task))
        closed = self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "next goal", check=True,
        )
        self.assertIn(expected, closed.stdout)

    def test_orchestrator_phase_handoff_and_next_action_capsules(self):
        project = self.make_project()
        self.configure(project, self.write_worker(GOOD_WORKER))
        task_id = self.create_task(project, "phase output", ["phase/**"])
        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        self.assertIn("Worker routing:", started.stdout)
        self.assertIn("Which model and reasoning level should Baton use", started.stdout)
        self.assertNotIn("Harness memory:", started.stdout)
        plan = self.baton(
            project, "orchestrator", "brief", "--phase", "plan", check=True,
        )
        self.assertIn("Task-spec quality checklist:", plan.stdout)
        self.assertIn(f"{task_id} [queued]", plan.stdout)
        run_brief = self.baton(
            project, "orchestrator", "brief", "--phase", "run", check=True,
        )
        self.assertIn(f"Would run: {task_id}", run_brief.stdout)

        status = self.baton(project, "status", check=True)
        self.assertIn("\nNext actions:\n", status.stdout)
        run = self.baton(project, "run", task_id, check=True)
        self.assertIn("\nNext actions:\n", run.stdout)
        self.assertIn("attempt-1.report.md", run.stdout.rsplit("Next actions:", 1)[1])
        shown = self.baton(project, "task", "show", task_id, check=True)
        self.assertIn("\nNext actions:\n", shown.stdout)

        closed = self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "Finish\n\x1b[31mhandoff\x1b[0m context",
            "--avoid", "Do not\n\x1b[33minherit\x1b[0m old goals",
            "--avoid", "Keep locks unchanged",
            "--avoid", "Preserve same-second dedupe",
            "--avoid", "Avoid placeholder context",
            "--avoid", "\x1b]0;title\x07" + "x" * 201,
            "--note", "Trusted\noperator context",
            "--note", "Trusted operator context",
            "--note", "\x1b[31m" + "n" * 161,
            check=True,
        )
        handoff = project / ".baton" / "orchestrator-handoff.md"
        self.assertTrue(handoff.exists())
        handoff_text = handoff.read_text()
        self.assertIn("consumed_at: (not yet)", handoff_text)
        self.assertIn("goal: Finish handoff context\n", handoff_text)
        self.assertIn(
            "goal: Finish handoff context\n"
            "warning: uncommitted Git-visible changes at close\n"
            "done:\n",
            handoff_text,
        )
        notes_block = handoff_text.split("notes:\n", 1)[1].split("avoid:\n", 1)[0]
        expected_notes = ["Trusted operator context", "n" * 159 + "…"]
        self.assertEqual(
            notes_block, "".join(f"- {note}\n" for note in expected_notes),
        )
        avoid_block = handoff_text.split("avoid:\n", 1)[1]
        expected_avoids = [
            "Do not inherit old goals", "Keep locks unchanged",
            "Preserve same-second dedupe", "Avoid placeholder context",
            "x" * 199 + "…",
        ]
        self.assertEqual(
            avoid_block, "".join(f"- {note}\n" for note in expected_avoids),
        )
        self.assertNotIn("(fill in)", avoid_block)
        self.assertIn(
            "Start a fresh coding-agent session and tell it to read "
            ".baton/orchestrator.md.",
            closed.stdout,
        )
        self.assertNotIn("orchestrator brief --phase start", closed.stdout)
        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        self.assertIn("Current handoff:", started.stdout)
        self.assertIn("goal: Finish handoff context", started.stdout)
        for note in expected_avoids:
            self.assertIn("- " + note, started.stdout)
        for note in expected_notes:
            self.assertIn("- " + note, started.stdout)
        self.assertIn("warning: uncommitted Git-visible changes at close", started.stdout)
        self.assertNotIn("consumed_at: (not yet)", handoff.read_text())

    def test_close_brief_validates_required_and_phase_scoped_context(self):
        project = self.make_project()
        remediation = (
            "error: `--phase close` requires a nonblank goal; "
            "add `--goal TEXT`\n"
        )
        for extra in ([], ["--goal", " \n\t "]):
            with self.subTest(extra=extra):
                rejected = self.baton(
                    project, "orchestrator", "brief", "--phase", "close", *extra,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(rejected.stderr, remediation)

        too_many_args = [
            item
            for number in range(6)
            for item in ("--avoid", f"note {number}")
        ]
        too_many = self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "Continue the work", *too_many_args,
        )
        self.assertNotEqual(too_many.returncode, 0)
        self.assertEqual(
            too_many.stderr,
            "error: at most 5 `--avoid` notes are allowed; consolidate them\n",
        )

        too_many_notes = [
            item
            for number in range(4)
            for item in ("--note", f"context {number}")
        ]
        rejected_notes = self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "Continue the work", *too_many_notes,
        )
        self.assertNotEqual(rejected_notes.returncode, 0)
        self.assertEqual(
            rejected_notes.stderr,
            "error: at most 3 `--note` values are allowed; consolidate them\n",
        )

        for phase in ("start", "plan", "run", "review"):
            for flag, value in (
                    ("--goal", "next"), ("--avoid", "risk"), ("--note", "fact")):
                with self.subTest(phase=phase, flag=flag):
                    rejected = self.baton(
                        project, "orchestrator", "brief", "--phase", phase,
                        flag, value,
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertEqual(
                        rejected.stderr,
                        f"error: `{flag}` is valid only for the close phase\n",
                    )

        closed = self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "g" * 201, "--note", " \n\t ", check=True,
        )
        handoff = project / ".baton" / "orchestrator-handoff.md"
        goal_line = next(
            line for line in handoff.read_text().splitlines() if line.startswith("goal: ")
        )
        self.assertEqual(goal_line, "goal: " + "g" * 199 + "…")
        self.assertIn("avoid:\n- (fill in)\n", handoff.read_text())
        self.assertNotIn("notes:", handoff.read_text())
        self.assertIn(goal_line, closed.stdout)

    def test_handoff_start_and_close_lock_complete_update(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_handoff_lock_probe")
        events = []
        handoff = (
            "# Orchestrator handoff\n"
            "generated_at: 2026-01-01T00:00:00Z\n"
            "consumed_at: (not yet)\n"
            "goal: test\n"
            "done:\n- (none)\n"
        )

        class LockProbe:
            def __init__(self, path):
                self.name = Path(path).name

            def __enter__(self):
                events.append(("enter", self.name))

            def __exit__(self, *_args):
                events.append(("exit", self.name))

        globals_ = module["orchestrator_start_brief"].__globals__
        globals_["file_lock"] = LockProbe
        globals_["read_handoff"] = lambda _baton_dir: events.append("read") or handoff
        globals_["atomic_write"] = lambda *_args: events.append("write")
        globals_["load_archived_tasks"] = lambda _baton_dir: events.append("archive") or []
        globals_["task_lock"] = lambda *_args: self.fail(
            "task lock nested in handoff lock"
        )
        globals_["now"] = lambda: "2026-01-01T00:00:01Z"
        globals_["say"] = lambda *_args: None
        globals_["load_config"] = lambda _baton_dir: {}
        globals_["project_root"] = lambda _baton_dir: "/project"
        globals_["worker_routing_lines"] = lambda _config, _root: ["Worker routing:"]

        module["orchestrator_start_brief"](
            "/baton", [], consume_handoff=True,
        )
        self.assertEqual(events, [
            ("enter", "orchestrator-handoff.lock"), "read", "write",
            ("exit", "orchestrator-handoff.lock"),
        ])
        events.clear()
        archived = globals_["load_archived_tasks"]("/baton")
        module["orchestrator_close_brief"](
            "/baton", [], archived, "next goal", [], [], False,
        )
        self.assertEqual(events, [
            "archive", ("enter", "orchestrator-handoff.lock"), "read", "write",
            ("exit", "orchestrator-handoff.lock"),
        ])

    def test_handoff_done_outcomes_are_matched_flattened_and_line_bounded(self):
        project = self.make_project()
        runtime = project / ".baton"
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_outcome_probe")
        accepted_at = "2026-01-01T00:00:00Z"
        tasks = [
            {
                "id": "T900-long-outcome", "title": "t" * 400, "status": "done",
                "history": [
                    {"event": "accepted", "at": accepted_at,
                     "note": " Shipped\n" + "o" * 140},
                    {"event": "archived", "at": accepted_at,
                     "note": "must not replace the accepted outcome"},
                ],
            },
            {
                "id": "T901-blank-outcome", "title": "blank note", "status": "done",
                "history": [
                    {"event": "accepted", "at": accepted_at, "note": " \n\t "},
                    {"event": "worker_exited", "at": accepted_at,
                     "note": "must not become an outcome"},
                ],
            },
        ]
        module["orchestrator_close_brief"](
            runtime, tasks, [], "next goal", [], [], False,
        )
        content = (runtime / "orchestrator-handoff.md").read_text()
        done_lines = content.split("done:\n", 1)[1].split(
            "decisions:\n", 1,
        )[0].splitlines()
        long_line = next(line[2:] for line in done_lines if "T900-long-outcome" in line)
        blank_line = next(line[2:] for line in done_lines if "T901-blank-outcome" in line)
        self.assertLessEqual(len(long_line), 240)
        self.assertTrue(long_line.startswith("T900-long-outcome: "))
        self.assertTrue(long_line.endswith(" — outcome: Shipped " + "o" * 111 + "…"))
        self.assertNotIn(" — outcome:", blank_line)
        self.assertNotIn("must not", content)

    def test_close_working_tree_warning_is_clean_dirty_or_unavailable(self):
        clean = self.make_project("clean-warning")
        self.git(clean, "add", ".gitignore")
        self.git(clean, "commit", "-qm", "ignore runtime")
        self.baton(
            clean, "orchestrator", "brief", "--phase", "close",
            "--goal", "clean close", check=True,
        )
        clean_handoff = (
            clean / ".baton" / "orchestrator-handoff.md"
        ).read_text()
        self.assertNotIn("warning:", clean_handoff)
        self.assertIn("goal: clean close\ndone:\n", clean_handoff)

        dirty = self.make_project("dirty-warning")
        leaked_path = "private-path-must-not-leak.txt"
        (dirty / leaked_path).write_text("dirty\n")
        self.baton(
            dirty, "orchestrator", "brief", "--phase", "close",
            "--goal", "dirty close", check=True,
        )
        dirty_handoff = (
            dirty / ".baton" / "orchestrator-handoff.md"
        ).read_text()
        self.assertIn(
            "goal: dirty close\n"
            "warning: uncommitted Git-visible changes at close\n"
            "done:\n",
            dirty_handoff,
        )
        self.assertNotIn(leaked_path, dirty_handoff)

        unavailable = self.make_project("unavailable-warning")
        unavailable_result = self.baton(
            unavailable, "orchestrator", "brief", "--phase", "close",
            "--goal", "unavailable close",
            env={"GIT_DIR": unavailable / "missing-git-dir"}, check=True,
        )
        unavailable_handoff = (
            unavailable / ".baton" / "orchestrator-handoff.md"
        ).read_text()
        self.assertIn(
            "goal: unavailable close\n"
            "warning: working-tree check unavailable at close\n"
            "done:\n",
            unavailable_handoff,
        )
        self.assertNotIn("fatal:", unavailable_result.stdout + unavailable_handoff)

    def test_handoff_total_budget_degrades_whole_sections_in_order(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_budget_probe")
        done = [
            (f"T{number:03d}-done", "t" * 240, "o" * 120)
            for number in range(12)
        ]
        decisions = [f"T{number:03d}-decision: " + "d" * 240 for number in range(12)]
        next_ids = [f"next-{number}-" + "n" * 240 for number in range(12)]
        unresolved = [f"unresolved-{number}-" + "u" * 240 for number in range(12)]
        notes = [character * 160 for character in "abc"]
        avoid = [str(number) * 200 for number in range(5)]
        content = module["render_handoff"](
            "2026-01-01T00:00:00Z", "g" * 200, True, done, decisions,
            next_ids, unresolved, notes, avoid,
        )

        def section(name, next_name):
            return [
                line[2:] for line in content.split(name + ":\n", 1)[1].split(
                    next_name + ":\n", 1,
                )[0].splitlines()
            ]

        self.assertLessEqual(len(content), 4000)
        self.assertNotIn("outcome:", content)
        self.assertEqual(section("done", "decisions"), ["+12 more"])
        self.assertEqual(section("decisions", "next"), ["+12 more"])
        for name, next_name in (("next", "unresolved"), ("unresolved", "notes")):
            lines = section(name, next_name)
            marker = next(line for line in lines if line.startswith("+"))
            self.assertEqual(len(lines) - 1 + int(marker[1:].split()[0]), 12)
        for note in notes:
            self.assertIn("- " + note, content)
        self.assertTrue(content.endswith("- " + avoid[-1] + "\n"))

    def test_close_to_start_round_trip_includes_outcome_warning_and_notes(self):
        project = self.make_project()
        runtime = project / ".baton"
        task_id = self.create_task(project, "round trip outcome", ["round/**"])
        state_path = runtime / "tasks" / f"{task_id}.json"
        task = json.loads(state_path.read_text())
        task["status"] = "done"
        task["history"].append({
            "event": "accepted", "at": "2026-01-01T00:00:00Z",
            "note": "Verified round-trip result",
        })
        state_path.write_text(json.dumps(task))
        self.baton(
            project, "orchestrator", "brief", "--phase", "close",
            "--goal", "continue round trip", "--note", "User prefers the safe path",
            check=True,
        )
        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        for expected in (
                f"{task_id}: round trip outcome — outcome: Verified round-trip result",
                "warning: uncommitted Git-visible changes at close",
                "notes:\n- User prefers the safe path",
                "avoid:\n- (fill in)"):
            self.assertIn(expected, started.stdout)

    def test_start_brief_and_hooks_do_not_write_beyond_handoff_consumption(self):
        project = self.make_project()
        runtime = project / ".baton"
        handoff = runtime / "orchestrator-handoff.md"
        handoff.write_text(
            "# Orchestrator handoff\n"
            "generated_at: 2026-01-01T00:00:00Z\n"
            "consumed_at: (not yet)\n"
            "goal: verify read-only onboarding\n"
            "done:\n- (none)\n"
        )
        (runtime / ".locks" / "orchestrator-handoff.lock").touch()

        def snapshot():
            return {
                path.relative_to(runtime).as_posix(): path.read_bytes()
                for path in runtime.rglob("*") if path.is_file()
            }

        before = snapshot()
        started = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        self.assertIn("Worker routing:", started.stdout)
        after_start = snapshot()
        changed = {
            path for path in before if before[path] != after_start.get(path)
        } | (set(after_start) - set(before))
        self.assertEqual(changed, {"orchestrator-handoff.md"})
        self.assertNotIn("consumed_at: (not yet)", handoff.read_text())

        hook_command = [
            runtime / "baton", "hook-event", "session-start",
        ]
        for hook_input in ('{"source":"startup"}', '{"source":"compact"}'):
            hooked = subprocess.run(
                hook_command, cwd=project, input=hook_input, text=True,
                capture_output=True,
            )
            self.assertEqual(hooked.returncode, 0)
            self.assertEqual(hooked.stderr, "")
        self.assertEqual(snapshot(), after_start)

    def test_handoff_same_second_acceptance_is_emitted_once(self):
        project = self.make_project()
        task_id = self.create_task(project, "same second", ["same-second/**"])
        runtime = project / ".baton"
        boundary = "2026-01-01T00:00:00Z"
        handoff_path = runtime / "orchestrator-handoff.md"
        handoff_path.write_text(
            "# Orchestrator handoff\n"
            f"generated_at: {boundary}\n"
            "consumed_at: (not yet)\n"
            "goal: test\n"
            "done:\n- (none)\n"
        )
        task = self.state(project, task_id)
        task["history"].append({
            "event": "accepted", "at": boundary,
            "note": "Reviewer-confirmed result",
        })
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_boundary_probe")
        globals_ = module["orchestrator_close_brief"].__globals__
        globals_["now"] = lambda: boundary
        globals_["say"] = lambda *_args: None

        module["orchestrator_close_brief"](
            runtime, [task], [], "next goal", [], [], False,
        )
        first = handoff_path.read_text().split("done:\n", 1)[1].split(
            "decisions:\n", 1,
        )[0]
        module["orchestrator_close_brief"](
            runtime, [task], [], "next goal", [], [], False,
        )
        second = handoff_path.read_text().split("done:\n", 1)[1].split(
            "decisions:\n", 1,
        )[0]
        self.assertEqual(first.count(task_id) + second.count(task_id), 1)
        self.assertIn(task_id, first)
        self.assertIn(" — outcome: Reviewer-confirmed result", first)
        self.assertNotIn(task_id, second)

    def test_worker_manual_uses_installed_baton_commands(self):
        worker = (ROOT / "framework" / "worker.md").read_text()
        self.assertNotIn("`baton ", worker)
        self.assertNotIn("`task finish ", worker)
        self.assertIn("python3 .baton/baton task brief", worker)
        self.assertIn("python3 .baton/baton task finish", worker)

    def test_claude_code_hook_fragment_is_exactly_two_matcher_free_commands(self):
        project = self.make_project()
        printed = self.baton(project, "hooks", "claude-code", check=True)
        fragment_text = printed.stdout.rsplit("\n", 2)[0]
        fragment = json.loads(fragment_text)
        commands = {
            "SessionStart": (
                '"$CLAUDE_PROJECT_DIR"/.baton/baton '
                "hook-event session-start"
            ),
            "UserPromptSubmit": (
                '"$CLAUDE_PROJECT_DIR"/.baton/baton '
                "hook-event user-prompt-submit"
            ),
        }

        self.assertEqual(list(fragment), ["hooks"])
        self.assertEqual(list(fragment["hooks"]), list(commands))
        for event, command in commands.items():
            entries = fragment["hooks"][event]
            self.assertEqual(len(entries), 1)
            self.assertNotIn("matcher", entries[0])
            self.assertEqual(entries[0], {
                "hooks": [{"type": "command", "command": command}],
            })

    def test_claude_code_hook_setup_prints_creates_merges_and_is_idempotent(self):
        project = self.make_project()
        printed = self.baton(project, "hooks", "claude-code", check=True)
        fragment_text, instruction = printed.stdout.rsplit("\n", 2)[:2]
        fragment = json.loads(fragment_text)
        self.assertEqual(set(fragment["hooks"]), {"SessionStart", "UserPromptSubmit"})
        self.assertIn(".baton/baton hook-event", printed.stdout)
        self.assertIn("Merge this fragment into .claude/settings.json", instruction)
        for event in ("SessionStart", "UserPromptSubmit"):
            self.assertNotIn("matcher", fragment["hooks"][event][0])

        self.baton(project, "hooks", "claude-code", "--write", check=True)
        created_path = project / ".claude" / "settings.json"
        self.assertEqual(json.loads(created_path.read_text()), fragment)

        merged_project = self.make_project("hooks-merge")
        settings_path = merged_project / ".claude" / "settings.json"
        settings_path.parent.mkdir()
        unrelated = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "existing-pre-tool"}],
        }
        existing_session = {
            "hooks": [{"type": "command", "command": "existing-session"}],
        }
        settings_path.write_text(json.dumps({
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "PreToolUse": [unrelated],
                "SessionStart": [existing_session],
            },
        }))
        for _ in range(2):
            self.baton(
                merged_project, "hooks", "claude-code", "--write", check=True,
            )
        merged = json.loads(settings_path.read_text())
        self.assertEqual(merged["permissions"], {"allow": ["Read"]})
        self.assertEqual(merged["hooks"]["PreToolUse"], [unrelated])
        self.assertEqual(merged["hooks"]["SessionStart"][0], existing_session)
        self.assertEqual(len(merged["hooks"]["SessionStart"]), 2)
        self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)

        invalid_project = self.make_project("hooks-invalid")
        invalid_path = invalid_project / ".claude" / "settings.json"
        invalid_path.parent.mkdir()
        invalid_path.write_text("{not valid json\n")
        before = invalid_path.read_text()
        rejected = self.baton(
            invalid_project, "hooks", "claude-code", "--write",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("cannot parse .claude/settings.json", rejected.stderr)
        self.assertEqual(invalid_path.read_text(), before)

    def test_session_start_hook_marks_compaction_and_caps_reinjected_brief(self):
        project = self.make_project()
        brief = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        ).stdout
        command = [
            project / ".baton" / "baton", "hook-event", "session-start",
        ]

        for hook_input in ("", '{"source":"startup"}', "not json", "[]"):
            with self.subTest(hook_input=hook_input):
                session = subprocess.run(
                    command, cwd=project, input=hook_input, text=True,
                    capture_output=True,
                )
                self.assertEqual(
                    (session.returncode, session.stdout, session.stderr),
                    (0, brief, ""),
                )

        notice = "Baton: context was compacted; state re-injected below."
        compact = subprocess.run(
            command, cwd=project, input='{"source":"compact"}', text=True,
            capture_output=True,
        )
        self.assertEqual(compact.returncode, 0)
        self.assertEqual(compact.stderr, "")
        self.assertEqual(compact.stdout, notice + "\n" + brief)
        self.assertIn("Worker routing:", compact.stdout)

        (project / ".baton" / "orchestrator-handoff.md").write_text(
            "goal: " + "x" * 10000 + "\nlast handoff line\n"
        )
        capped = subprocess.run(
            command, cwd=project, input='{"source":"compact"}', text=True,
            capture_output=True,
        )
        self.assertEqual(capped.returncode, 0)
        self.assertEqual(capped.stderr, "")
        self.assertLessEqual(len(capped.stdout), 9000)
        self.assertTrue(capped.stdout.startswith(notice + "\n"))
        self.assertIn("\n(truncated)\n", capped.stdout)

    def test_claude_code_hook_events_match_brief_emit_json_and_fail_open(self):
        project = self.make_project()
        brief = self.baton(
            project, "orchestrator", "brief", "--phase", "start", check=True,
        )
        session = subprocess.run(
            [project / ".baton" / "baton", "hook-event", "session-start"],
            cwd=project, input="not json", text=True, capture_output=True,
        )
        self.assertEqual(session.returncode, 0)
        self.assertEqual(session.stderr, "")
        self.assertEqual(session.stdout, brief.stdout)
        decision = self.create_task(project, "hook decision")
        decision_path = (
            project / ".baton" / "tasks" / f"{decision}.json"
        )
        decision_task = json.loads(decision_path.read_text())
        question = "May we\n\x1b[31mchange\x1b[0m the interface?"
        decision_task["status"] = "needs_decision"
        decision_task["last_note"] = question
        decision_task["history"].append({
            "event": "worker_exited", "status": "needs_decision", "note": question,
        })
        decision_path.write_text(json.dumps(decision_task))
        prompt = subprocess.run(
            [
                project / ".baton" / "baton", "hook-event",
                "user-prompt-submit",
            ],
            cwd=project, input="{malformed", text=True, capture_output=True,
        )
        self.assertEqual(prompt.returncode, 0)
        self.assertLessEqual(len(prompt.stdout), 9000)
        payload = json.loads(prompt.stdout)
        specific = payload["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        self.assertTrue(specific["additionalContext"].startswith(
            "Baton state:\nNext actions:\n",
        ))
        self.assertIn(
            f"- decide {decision}: worker question: May we change the interface?",
            specific["additionalContext"],
        )

        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_hook_cap_probe")
        capped = module["cap_hook_output"]("first\n" + "x" * 10000 + "\nlast\n")
        self.assertLessEqual(len(capped), 9000)
        self.assertTrue(capped.startswith("first\n"))
        self.assertTrue(capped.endswith("(truncated)\nlast\n"))
        bounded_json = module["claude_user_prompt_output"](
            "Baton state:\n" + "x" * 10000 + "\nlast",
        )
        self.assertLessEqual(len(bounded_json), 9000)
        self.assertIn("(truncated)\nlast", json.loads(bounded_json)[
            "hookSpecificOutput"
        ]["additionalContext"])

        broken_runtime = self.base / "empty-runtime"
        broken_runtime.mkdir()
        for name in ("session-start", "user-prompt-submit"):
            broken = self.baton(
                project, "hook-event", name, env={"BATON_DIR": broken_runtime},
            )
            self.assertEqual((broken.returncode, broken.stdout, broken.stderr), (0, "", ""))
        outside = self.command(
            [SOURCE_BATON, "hook-event", "session-start"], self.base,
        )
        self.assertEqual((outside.returncode, outside.stdout, outside.stderr), (0, "", ""))

        worker_env = {
            "BATON_TASK_ID": "T999-worker", "BATON_ATTEMPT": "1",
            "BATON_LEASE": "worker",
        }
        for command in (
                ("hooks", "claude-code"),
                ("hook-event", "session-start")):
            denied = self.baton(project, *command, env=worker_env)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

    def test_hook_cap_handles_edge_lines_and_preserves_normal_input(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_hook_edges_probe")
        cap = module["cap_hook_output"]
        prompt_output = module["claude_user_prompt_output"]
        normal = "first\nmiddle\nlast\n"
        self.assertEqual(cap(normal), normal)
        self.assertEqual(
            json.loads(prompt_output(normal))["hookSpecificOutput"]["additionalContext"],
            normal,
        )

        for impossible in (
                "x" * 10000 + "\nlast\n",
                "first\n" + "x" * 10000 + "\n"):
            with self.subTest(edge=impossible[:5]):
                self.assertEqual(cap(impossible), "")
                self.assertEqual(prompt_output(impossible), "")

        huge_middle = "first\n" + "x" * 10000 + "\nlast\n"
        capped = cap(huge_middle)
        self.assertLessEqual(len(capped), 9000)
        self.assertTrue(capped.startswith("first\n"))
        self.assertTrue(capped.endswith("(truncated)\nlast\n"))
        encoded = prompt_output(huge_middle)
        self.assertLessEqual(len(encoded), 9000)
        context = json.loads(encoded)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(context.startswith("first\n"))
        self.assertTrue(context.endswith("(truncated)\nlast\n"))

    def test_concurrent_run_claims_task_once(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "once", ["once/**"])
        starts = self.base / "starts"
        env = dict(os.environ, STARTS=str(starts), FINISH_MARKER=str(self.base / "wait"))
        commands = [str(project / ".baton" / "baton"), "run", task_id]
        first = subprocess.Popen(commands, cwd=project, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(commands, cwd=project, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        out1, err1 = first.communicate(timeout=10)
        out2, err2 = second.communicate(timeout=10)
        self.assertIn(first.returncode, (0, 1), out1 + err1)
        self.assertIn(second.returncode, (0, 1), out2 + err2)
        self.assertEqual(starts.read_text().splitlines(), [task_id])
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")

    def test_separate_run_processes_serialize_snapshot_windows(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        one = self.create_task(project, "alpha", ["alpha/**"])
        two = self.create_task(project, "beta", ["beta/**"])
        baton = str(project / ".baton" / "baton")
        env = dict(os.environ, SLEEP_AFTER_FINISH="0.8")
        first = subprocess.Popen(
            [baton, "run", one], cwd=project, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.state(project, one)["status"] == "running":
                break
            time.sleep(0.02)
        else:
            self.fail("first run did not claim its task")
        second = subprocess.Popen(
            [baton, "run", two], cwd=project, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        time.sleep(0.2)
        self.assertIsNone(second.poll())
        self.assertEqual(self.state(project, two)["status"], "queued")
        out1, err1 = first.communicate(timeout=10)
        out2, err2 = second.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, out1 + err1)
        self.assertEqual(second.returncode, 0, out2 + err2)
        for task_id in (one, two):
            state = self.state(project, task_id)
            self.assertEqual(state["status"], "needs_review")
            self.assertNotIn("scope_violations", state)

    def test_invalid_command_fails_before_task_claim(self):
        project = self.make_project()
        task_id = self.create_task(project, "bad command", ["a/**"])
        config = project / ".baton" / "config.toml"
        config.write_text(
            '[commands]\nworker = "true {prompt} embedded{prompt}"\n'
            '[tiers.test]\n'
            '[limits]\nmax_parallel = 1\n'
        )
        self.assertNotEqual(self.baton(project, "validate").returncode, 0)
        result = self.baton(project, "run")
        self.assertNotEqual(result.returncode, 0)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "queued")
        self.assertFalse(any(
            entry.get("event") == "launched" for entry in state["history"]
        ))

    def test_review_result_without_report_fails(self):
        project = self.make_project()
        worker = self.write_worker(RESULT_WITHOUT_REPORT_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "missing report", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "missing_review_report")

    def test_finalization_rejects_report_drift_after_finish(self):
        project = self.make_project()
        worker = self.write_worker(
            NO_CHANGE_WORKER + '\nreport.write_text("# malformed after finish\\n")\n'
        )
        self.configure(project, worker)
        task_id = self.create_task(project, "report drift after finish", ["drift/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "invalid_review_report")

    def test_malformed_result_and_directory_report_are_rejected(self):
        project = self.make_project()
        worker = self.write_worker(MALFORMED_OUTPUT_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "malformed output", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "invalid_worker_output")
        self.assertIsInstance(state["last_note"], str)

    def test_valid_submission_survives_nonzero_exit_with_review_warning(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "submitted before exit", ["src/**"])
        self.baton(project, "run", task_id, env={"EXIT_CODE": "1"}, check=True)

        state = self.state(project, task_id)
        warning = "worker_exit_1_after_submission"
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["warning"], warning)
        worker_exit = state["history"][-1]
        self.assertEqual(worker_exit["event"], "worker_exited")
        self.assertEqual(worker_exit["exit_code"], 1)
        self.assertEqual(worker_exit["warning"], warning)

        status = self.baton(project, "status", check=True)
        self.assertIn(f"WARNING: {warning}", status.stdout)
        brief, token = self.review_brief_token(project, task_id)
        self.assertIn("WARNING: Worker exited with code 1 after submission", brief.stdout)
        self.assertIn(
            f".baton/work/{task_id}/attempt-1.log", brief.stdout,
        )
        self.baton(
            project, "task", "accept", task_id, "--brief", token, check=True,
        )
        self.assertEqual(self.state(project, task_id)["status"], "done")

    def test_nonzero_exit_without_result_keeps_worker_exit_failure(self):
        project = self.make_project()
        self.configure(project, self.write_worker("raise SystemExit(1)\n"))
        task_id = self.create_task(project, "exit without result", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "worker_exit_1")
        self.assertNotIn("warning", state)

    def test_nonzero_exit_with_malformed_result_is_invalid_output(self):
        project = self.make_project()
        worker = self.write_worker(MALFORMED_OUTPUT_WORKER + "\nraise SystemExit(1)\n")
        self.configure(project, worker)
        task_id = self.create_task(project, "malformed before exit", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "invalid_worker_output")
        self.assertNotIn("warning", state)

    def test_timeout_overrides_valid_submission(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker, max_parallel=1, timeout_minutes=0.02)
        task_id = self.create_task(project, "submitted before timeout", ["src/**"])
        self.baton(
            project, "run", task_id, env={"SLEEP_AFTER_FINISH": "10"}, check=True,
        )
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "worker_timeout")
        self.assertNotIn("warning", state)

    def test_nonzero_exit_does_not_override_changed_paths_mismatch(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER.replace(
            "for path in changed:\n",
            "changed.append('src/not-observed.txt')\nfor path in changed:\n",
        ))
        self.configure(project, worker)
        task_id = self.create_task(project, "mismatch before exit", ["src/**"])
        self.baton(project, "run", task_id, env={"EXIT_CODE": "1"}, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "changed_paths_mismatch")
        self.assertNotIn("warning", state)

    def test_non_utf8_result_fails_without_stale_runner(self):
        project = self.make_project()
        worker = self.write_worker(NON_UTF8_RESULT_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "non utf8 output", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "invalid_worker_output")
        self.assertNotIn("runner", state)

    def test_oversized_integer_result_fails_without_stale_runner(self):
        project = self.make_project()
        worker = self.write_worker(OVERSIZED_INTEGER_RESULT_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "oversized integer output", ["src/**"])
        self.baton(project, "run", task_id, check=True)
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "invalid_worker_output")
        self.assertNotIn("runner", state)

    def test_nested_runtime_symlink_is_rejected_without_overwrite(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "symlink artifact", ["src/**"])
        sentinel = self.base / "log-sentinel"
        sentinel.write_text("unchanged\n")
        directory = project / ".baton" / "work" / task_id
        directory.mkdir(parents=True)
        (directory / "attempt-1.log").symlink_to(sentinel)
        result = self.baton(project, "run", task_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "unchanged\n")
        self.assertEqual(self.state(project, task_id)["status"], "queued")

    def test_cross_scope_write_fails_changed_path_attribution(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker, max_parallel=2)
        alpha = self.create_task(project, "alpha", ["alpha/**"])
        beta = self.create_task(project, "beta", ["beta/**"])
        result = self.baton(
            project, "run", alpha, beta,
            env={"WRITE_OUTSIDE": "beta/injected.txt", "WRITE_OUTSIDE_TASK": alpha},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for task_id in (alpha, beta):
            state = self.state(project, task_id)
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["last_note"], "changed_paths_mismatch")

    def test_stale_finalizer_cannot_overwrite_a_new_lease(self):
        project = self.make_project()
        task_id = self.create_task(project, "lease guard", ["src/**"])
        runtime = project / ".baton"
        state_path = runtime / "tasks" / f"{task_id}.json"
        old_task = json.loads(state_path.read_text())
        old_task["status"] = "running"
        old_task["runner"] = {"pid": None, "lease": "old"}
        current = dict(old_task)
        current["attempt"] = 2
        current["runner"] = {"pid": None, "lease": "new"}
        state_path.write_text(json.dumps(current))
        result = runtime / "work" / task_id / "attempt-1.result.json"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({
            "status": "needs_review", "note": "old", "at": "now",
            "lease": "old", "changed_paths": [],
        }))
        (result.parent / "attempt-1.report.md").write_text("# old report\n")
        baton_module = runpy.run_path(str(SOURCE_BATON), run_name="baton_module")
        finalized = baton_module["finalize_task"](
            str(runtime), old_task, {"returncode": 0}, [], [],
            "baseline", "old", True,
        )
        self.assertFalse(finalized)
        after = json.loads(state_path.read_text())
        self.assertEqual(after["attempt"], 2)
        self.assertEqual(after["status"], "running")
        self.assertEqual(after["runner"]["lease"], "new")

    def test_worker_command_does_not_invoke_a_shell(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        command = f'{sys.executable} {worker} "{{prompt}}"'
        config = (
            "[commands]\n"
            f"worker = {json.dumps(command)}\n\n"
            "[tiers.test]\n\n"
            "[limits]\n"
            "max_parallel = 1\n"
            "worker_timeout_minutes = 1\n"
        )
        (project / ".baton" / "config.toml").write_text(config)
        marker = self.base / "injected"
        scope = f"safe/$(touch {marker})/**"
        task_id = self.create_task(project, "literal prompt", [scope])
        self.baton(project, "run", task_id, check=True)
        self.assertFalse(marker.exists())
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")

    def test_task_creation_requires_explicit_difficulty(self):
        project = self.make_project()
        missing = self.baton(project, "task", "create", "--title", "implicit")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("--tier", missing.stderr)

        rejected_default = self.try_create_task(project, "removed route", tier="default")
        self.assertNotEqual(rejected_default.returncode, 0)
        self.assertIn("unknown tier 'default'", rejected_default.stderr)

        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text() + (
            '\n[tiers.explicit]\ncommand = "/usr/bin/true {prompt_file}"\n'
        ))
        task_id = self.create_task(project, "explicit", tier="explicit")
        self.assertEqual(self.state(project, task_id)["tier"], "explicit")

        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state.pop("tier")
        state_path.write_text(json.dumps(state))
        launch = self.baton(project, "run", task_id, "--dry-run")
        self.assertNotEqual(launch.returncode, 0)
        self.assertIn("tier name must be non-blank", launch.stdout + launch.stderr)
        self.assertEqual(self.state(project, task_id)["status"], "queued")

    def test_difficulty_and_worker_label_are_visible_before_and_during_launch(self):
        project = self.make_project()
        worker = self.write_worker(NO_CHANGE_WORKER)
        self.configure(project, worker)
        config = project / ".baton" / "config.toml"
        tier_command = f"{sys.executable} {worker} --api-key do-not-print {{prompt_file}}"
        config.write_text(config.read_text() + (
            "\n[tiers.hard]\n"
            f"command = {json.dumps(tier_command)}\n"
            "\n[tiers.hard.display]\n"
            'model = "GPT 5.6 Sol"\n'
            'harness = "Hermes"\n'
            'effort = "high"\n'
            'engineering_role = "elite senior"\n'
        ))

        created = self.baton(
            project, "task", "create", "--title", "Visible routing",
            "--scope", "routing/**", "--tier", "hard", check=True,
        )
        task_id = created.stdout.split()[1]
        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            "Replace this line with one clear outcome.", "Verify visible routing.",
        ).replace(
            "- Add observable requirements.", "- Routing is visible.",
        ))
        identity = (
            f"{task_id} | title=Visible routing | difficulty=hard | "
            "worker=model=GPT 5.6 Sol; harness=Hermes; effort=high; "
            "engineering_role=elite senior"
        )
        outputs = [
            created.stdout,
            self.baton(project, "task", "list", check=True).stdout,
            self.baton(project, "task", "list", "--json", check=True).stdout,
            self.baton(project, "task", "show", task_id, check=True).stdout,
            self.baton(project, "status", check=True).stdout,
            self.baton(project, "run", task_id, "--dry-run", check=True).stdout,
            self.baton(project, "tiers", check=True).stdout,
        ]
        for output in outputs:
            self.assertIn("difficulty=hard", output)
            self.assertIn("GPT 5.6 Sol", output)
            self.assertNotIn("--api-key", output)
            self.assertNotIn("do-not-print", output)
        for output in outputs[:6]:
            self.assertIn(task_id, output)
        for output in (outputs[0], outputs[1], outputs[2], outputs[3], outputs[4]):
            self.assertIn("Visible routing", output)
        self.assertIn(identity, created.stdout)

        launched = self.baton(project, "run", task_id, check=True)
        self.assertIn(identity, launched.stdout)
        self.assertNotIn("--api-key", launched.stdout)
        self.assertNotIn("do-not-print", launched.stdout)
        self.assertEqual(self.state(project, task_id)["status"], "needs_review")

    def test_launch_prompt_records_effective_difficulty_and_safe_worker_label(self):
        project = self.make_project()
        worker = self.write_worker(NO_CHANGE_WORKER)
        self.configure(project, worker)
        config = project / ".baton" / "config.toml"
        command = f"{sys.executable} {worker} --credential hidden {{prompt_file}}"
        config.write_text(config.read_text() + (
            "\n[tiers.medium]\n"
            f"command = {json.dumps(command)}\n"
            "\n[tiers.medium.display]\n"
            'model = "GPT 5.6 Sol"\n'
            'harness = "Hermes"\n'
            'effort = "medium"\n'
            'engineering_role = "elite senior"\n'
        ))
        task_id = self.create_task(project, "prompt routing", tier="medium")
        self.baton(project, "run", task_id, check=True)

        prompt = (
            project / ".baton" / "work" / task_id / "attempt-1.prompt.md"
        ).read_text()
        self.assertIn("Difficulty: medium", prompt)
        self.assertIn(
            "Worker: model=GPT 5.6 Sol; harness=Hermes; effort=medium; "
            "engineering_role=elite senior",
            prompt,
        )
        self.assertNotIn("--credential", prompt)
        self.assertNotIn("hidden", prompt)

    def test_worker_label_metadata_is_bounded_sanitized_and_has_safe_fallback(self):
        project = self.make_project()
        worker = self.write_worker(NO_CHANGE_WORKER)
        self.configure(project, worker)
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text() + (
            "\n[tiers.safe]\n"
            "\n[tiers.safe.display]\n"
            'model = "api_key=worker-secret"\n'
            'harness = "Hermes"\n'
            'effort = "high"\n'
            'engineering_role = "elite senior"\n'
            'fallback = "GPT 5.6 Terra/high when Claude usage is exhausted"\n'
        ))

        fallback_created = self.baton(
            project, "task", "create", "--title", "fallback label",
            "--tier", "test", check=True,
        )
        self.assertIn("difficulty=test | worker=unlabeled worker", fallback_created.stdout)
        safe_created = self.baton(
            project, "task", "create", "--title", "safe label",
            "--tier", "safe", check=True,
        )
        self.assertIn("model=api_key=[redacted]", safe_created.stdout)
        self.assertIn("engineering_role=elite senior", safe_created.stdout)
        self.assertNotIn("worker-secret", safe_created.stdout)
        self.assertNotIn("--", safe_created.stdout)

        tier_output = self.baton(project, "tiers", check=True).stdout
        safe_routing = next(
            line for line in tier_output.splitlines()
            if line.startswith("Routing: difficulty=safe")
        )
        worker_label = safe_routing.split("worker=", 1)[1]
        self.assertLessEqual(len(worker_label), 240)
        self.assertNotIn("worker-secret", tier_output)

        invalid_values = (
            ('display = "not-a-table"\n', "must be a table"),
            ('[tiers.bad.display]\nmodel = "' + "x" * 81 + '"\n', "exceeds 80"),
            ('[tiers.bad.display]\nharness = "Hermes\\u001b"\n', "control characters"),
            ('[tiers.bad.display]\nfallback = "--api-key hidden"\n', "command flags"),
            ('[tiers.bad.display]\nunknown = "value"\n', "unknown tier display metadata"),
        )
        for index, (display_config, message) in enumerate(invalid_values):
            with self.subTest(message=message):
                invalid = self.make_project(f"invalid-display-{index}")
                self.configure(invalid, worker)
                invalid_config = invalid / ".baton" / "config.toml"
                invalid_config.write_text(invalid_config.read_text() + (
                    "\n[tiers.bad]\n" + display_config
                ))
                validation = self.baton(invalid, "validate")
                tiers = self.baton(invalid, "tiers")
                self.assertNotEqual(validation.returncode, 0)
                self.assertNotEqual(tiers.returncode, 0)
                self.assertIn(message, validation.stdout + validation.stderr)
                self.assertIn(message, tiers.stdout + tiers.stderr)
                self.assertNotIn("hidden", tiers.stdout)

    def test_tier_display_rejects_command_flags_after_punctuation(self):
        worker = self.write_worker(NO_CHANGE_WORKER)
        for index, value in enumerate(("x;--flag", "(--flag)", "x --flag")):
            with self.subTest(value=value):
                project = self.make_project(f"punctuated-display-flag-{index}")
                self.configure(project, worker)
                config = project / ".baton" / "config.toml"
                config.write_text(config.read_text() + (
                    "\n[tiers.audit]\n\n[tiers.audit.display]\n"
                    f"model = {json.dumps(value)}\n"
                ))
                validation = self.baton(project, "validate")
                tiers = self.baton(project, "tiers")
                self.assertEqual(validation.returncode, 1)
                self.assertEqual(tiers.returncode, 1)
                self.assertIn("command flags", validation.stdout)
                self.assertIn("command flags", tiers.stderr)

        valid = self.make_project("hyphenated-display-prose")
        self.configure(valid, worker)
        config = valid / ".baton" / "config.toml"
        config.write_text(config.read_text() + (
            "\n[tiers.audit]\n\n[tiers.audit.display]\n"
            'model = "ordinary hyphenated-prose"\n'
        ))
        self.baton(valid, "validate", check=True)

    def test_tiers_are_strict_at_create_validate_preview_and_launch(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text() + "\n[tiers.premium]\ncapsule_max_chars = 5000\n")

        unknown = self.try_create_task(project, "unknown tier", tier="mystery")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("unknown tier 'mystery'", unknown.stderr)
        self.assertIn("known tiers: premium, test", unknown.stderr)
        blank = self.try_create_task(project, "blank tier", tier="")
        self.assertNotEqual(blank.returncode, 0)
        self.assertIn("tier name must be non-blank", blank.stderr)

        task_id = self.create_task(
            project, "strict premium", ["premium/**"], tier="premium",
        )
        brief = self.baton(
            project, "orchestrator", "brief", "--phase", "run", check=True,
        )
        dry = self.baton(project, "run", "--dry-run", check=True)
        annotation = (
            f"{task_id} | title=strict premium | difficulty=premium | "
            "worker=unlabeled worker"
        )
        self.assertIn("Would run: " + annotation, brief.stdout)
        self.assertIn("would run: " + annotation, dry.stdout)

        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state["tier"] = "removed"
        state_path.write_text(json.dumps(state))
        validation = self.baton(project, "validate")
        preview = self.baton(project, "task", "capsule", task_id)
        launch = self.baton(project, "run", task_id)
        for result in (validation, preview, launch):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown tier 'removed'", result.stdout + result.stderr)
        self.assertEqual(self.state(project, task_id)["status"], "queued")

    def test_per_tier_capsule_budget_controls_preview_validate_and_launch(self):
        roomy = self.make_project("roomy-tier")
        self.configure(
            roomy, self.write_worker(NO_CHANGE_WORKER), capsule_max_chars=100,
        )
        config = roomy / ".baton" / "config.toml"
        config.write_text(config.read_text() + "\n[tiers.roomy]\ncapsule_max_chars = 4000\n")
        roomy_id = self.create_task(roomy, "roomy capsule", ["roomy/**"], tier="roomy")
        preview = self.baton(roomy, "task", "capsule", roomy_id, check=True)
        self.assertIn("of 4000 chars", preview.stdout)
        self.baton(roomy, "validate", check=True)
        self.baton(roomy, "run", roomy_id, check=True)
        self.assertEqual(self.state(roomy, roomy_id)["status"], "needs_review")

        tight = self.make_project("tight-tier")
        self.configure(tight, self.write_worker(NO_CHANGE_WORKER), capsule_max_chars=4000)
        config = tight / ".baton" / "config.toml"
        config.write_text(config.read_text() + "\n[tiers.tight]\ncapsule_max_chars = 100\n")
        tight_id = self.create_task(tight, "tight capsule", ["tight/**"], tier="tight")
        results = (
            self.baton(tight, "task", "capsule", tight_id),
            self.baton(tight, "validate"),
            self.baton(tight, "run", tight_id),
        )
        for result in results:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("capsule_max_chars=100", result.stdout + result.stderr)
        self.assertEqual(self.state(tight, tight_id)["status"], "queued")

    def test_one_wave_uses_each_limits_only_tier_timeout(self):
        project = self.make_project()
        self.configure(
            project, self.write_worker(TIER_TIMEOUT_WORKER),
            max_parallel=2, timeout_minutes=1,
        )
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text() + (
            "\n[tiers.short]\nworker_timeout_minutes = 0.005\n"
            "\n[tiers.long]\nworker_timeout_minutes = 0.1\n"
        ))
        short = self.create_task(project, "short timeout", ["short/**"], tier="short")
        long = self.create_task(project, "long timeout", ["long/**"], tier="long")
        self.baton(project, "run", short, long, check=True)
        self.assertEqual(self.state(project, short)["status"], "failed")
        self.assertEqual(self.state(project, short)["last_note"], "worker_timeout")
        self.assertEqual(self.state(project, long)["status"], "needs_review")

    def test_validate_rejects_non_object_task_state_and_malformed_history(self):
        project = self.make_project("non-object-task-state")
        task_id = self.create_task(project, "non object task state")
        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state_path.write_text("[]\n")
        validation = self.baton(project, "validate")
        self.assertEqual(validation.returncode, 1)
        self.assertIn("PROBLEM: cannot read task state:", validation.stdout)
        self.assertIn("must contain a JSON object", validation.stdout)
        self.assertNotIn("Traceback", validation.stderr)
        for command in (("task", "list"), ("status",), ("stats",)):
            rejected = self.baton(project, *command)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("must contain a JSON object", rejected.stderr)
            self.assertNotIn("Traceback", rejected.stderr)

        malformed_entries = (1, None, [], "entry", {}, {"event": 1, "at": []})
        for index, entry in enumerate(malformed_entries):
            with self.subTest(entry=entry):
                project = self.make_project(f"malformed-history-{index}")
                task_id = self.create_task(project, f"malformed history {index}")
                state_path = project / ".baton" / "tasks" / f"{task_id}.json"
                state = json.loads(state_path.read_text())
                state["history"] = [entry]
                state_path.write_text(json.dumps(state))
                validation = self.baton(project, "validate")
                self.assertEqual(validation.returncode, 1)
                self.assertIn("history entry 0", validation.stdout)
                self.assertNotIn("Traceback", validation.stderr)
                if not isinstance(entry, dict):
                    status = self.baton(project, "status")
                    self.assertEqual(status.returncode, 1)
                    self.assertIn("history entry 0", status.stderr)
                    self.assertNotIn("Traceback", status.stderr)

    def test_validate_rejects_malformed_active_task_field_shapes(self):
        cases = (
            ("id", ["bad"], "task id must look like"),
            ("depends_on", 1, "depends_on must be a list of task ids"),
            ("scope", 1, "scope must be a list"),
        )
        for index, (field, value, message) in enumerate(cases):
            with self.subTest(field=field, value=value):
                project = self.make_project(f"malformed-active-{index}")
                task_id = self.create_task(project, f"malformed active {index}")
                state_path = project / ".baton" / "tasks" / f"{task_id}.json"
                state = json.loads(state_path.read_text())
                state[field] = value
                state_path.write_text(json.dumps(state))
                validation = self.baton(project, "validate")
                self.assertEqual(validation.returncode, 1)
                self.assertIn("PROBLEM:", validation.stdout)
                self.assertIn(message, validation.stdout)
                self.assertNotIn("ok:", validation.stdout)
                self.assertNotIn("Traceback", validation.stdout + validation.stderr)

        project = self.make_project("aggregate-malformed-active")
        task_id = self.create_task(project, "aggregate malformed active")
        state_path = project / ".baton" / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state.update({
            "status": 7,
            "attempt": False,
            "tier": [],
            "title": 1,
            "scope": 1,
            "depends_on": 1,
            "history": "bad",
        })
        state_path.write_text(json.dumps(state))
        validation = self.baton(project, "validate")
        self.assertEqual(validation.returncode, 1)
        for message in (
                "invalid status", "attempt must be a positive integer",
                "tier must be non-empty text", "title must be non-empty text",
                "scope must be a list", "depends_on must be a list of task ids",
                "history must be a list"):
            self.assertIn(message, validation.stdout)
        self.assertNotIn("Traceback", validation.stdout + validation.stderr)

    def test_validate_rejects_malformed_archived_task_field_shapes(self):
        cases = (
            ("scope", 1, "scope must be a list"),
            ("depends_on", 1, "depends_on must be a list of task ids"),
            ("status", 7, "invalid status"),
            ("attempt", False, "attempt must be a positive integer"),
        )
        for index, (field, value, message) in enumerate(cases):
            with self.subTest(field=field, value=value):
                project = self.make_project(f"malformed-archive-{index}")
                archived_id = self.create_task(project, f"archived source {index}")
                state_path = project / ".baton" / "tasks" / f"{archived_id}.json"
                state = json.loads(state_path.read_text())
                state["status"] = "done"
                state_path.write_text(json.dumps(state))
                self.baton(project, "archive", check=True)
                dependent_id = self.create_task(
                    project, f"active dependent {index}", depends_on=[archived_id],
                )
                archive_path = project / ".baton" / "archive" / f"{archived_id}.json"
                archived = json.loads(archive_path.read_text())
                archived[field] = value
                archive_path.write_text(json.dumps(archived))

                validation = self.baton(project, "validate")
                self.assertEqual(validation.returncode, 1)
                self.assertIn("PROBLEM:", validation.stdout)
                self.assertIn(message, validation.stdout)
                self.assertNotIn("ok:", validation.stdout)
                self.assertNotIn("Traceback", validation.stdout + validation.stderr)
                if field == "status":
                    self.assertIn(
                        f"{dependent_id}: dependency {archived_id} has invalid status",
                        validation.stdout,
                    )

    def test_valid_archived_done_and_cancelled_records_validate(self):
        project = self.make_project()
        done_id = self.create_task(project, "valid archived done")
        done_path = project / ".baton" / "tasks" / f"{done_id}.json"
        done = json.loads(done_path.read_text())
        done["status"] = "done"
        done_path.write_text(json.dumps(done))
        cancelled_id = self.create_task(project, "valid archived cancelled")
        self.baton(
            project, "task", "cancel", cancelled_id, "--reason", "not needed",
            check=True,
        )
        self.baton(project, "archive", check=True)
        validation = self.baton(project, "validate")
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        self.assertEqual(validation.stdout, "ok: 0 active task(s)\n")

    def test_validate_reports_every_malformed_unused_tier_setting_and_name(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        config = project / ".baton" / "config.toml"
        config.write_text(config.read_text() + (
            "\n[tiers.broken]\n"
            "command = \"\"\n"
            "worker_timeout_minutes = \"never\"\n"
            "capsule_max_chars = true\n"
            "\n[tiers.\"\"]\ncapsule_max_chars = 100\n"
            "\n[tiers.default]\ncapsule_max_chars = 200\n"
        ))
        validation = self.baton(project, "validate")
        self.assertNotEqual(validation.returncode, 0)
        for message in (
                "tier 'broken': no worker command configured",
                "worker_timeout_minutes must be a finite non-negative number",
                "capsule_max_chars must be a positive integer",
                "tier name must be non-blank",
                "tier name 'default' is reserved"):
            self.assertIn(message, validation.stdout)

    def test_non_finite_global_and_per_tier_timeouts_are_rejected(self):
        message = "worker_timeout_minutes must be a finite non-negative number"
        for value in ("nan", "inf"):
            for location in ("global", "tier"):
                with self.subTest(value=value, location=location):
                    project = self.make_project(f"non-finite-{location}-{value}")
                    self.configure(project, self.write_worker(NO_CHANGE_WORKER))
                    config = project / ".baton" / "config.toml"
                    if location == "global":
                        config.write_text(config.read_text().replace(
                            "worker_timeout_minutes = 1",
                            f"worker_timeout_minutes = {value}",
                        ))
                    else:
                        config.write_text(config.read_text() + (
                            f"\n[tiers.bad]\nworker_timeout_minutes = {value}\n"
                        ))

                    validation = self.baton(project, "validate")
                    self.assertEqual(validation.returncode, 1)
                    self.assertIn(message, validation.stdout)
                    tiers = self.baton(project, "tiers")
                    self.assertEqual(tiers.returncode, 1)
                    self.assertIn(message, tiers.stderr)
                    self.assertNotIn(f"{value} minutes", tiers.stdout)

    def test_tiers_output_is_exact_read_only_redacted_and_worker_denied(self):
        project = self.make_project()
        worker = self.write_worker(NO_CHANGE_WORKER)
        self.configure(project, worker, timeout_minutes=2.5, capsule_max_chars=4000)
        config = project / ".baton" / "config.toml"
        tier_command = f"{sys.executable} {worker} --secret do-not-print {{prompt_file}}"
        config.write_text(config.read_text() + (
            "\n[tiers.alpha]\ncapsule_max_chars = 5000\n"
            "\n[tiers.zeta]\n"
            f"command = {json.dumps(tier_command)}\n"
            "worker_timeout_minutes = 0\n"
        ))
        runtime = project / ".baton"

        def snapshot():
            return {
                path.relative_to(runtime).as_posix(): path.read_bytes()
                for path in runtime.rglob("*") if path.is_file()
            }

        before = snapshot()
        tiers = self.baton(project, "tiers", check=True)
        executable = sys.executable
        tier_blocks = (
            "Tier: alpha\nRouting: difficulty=alpha | worker=unlabeled worker\n"
            f"Executable: {executable}\nCommand source: global\n"
            "Worker timeout: 2.5 minutes\nCapsule budget: 5000 characters\n\n"
            "Tier: test\nRouting: difficulty=test | worker=unlabeled worker\n"
            f"Executable: {executable}\nCommand source: global\n"
            "Worker timeout: 2.5 minutes\nCapsule budget: 4000 characters\n\n"
            "Tier: zeta\nRouting: difficulty=zeta | worker=unlabeled worker\n"
            f"Executable: {executable}\nCommand source: tier\n"
            "Worker timeout: 0 minutes\nCapsule budget: 4000 characters\n"
        )
        expected = tier_blocks + "Conventional levels missing: hard, medium, easy\n"
        self.assertEqual(tiers.stdout, expected)
        self.assertNotIn("--secret", tiers.stdout)
        self.assertNotIn("do-not-print", tiers.stdout)
        self.assertEqual(snapshot(), before)

        config.write_text(config.read_text() + "\n[tiers.hard]\ncapsule_max_chars = 4100\n")
        partial = self.baton(project, "tiers", check=True)
        self.assertTrue(partial.stdout.endswith(
            "Conventional levels missing: medium, easy\n",
        ))
        config.write_text(config.read_text() + (
            "\n[tiers.medium]\ncapsule_max_chars = 4200\n"
            "\n[tiers.easy]\ncapsule_max_chars = 4300\n"
        ))
        complete = self.baton(project, "tiers", check=True)
        self.assertNotIn("Conventional levels missing:", complete.stdout)
        denied = self.baton(
            project, "tiers", env={"BATON_TASK_ID": "T999-worker"},
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

    def test_timeout_kills_worker_process_group(self):
        project = self.make_project()
        worker = self.write_worker(TIMEOUT_WORKER)
        self.configure(project, worker, max_parallel=1, timeout_minutes=0.005)
        task_id = self.create_task(project, "timeout", ["timeout/**"])
        marker = self.base / "late-marker"
        self.baton(project, "run", task_id, env={"LATE_MARKER": marker}, check=True)
        time.sleep(0.8)
        self.assertFalse(marker.exists())
        state = self.state(project, task_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_note"], "worker_timeout")

    def test_interrupt_stops_workers_without_waiting_for_timeout(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signal.Signals(signum).name):
                name = "signal-{}".format(signum)
                project = self.make_project(name)
                worker = self.write_worker(TIMEOUT_WORKER)
                self.configure(project, worker, max_parallel=1, timeout_minutes=0.05)
                task_id = self.create_task(project, "interrupt", ["interrupt/**"])
                marker = self.base / (name + "-late-marker")
                process = subprocess.Popen(
                    [str(project / ".baton" / "baton"), "run", task_id],
                    cwd=project,
                    env=dict(os.environ, LATE_MARKER=str(marker)),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        state = self.state(project, task_id)
                        if (state["status"] == "running"
                                and state.get("runner", {}).get("pid")):
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("worker did not start")
                    started = time.monotonic()
                    process.send_signal(signum)
                    stdout, stderr = process.communicate(timeout=5)
                    elapsed = time.monotonic() - started
                    self.assertEqual(
                        process.returncode, 128 + signum, stdout + stderr,
                    )
                    self.assertLess(elapsed, 2)
                    time.sleep(0.7)
                    self.assertFalse(marker.exists())
                    state = self.state(project, task_id)
                    self.assertEqual(state["status"], "failed")
                    self.assertEqual(
                        state["last_note"], "orchestrator_interrupted",
                    )
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    state = self.state(project, task_id)
                    pid = state.get("runner", {}).get("pid")
                    if pid:
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_sigterm_stops_parallel_groups_with_one_shared_grace_period(self):
        project = self.make_project()
        worker = self.write_worker(TIMEOUT_WORKER)
        self.configure(project, worker, max_parallel=4, timeout_minutes=0.05)
        task_ids = [
            self.create_task(project, f"parallel signal {index}", [f"signal-{index}/**"])
            for index in range(4)
        ]
        marker = self.base / "parallel-late-marker"
        process = subprocess.Popen(
            [str(project / ".baton" / "baton"), "run", *task_ids],
            cwd=project, env=dict(os.environ, LATE_MARKER=str(marker)),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                states = [self.state(project, task_id) for task_id in task_ids]
                if all(state.get("runner", {}).get("pid") for state in states):
                    break
                time.sleep(0.02)
            else:
                self.fail("parallel workers did not start")
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            elapsed = time.monotonic() - started
            self.assertEqual(process.returncode, 128 + signal.SIGTERM, stdout + stderr)
            self.assertLess(elapsed, 1.5)
            time.sleep(0.7)
            self.assertFalse(marker.exists())
            for task_id in task_ids:
                state = self.state(project, task_id)
                self.assertEqual(state["status"], "failed")
                self.assertEqual(state["last_note"], "orchestrator_interrupted")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_archived_done_dependency_remains_satisfied_and_cycles_fail_validation(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        first = self.create_task(project, "first", ["first/**"])
        self.baton(project, "run", check=True)
        self.accept_task(project, first)
        second = self.create_task(project, "second", ["second/**"], [first])
        self.baton(project, "archive", check=True)
        dry = self.baton(project, "run", "--dry-run", check=True)
        self.assertIn(f"would run: {second}", dry.stdout)
        self.assertEqual(self.baton(project, "validate").returncode, 0)

        third = self.create_task(project, "third", ["third/**"])
        self.assertTrue(third.startswith("T003-"), third)
        second_path = project / ".baton" / "tasks" / f"{second}.json"
        third_path = project / ".baton" / "tasks" / f"{third}.json"
        second_state = json.loads(second_path.read_text())
        third_state = json.loads(third_path.read_text())
        second_state["depends_on"] = [third]
        third_state["depends_on"] = [second]
        second_path.write_text(json.dumps(second_state))
        third_path.write_text(json.dumps(third_state))
        validation = self.baton(project, "validate")
        self.assertNotEqual(validation.returncode, 0)
        self.assertIn("dependency cycle", validation.stdout)

    def test_stats_empty_runtime_is_read_only_and_denied_to_workers(self):
        project = self.make_project()
        runtime = project / ".baton"

        def snapshot():
            return {
                path.relative_to(runtime).as_posix(): path.read_bytes()
                for path in runtime.rglob("*") if path.is_file()
            }

        before = snapshot()
        stats = self.baton(project, "stats", check=True)
        self.assertEqual(stats.stdout, "no task data\n")
        self.assertEqual(snapshot(), before)
        denied = self.baton(
            project, "stats",
            env={"BATON_TASK_ID": "T999-worker", "BATON_ATTEMPT": "1",
                 "BATON_LEASE": "worker"},
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

    def test_stats_exact_mixed_outcomes_and_archived_receipt_coverage(self):
        project = self.make_project()
        runtime = project / ".baton"
        task_ids = [
            self.create_task(project, "stats queued", ["queued/**"]),
            self.create_task(project, "stats failed", ["failed/**"]),
            self.create_task(project, "stats blocked", ["blocked/**"]),
            self.create_task(project, "stats archived", ["archived/**"]),
        ]
        state_paths = [runtime / "tasks" / f"{task_id}.json" for task_id in task_ids]
        states = [json.loads(path.read_text()) for path in state_paths]
        states[0]["history"].append({
            "event": "launched", "attempt": 1, "capsule_chars": 20,
        })
        states[1]["status"] = "failed"
        states[1]["attempt"] = 2
        states[1]["last_note"] = "private failure text must not appear"
        states[1]["history"].extend([
            {"event": "launched", "attempt": 1, "capsule_chars": 10},
            {"event": "worker_exited", "status": "failed", "note": "worker_timeout"},
            {"event": "launched", "attempt": 2, "capsule_chars": 30},
            {"event": "worker_exited", "status": "failed",
             "note": "private failure text must not appear"},
        ])
        states[2]["status"] = "blocked"
        states[2]["last_note"] = "scope_violation"
        states[2]["warning"] = "worker_exit_9_after_submission"
        states[2]["history"].extend([
            {"event": "launched", "attempt": 1, "capsule_chars": 40},
            {"event": "worker_exited", "status": "blocked", "note": "scope_violation",
             "warning": "worker_exit_9_after_submission"},
        ])
        states[3]["status"] = "done"
        states[3]["history"].append({
            "event": "launched", "attempt": 1, "capsule_chars": 50,
        })
        for path, state in zip(state_paths, states):
            path.write_text(json.dumps(state))

        digest = "sha256:" + "a" * 64

        def write_receipt(task_id, attempt, phases):
            work = runtime / "work" / task_id
            work.mkdir(parents=True, exist_ok=True)
            record = {
                "task_id": task_id,
                "attempt": attempt,
                "lease": f"lease-{task_id}-{attempt}",
                "capsule_digest": digest,
                "phases": {
                    phase: {"first_at": "2026-01-01T00:00:00Z",
                            "last_at": "2026-01-01T00:00:00Z", "count": 1}
                    for phase in phases
                },
            }
            (work / f"attempt-{attempt}.briefs.json").write_text(json.dumps(record))

        write_receipt(task_ids[0], 1, ("edit", "report"))
        write_receipt(task_ids[1], 1, ("edit", "verify", "report"))
        write_receipt(task_ids[1], 2, ("edit",))
        write_receipt(task_ids[3], 1, ("report",))
        self.baton(project, "archive", check=True)
        archived_receipt = (
            runtime / "archive" / f"{task_ids[3]}.work" / "attempt-1.briefs.json"
        )
        self.assertTrue(archived_receipt.exists())

        stats = self.baton(project, "stats", check=True)
        self.assertEqual(
            stats.stdout,
            "Status counts:\n"
            "- blocked=1\n"
            "- done=1\n"
            "- failed=1\n"
            "- queued=1\n"
            "Attempts histogram:\n"
            "- 1=3\n"
            "- 2=1\n"
            "Failure/blocked reason codes:\n"
            "- other=1\n"
            "- scope_violation=1\n"
            "- worker_timeout=1\n"
            "Capsule chars:\n"
            "- min=10 median=30 max=50\n"
            "Phase brief coverage (command-use evidence, not proof of attention):\n"
            "- edit=3/5\n"
            "- verify=1/5\n"
            "- report=3/5\n"
            "Post-submission warnings: 1\n",
        )
        self.assertNotIn("private failure text", stats.stdout)

    def test_stats_request_worker_count_filters_active_and_archived_tasks(self):
        project = self.make_project()
        runtime = project / ".baton"
        hard, medium, easy, other = [
            self.create_task(project, title, [f"{title}/**"])
            for title in ("hard", "medium", "easy", "other")
        ]

        medium_path = runtime / "tasks" / f"{medium}.json"
        medium_state = json.loads(medium_path.read_text())
        medium_state["status"] = "done"
        medium_state["tier"] = "medium"
        medium_state["history"] = [{"event": "launched", "attempt": 1}]
        medium_path.write_text(json.dumps(medium_state))
        self.baton(project, "archive", check=True)

        for task_id, tier, launches in (
                (hard, "hard", 2),
                (easy, "easy", 3),
                (other, [], 1)):
            path = runtime / "tasks" / f"{task_id}.json"
            state = json.loads(path.read_text())
            state["tier"] = tier
            state["history"] = [
                {"event": "launched", "attempt": attempt}
                for attempt in range(1, launches + 1)
            ]
            path.write_text(json.dumps(state))

        request_stats = self.baton(
            project, "stats",
            "--task", hard,
            "--task", medium,
            "--task", hard,
            "--task", easy,
            "--task", other,
            check=True,
        )
        self.assertEqual(
            request_stats.stdout,
            "I used 7 workers for this request: 2 on hard, 1 on medium, "
            "3 on easy, and 1 on other levels.\n",
        )
        self.assertNotIn("Status counts:", request_stats.stdout)

        aggregate = self.baton(project, "stats", check=True)
        self.assertIn("Status counts:\n", aggregate.stdout)
        self.assertNotIn("for this request", aggregate.stdout)

        unknown = self.baton(
            project, "stats", "--task", hard, "--task", "T999-unknown",
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertEqual(unknown.stdout, "")
        self.assertIn("unknown task T999-unknown", unknown.stderr)
        self.assertNotIn("I used", unknown.stderr)

        malformed = self.baton(project, "stats", "--task", "not-a-task-id")
        self.assertNotEqual(malformed.returncode, 0)
        self.assertEqual(malformed.stdout, "")
        self.assertIn("task id must look like T001-short-slug", malformed.stderr)

        denied = self.baton(
            project, "stats", "--task", hard,
            env={"BATON_TASK_ID": "T999-worker", "BATON_ATTEMPT": "1",
                 "BATON_LEASE": "worker"},
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

    def test_archive_preflights_all_destinations_before_moving(self):
        project = self.make_project()
        task_ids = [
            self.create_task(project, "archive one", ["one/**"]),
            self.create_task(project, "archive two", ["two/**"]),
        ]
        runtime = project / ".baton"
        for task_id in task_ids:
            state_path = runtime / "tasks" / f"{task_id}.json"
            state = json.loads(state_path.read_text())
            state["status"] = "done"
            state_path.write_text(json.dumps(state))
            work = runtime / "work" / task_id
            work.mkdir(parents=True)
            (work / "artifact").write_text("test\n")
        collision = runtime / "archive" / f"{task_ids[1]}.work"
        collision.write_text("collision\n")
        archived = self.baton(project, "archive")
        self.assertNotEqual(archived.returncode, 0)
        for task_id in task_ids:
            self.assertTrue((runtime / "tasks" / f"{task_id}.json").exists())
            self.assertFalse((runtime / "archive" / f"{task_id}.json").exists())

    def test_archive_defers_sigterm_until_transaction_is_complete(self):
        project = self.make_project()
        task_id = self.create_task(project, "archive signal", ["archive/**"])
        runtime = project / ".baton"
        state_path = runtime / "tasks" / f"{task_id}.json"
        state = json.loads(state_path.read_text())
        state["status"] = "done"
        state_path.write_text(json.dumps(state))
        work = runtime / "work" / task_id
        work.mkdir(parents=True)
        (work / "artifact").write_text("test\n")
        marker = self.base / "archive-move-started"
        code = r'''
import os
from pathlib import Path
import runpy
import sys
import time
from types import SimpleNamespace

module = runpy.run_path(sys.argv[1], run_name="baton_archive_probe")
original = module["shutil"].move
marker = Path(sys.argv[3])

def slow_move(source, target):
    result = original(source, target)
    marker.write_text("moved\n")
    time.sleep(0.25)
    return result

module["shutil"].move = slow_move
os.chdir(sys.argv[2])
module["cmd_archive"](SimpleNamespace())
'''
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(SOURCE_BATON), str(project), str(marker)],
            cwd=project, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(marker.exists())
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, -signal.SIGTERM)
        self.assertFalse((runtime / "tasks" / f"{task_id}.json").exists())
        self.assertFalse((runtime / "tasks" / f"{task_id}.md").exists())
        self.assertFalse((runtime / "work" / task_id).exists())
        self.assertTrue((runtime / "archive" / f"{task_id}.json").exists())
        self.assertTrue((runtime / "archive" / f"{task_id}.md").exists())
        self.assertTrue((runtime / "archive" / f"{task_id}.work").exists())

    def test_unborn_repository_diff_uses_worktree_content(self):
        project = self.make_project(commit=False)
        worker = self.write_worker(STAGE_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "stage", ["new/**"])
        self.baton(project, "run", task_id, check=True)
        diff = project / ".baton" / "work" / task_id / "attempt-1.diff"
        self.assertIn("new/staged.txt", diff.read_text())

    def test_capsule_sandwich_brief_digest_and_retry_delta(self):
        project = self.make_project()
        worker = self.write_worker(GOOD_WORKER)
        self.configure(project, worker)
        task_id = self.create_task(project, "capsule", ["capsule/**"])
        self.baton(project, "run", task_id, check=True)

        work = project / ".baton" / "work" / task_id
        prompt = (work / "attempt-1.prompt.md").read_text()
        brief = (work / "attempt-1.brief.md").read_text()
        digest_line, capsule = brief.split("\n\n", 1)
        digest = hashlib.sha256(capsule.encode()).hexdigest()
        self.assertEqual(digest_line, f"Content digest: sha256:{digest}")
        launched = next(
            entry for entry in self.state(project, task_id)["history"]
            if entry.get("event") == "launched"
        )
        self.assertEqual(launched["capsule_chars"], len(capsule))
        self.assertTrue(prompt.startswith(capsule))
        self.assertTrue(prompt.endswith(capsule))
        self.assertEqual(prompt.count(capsule), 2)

        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_capsule_probe")
        task = self.state(project, task_id)
        spec = (project / ".baton" / "tasks" / f"{task_id}.md").read_text()
        entries = module["memory_index_entries"](
            (project / ".baton" / "memory.md").read_text()
        )
        self.assertEqual(module["compile_context_capsule"](task, spec, entries), capsule)
        self.assertEqual(module["compile_context_capsule"](task, spec, entries), capsule)

        self.baton(
            project, "task", "return", task_id,
            "--reason", "Preserve the capsule boundary", check=True,
        )
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        self.baton(project, "run", task_id, check=True)
        retry_prompt = (work / "attempt-2.prompt.md").read_text()
        retry_brief = (work / "attempt-2.brief.md").read_text()
        _retry_digest, retry_capsule = retry_brief.split("\n\n", 1)
        self.assertTrue(retry_prompt.startswith(retry_capsule))
        self.assertTrue(retry_prompt.endswith(retry_capsule))
        self.assertIn("## Retry delta", retry_capsule)
        self.assertIn("Preserve the capsule boundary", retry_capsule)
        self.assertIn("attempt-1.report.md", retry_prompt)
        self.assertNotEqual(retry_capsule, capsule)

    def test_placeholder_and_empty_specs_are_rejected_by_run_and_validate(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        created = self.baton(
            project, "task", "create", "--title", "unfinished spec",
            "--tier", "test", check=True,
        )
        task_id = created.stdout.split()[1]
        run = self.baton(project, "run", task_id)
        validation = self.baton(project, "validate")
        self.assertNotEqual(run.returncode, 0)
        self.assertNotEqual(validation.returncode, 0)
        shared = "Objective still contains the template placeholder"
        self.assertIn(shared, run.stderr)
        self.assertIn(shared, validation.stdout)
        self.assertEqual(self.state(project, task_id)["status"], "queued")

        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            "Replace this line with one clear outcome.", "",
        ))
        empty_run = self.baton(project, "run", task_id)
        empty_validation = self.baton(project, "validate")
        self.assertIn("Objective is empty", empty_run.stderr)
        self.assertIn("Objective is empty", empty_validation.stdout)

    def test_capsule_budget_overflow_is_rejected_by_run_and_validate(self):
        project = self.make_project()
        self.configure(
            project, self.write_worker(NO_CHANGE_WORKER), capsule_max_chars=100,
        )
        task_id = self.create_task(project, "over budget", ["budget/**"])
        run = self.baton(project, "run", task_id)
        validation = self.baton(project, "validate")
        self.assertNotEqual(run.returncode, 0)
        self.assertNotEqual(validation.returncode, 0)
        for output in (run.stderr, validation.stdout):
            self.assertIn("capsule_max_chars=100", output)
            self.assertIn("exceeded by", output)
        self.assertEqual(self.state(project, task_id)["status"], "queued")

    def test_task_capsule_running_raw_uses_stored_launch_and_denies_worker(self):
        project = self.make_project()
        task_id = self.create_task(project, "stored capsule", ["capsule/**"])
        env = self.lease_task(project, task_id, "stored-capsule-lease")
        brief = (
            project / ".baton" / "work" / task_id / "attempt-1.brief.md"
        ).read_text()
        _digest_header, stored_capsule = brief.split("\n\n", 1)
        spec = project / ".baton" / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            "Complete the stored capsule task.", "This changed after launch.",
        ))

        raw = self.baton(project, "task", "capsule", task_id, "--raw", check=True)
        self.assertEqual(raw.stdout.encode(), stored_capsule.encode())
        shown = self.baton(project, "task", "capsule", task_id, check=True)
        self.assertTrue(shown.stdout.startswith(stored_capsule + "\n\nCapsule diagnostics:\n"))
        self.assertIn("Source: launch (attempt 1)\n", shown.stdout)
        self.assertIn(
            "Digest: sha256:" + hashlib.sha256(stored_capsule.encode()).hexdigest(),
            shown.stdout,
        )
        denied = self.baton(project, "task", "capsule", task_id, env=env)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("worker processes cannot run orchestrator commands", denied.stderr)

    def test_task_capsule_prospective_preview_matches_launch_and_writes_nothing(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        task_id = self.create_task(project, "prospective capsule", ["preview/**"])
        runtime = project / ".baton"

        def snapshot():
            return {
                str(path.relative_to(runtime)): (
                    path.is_dir(), path.stat().st_mtime_ns,
                    b"" if path.is_dir() else path.read_bytes(),
                )
                for path in runtime.rglob("*")
            }

        before = snapshot()
        shown = self.baton(project, "task", "capsule", task_id, check=True)
        self.assertEqual(snapshot(), before)
        self.assertIn("Source: current spec (prospective)\n", shown.stdout)
        prospective = self.baton(
            project, "task", "capsule", task_id, "--raw", check=True,
        ).stdout
        self.assertEqual(snapshot(), before)

        self.baton(project, "run", task_id, check=True)
        brief = runtime / "work" / task_id / "attempt-1.brief.md"
        _digest_header, launched = brief.read_text().split("\n\n", 1)
        self.assertEqual(prospective, launched)

    def test_task_capsule_diagnostics_count_unicode_characters(self):
        project = self.make_project()
        title = "aperçu 😀 東京"
        task_id = self.create_task(project, title, ["café/**"])
        shown = self.baton(project, "task", "capsule", task_id, check=True)
        task_line = f"Task: {task_id}: {title}"
        scope_line = "Scope: café/**"
        objective = f"## Objective\nComplete the {title} task."
        self.assertIn(f"- Task: {len(task_line)} chars\n", shown.stdout)
        self.assertIn(f"- Scope: {len(scope_line)} chars\n", shown.stdout)
        self.assertIn(f"- Objective: {len(objective)} chars\n", shown.stdout)
        capsule, diagnostics = shown.stdout.split("\n\nCapsule diagnostics:\n", 1)
        self.assertIn(f"Capsule: {len(capsule)} of 4000 chars", diagnostics)
        self.assertRegex(diagnostics, r"Digest: sha256:[0-9a-f]{64}\n")

    def test_task_capsule_over_budget_reports_all_diagnostics_and_raw_is_empty(self):
        project = self.make_project()
        self.configure(
            project, self.write_worker(NO_CHANGE_WORKER), capsule_max_chars=100,
        )
        task_id = self.create_task(project, "preview overflow", ["budget/**"])
        shown = self.baton(project, "task", "capsule", task_id)
        self.assertNotEqual(shown.returncode, 0)
        self.assertTrue(shown.stdout.startswith("# Critical Context Capsule\n"))
        self.assertRegex(
            shown.stdout, r"Capsule: \d+ of 100 chars \(\d+ chars overflow\)",
        )
        for label in (
                "Header", "Task", "Scope", "Objective", "Acceptance criteria",
                "Not allowed", "Verification"):
            self.assertRegex(shown.stdout, rf"- {label}: \d+ chars\n")
        self.assertRegex(shown.stdout, r"Digest: sha256:[0-9a-f]{64}\n")
        self.assertIn("Source: current spec (prospective)\n", shown.stdout)
        self.assertIn("capsule_max_chars=100", shown.stderr)

        raw = self.baton(project, "task", "capsule", task_id, "--raw")
        self.assertNotEqual(raw.returncode, 0)
        self.assertEqual(raw.stdout, "")
        self.assertIn("capsule_max_chars=100", raw.stderr)

    def test_task_capsule_errors_pass_through_and_reject_unknown_or_archived(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        created = self.baton(
            project, "task", "create", "--title", "unfinished preview",
            "--tier", "test", check=True,
        )
        unfinished = created.stdout.split()[1]
        preview = self.baton(project, "task", "capsule", unfinished)
        launch = self.baton(project, "run", unfinished)
        self.assertNotEqual(preview.returncode, 0)
        self.assertEqual(preview.stderr, launch.stderr)
        self.assertIn("Objective still contains the template placeholder", preview.stderr)

        unknown = self.baton(project, "task", "capsule", "T999-not-here")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("no such task: T999-not-here", unknown.stderr)

        archived = self.create_task(project, "archived preview", ["archive/**"])
        state_path = project / ".baton" / "tasks" / f"{archived}.json"
        state = json.loads(state_path.read_text())
        state["status"] = "done"
        state_path.write_text(json.dumps(state))
        self.baton(project, "archive", check=True)
        rejected = self.baton(project, "task", "capsule", archived)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(f"{archived} is archived", rejected.stderr)

    def test_referenced_memory_is_ordered_deduplicated_and_snapshotted(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        self.write_memory(project, [
            ("M001", "W", "First worker fact", "FIRST FULL BODY MUST NOT LEAK"),
            ("M1000", "B", "Four-digit shared fact", "SECOND FULL BODY MUST NOT LEAK"),
        ])
        task_id = self.create_task(project, "referenced memory", ["memory/**"])
        runtime = project / ".baton"
        spec_path = runtime / "tasks" / f"{task_id}.md"
        spec_path.write_text(spec_path.read_text().replace(
            "List the paths and facts the worker needs. Reference memory ids when useful.",
            "Use M1000, then M001, then M1000 again. Other sections do not count.",
        ))

        preview = self.baton(project, "task", "capsule", task_id, check=True)
        self.assertIn("- Referenced memory: ", preview.stdout)
        prospective = self.baton(
            project, "task", "capsule", task_id, "--raw", check=True,
        ).stdout
        expected_section = (
            "## Referenced memory\n"
            "Load full entries as needed with "
            "`python3 .baton/baton memory show ID`.\n"
            "- M1000: Four-digit shared fact\n"
            "- M001: First worker fact"
        )
        self.assertIn(expected_section, prospective)
        self.assertEqual(prospective.count("- M1000: Four-digit shared fact"), 1)
        self.assertGreater(
            prospective.index("## Referenced memory"),
            prospective.index("## Verification"),
        )
        for body in ("FIRST FULL BODY MUST NOT LEAK", "SECOND FULL BODY MUST NOT LEAK"):
            self.assertNotIn(body, prospective)
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_stored_memory_probe")
        stored_result = module["stored_context_capsule_components"](prospective)
        self.assertEqual(stored_result["text"], prospective)
        self.assertIn("Referenced memory", dict(stored_result["section_chars"]))

        self.baton(project, "run", task_id, check=True)
        work = runtime / "work" / task_id
        _digest, launch_capsule = (work / "attempt-1.brief.md").read_text().split(
            "\n\n", 1,
        )
        prompt = (work / "attempt-1.prompt.md").read_text()
        self.assertEqual(launch_capsule, prospective)
        self.assertTrue(prompt.startswith(launch_capsule))
        self.assertTrue(prompt.endswith(launch_capsule))
        self.assertEqual(prompt.count(launch_capsule), 2)

    def test_memory_reference_errors_fail_compile_preview_launch_and_validate(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        self.write_memory(project, [
            *[(f"M00{number}", "W", f"Worker fact {number}", "body")
              for number in range(1, 8)],
            ("M010", "O", "Orchestrator secret", "orchestrator body"),
        ])
        cases = [
            ("unknown reference", "M999", "referenced memory id M999 is missing from memory.md"),
            (
                "orchestrator reference", "M010",
                "referenced memory id M010 is orchestrator-only [O]; worker capsules "
                "may reference only [W] or [B]",
            ),
            (
                "too many references", "M001 M002 M003 M004 M005 M006 M007",
                "Context references 7 memory entries; maximum is 6; split the task "
                "or remove references",
            ),
        ]
        runtime = project / ".baton"
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_memory_error_probe")
        entries = module["memory_index_entries"]((runtime / "memory.md").read_text())
        task_cases = []
        for title, context, message in cases:
            task_id = self.create_task(project, title, [f"{title.replace(' ', '-')}/**"])
            spec_path = runtime / "tasks" / f"{task_id}.md"
            spec_path.write_text(spec_path.read_text().replace(
                "List the paths and facts the worker needs. Reference memory ids when useful.",
                context,
            ))
            task_cases.append((task_id, spec_path, message))
            with self.assertRaisesRegex(ValueError, re.escape(message)):
                module["compile_context_capsule"](
                    self.state(project, task_id), spec_path.read_text(), entries,
                )
            preview = self.baton(project, "task", "capsule", task_id)
            launch = self.baton(project, "run", task_id)
            self.assertNotEqual(preview.returncode, 0)
            self.assertNotEqual(launch.returncode, 0)
            self.assertIn(message, preview.stderr)
            self.assertIn(message, launch.stderr)

        validation = self.baton(project, "validate")
        self.assertNotEqual(validation.returncode, 0)
        for _task_id, _spec_path, message in task_cases:
            self.assertIn(message, validation.stdout)

    def test_memory_add_rejects_structural_values_and_show_requires_indexed_id(self):
        invalid_values = (
            ("   ", "body", "summary"),
            ("line one\nline two", "body", "summary"),
            (
                "valid summary",
                "real body\n### M999 [W] injected heading\nsynthetic body",
                "entry heading",
            ),
        )
        for index, (summary, body, message) in enumerate(invalid_values):
            with self.subTest(summary=summary, body=body):
                project = self.make_project(f"invalid-memory-add-{index}")
                memory = project / ".baton" / "memory.md"
                before = memory.read_bytes()
                rejected = self.baton(
                    project, "memory", "add", "--for", "worker", summary, body,
                )
                self.assertEqual(rejected.returncode, 1)
                self.assertIn(message, rejected.stderr)
                self.assertEqual(memory.read_bytes(), before)

        project = self.make_project("unindexed-memory-heading")
        self.write_memory(project, [
            (
                "M001", "W", "Real memory", "real body\n"
                "### M999 [W] injected heading\nsynthetic body",
            ),
        ])
        shown = self.baton(project, "memory", "show", "M999")
        self.assertEqual(shown.returncode, 1)
        self.assertIn("no memory entry M999", shown.stderr)

    def test_memory_add_rejects_unicode_line_separators_without_mutation(self):
        for separator in ("\u2028", "\u2029"):
            for variant, summary in (
                    ("embedded", f"safe{separator}unsafe"),
                    ("trailing", f"trailing{separator}")):
                with self.subTest(separator=hex(ord(separator)), variant=variant):
                    project = self.make_project(
                        f"unicode-memory-{ord(separator):x}-{variant}"
                    )
                    memory = project / ".baton" / "memory.md"
                    before = memory.read_bytes()
                    rejected = self.baton(
                        project, "memory", "add", "--for", "worker",
                        summary, "body",
                    )
                    self.assertEqual(rejected.returncode, 1)
                    self.assertIn("single-line", rejected.stderr)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertEqual(memory.read_bytes(), before)
                    indexed = self.baton(project, "memory", "index")
                    self.assertEqual(
                        indexed.returncode, 0, indexed.stdout + indexed.stderr,
                    )

    def test_memory_index_parser_is_strict_and_preserves_four_digit_ids(self):
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_memory_parser_probe")
        parse = module["memory_index_entries"]
        valid = (
            "# Memory\n\n## Index\n"
            "- M1000 [B] Shared fact\n"
            "- M001 [W] Worker fact\n\n"
            "## Entries\n"
        )
        self.assertEqual(
            parse(valid),
            [("M1000", "B", "Shared fact"), ("M001", "W", "Worker fact")],
        )
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse(valid.replace("- M001 [W] Worker fact", "- M01 [W] Worker fact"))
        with self.assertRaisesRegex(ValueError, "duplicate id M1000"):
            parse(valid.replace("M001 [W] Worker fact", "M1000 [W] Worker fact"))

        project = self.make_project()
        memory = project / ".baton" / "memory.md"
        memory.write_text(valid.replace("M001 [W] Worker fact", "M1000 [W] Worker fact"))
        validation = self.baton(project, "validate")
        self.assertNotEqual(validation.returncode, 0)
        self.assertIn("memory index has duplicate id M1000", validation.stdout)

    def test_no_reference_format_is_unchanged_and_memory_counts_toward_budget(self):
        project = self.make_project()
        self.write_memory(project, [
            ("M001", "W", "A deliberately long summary for capsule budgeting", "body"),
        ])
        task_id = self.create_task(project, "format stability", ["stable/**"])
        runtime = project / ".baton"
        module = runpy.run_path(str(SOURCE_BATON), run_name="baton_memory_budget_probe")
        task = self.state(project, task_id)
        spec_path = runtime / "tasks" / f"{task_id}.md"
        spec = spec_path.read_text().replace(
            "Complete the format stability task.",
            "Complete the format stability task while mentioning M999 outside Context.",
        )
        entries = module["memory_index_entries"]((runtime / "memory.md").read_text())
        capsule = module["compile_context_capsule"](task, spec, entries)
        expected = (
            "# Critical Context Capsule\n\n"
            f"Task: {task_id}: format stability\n"
            "Scope: stable/**\n\n"
            "## Objective\nComplete the format stability task while mentioning M999 "
            "outside Context.\n\n"
            "## Acceptance criteria\n- The targeted task behavior is verified.\n\n"
            "## Not allowed\n- No changes outside the task scope.\n"
            "- No unrelated cleanup or new dependencies.\n\n"
            "## Verification\n- Add exact, targeted commands."
        )
        self.assertEqual(capsule, expected)
        self.assertNotIn("Referenced memory", capsule)

        baseline = module["context_capsule_components"](task, spec, entries)
        referenced_spec = spec.replace(
            "List the paths and facts the worker needs. Reference memory ids when useful.",
            "Load M001.",
        )
        referenced = module["context_capsule_components"](
            task, referenced_spec, entries, baseline["chars"],
        )
        self.assertGreater(referenced["overflow"], 0)
        self.assertIn("Referenced memory", dict(referenced["section_chars"]))
        spec_path.write_text(referenced_spec)
        self.configure(
            project, self.write_worker(NO_CHANGE_WORKER),
            capsule_max_chars=baseline["chars"],
        )
        preview = self.baton(project, "task", "capsule", task_id)
        self.assertNotEqual(preview.returncode, 0)
        self.assertIn("- Referenced memory: ", preview.stdout)
        self.assertIn("capsule_max_chars=", preview.stderr)

    def test_review_brief_warns_on_memory_drift_and_shows_launch_capsule(self):
        project = self.make_project()
        self.configure(project, self.write_worker(NO_CHANGE_WORKER))
        self.write_memory(project, [
            ("M001", "W", "Original launch summary", "body"),
        ])
        task_id = self.create_task(project, "review memory drift", ["review/**"])
        runtime = project / ".baton"
        spec = runtime / "tasks" / f"{task_id}.md"
        spec.write_text(spec.read_text().replace(
            "List the paths and facts the worker needs. Reference memory ids when useful.",
            "Use M001.",
        ))
        self.baton(project, "run", task_id, check=True)
        _digest, stored_capsule = (
            runtime / "work" / task_id / "attempt-1.brief.md"
        ).read_text().split("\n\n", 1)
        memory = runtime / "memory.md"
        memory.write_text(memory.read_text().replace(
            "Original launch summary", "Edited after launch summary",
        ))

        review, _token = self.review_brief_token(project, task_id)
        warning = (
            "WARNING: capsule inputs drifted since launch (spec or memory changed); "
            "showing launch capsule"
        )
        self.assertTrue(review.stdout.startswith(stored_capsule + "\n"))
        self.assertEqual(review.stdout.count(warning), 1)
        self.assertIn("- M001: Original launch summary", review.stdout)
        self.assertNotIn("Edited after launch summary", review.stdout)

    def test_memory_archive_and_prompt_spec_alignment(self):
        project = self.make_project()
        self.baton(project, "memory", "add", "--for", "worker",
                   "Use the local environment", "Do not install global packages.", check=True)
        index = self.baton(project, "memory", "index", "--for", "worker", check=True)
        self.assertIn("M001", index.stdout)
        shown = self.baton(project, "memory", "show", "M001", check=True)
        self.assertIn("Do not install global packages.", shown.stdout)
        self.assertEqual(self.baton(project, "validate").returncode, 0)

        spec = (ROOT / "SPEC.md").read_text()
        prompt = (ROOT / "prompts" / "create-framework.md").read_text()
        embedded = prompt.split("<!-- BEGIN SPEC -->\n", 1)[1].split(
            "\n<!-- END SPEC -->", 1
        )[0]
        self.assertEqual(embedded, spec.rstrip())

        orchestrator = (ROOT / "framework" / "orchestrator.md").read_text()
        use_prompt = (ROOT / "prompts" / "use-framework.md").read_text()
        example_text = (ROOT / "framework" / "config.example.toml").read_text()
        question = (
            "Which model and reasoning level should Baton use for hard, medium, "
            "and easy tasks? You can specify each one or ask me to derive the "
            "settings from the current orchestrator."
        )
        ui_rule = (
            "Ask this as a persistent plain-text question that remains visible "
            "until answered. Never use a transient form; expiration or dismissal "
            "is not an answer and must not be treated as selecting any option."
        )
        self.assertEqual(orchestrator.count(question), 1)
        self.assertEqual(orchestrator.count(ui_rule), 1)
        self.assertLess(abs(orchestrator.index(question) - orchestrator.index(ui_rule)), 600)
        normalized_orchestrator = " ".join(orchestrator.split())
        for phrase in (
            "unsure", "continues the task without settings", "do not repeat the initial question",
            "reliable harness-provided context", "read-only local", "never infer",
            "next lower available reasoning", "with only two levels",
            "already the minimum", "permission before lowering", "Omission is not approval",
            "avoided an unapproved downgrade", "display metadata alone is insufficient",
        ):
            self.assertIn(phrase.lower(), normalized_orchestrator.lower())
        self.assertIn("internally and silently", orchestrator)
        self.assertIn("Never ask the user to run", orchestrator)
        for path in (
            ROOT / "framework" / "orchestrator.md",
            ROOT / "framework" / "config.example.toml",
            ROOT / "prompts" / "use-framework.md",
            ROOT / "prompts" / "improve-framework.md",
            ROOT / "skill" / "SKILL.md",
            ROOT / "SPEC.md",
            ROOT / "summary.md",
        ):
            text = path.read_text()
            for stale in (
                "Harness memory", "use the defaults", "documented defaults",
                "GPT 5.6", "Claude Code Opus 4.8", "Claude Opus 4.8",
            ):
                self.assertNotIn(stale, text, f"{stale!r} remains in {path}")
        for text in (orchestrator, use_prompt):
            normalized = " ".join(text.split())
            self.assertIn("0 workers for this request", normalized)
        self.assertIn("stats --task ID", " ".join(use_prompt.split()))
        self.assertIn(
            "`--task ID` once for every unique task",
            " ".join(orchestrator.split()),
        )
        self.assertIn("runtime-wide", orchestrator)
        self.assertIn("whole Baton runtime", use_prompt)
        self.assertIn("Never omit `--tier`", orchestrator)

        with (ROOT / "framework" / "config.example.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertNotIn("worker", config.get("commands", {}))
        self.assertNotIn("tiers", config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
