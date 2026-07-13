#!/usr/bin/env python3
"""Measure Baton's pre-goal activation context using a fresh temporary install."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, cast, Mapping

ARTIFACT_ORDER = (
    "activation_instructions",
    "installed_orchestrator_manual",
    "generated_start_brief",
)
STANDARD_EXCLUSIONS = (
    "host base system prompt",
    "host tool schemas",
    "unrelated user profile or saved harness memory",
    "summary.md",
    "source code",
    "worker.md",
    "task specifications and later task capsules",
)
MODEL_PATHS = (
    ("gpt_5_6_sol", "GPT 5.6 Sol"),
    ("claude_opus_4_8", "Claude Opus 4.8"),
)
PROVIDER_EVIDENCE = Path(__file__).with_name("context-provider-differential.json")
PROVIDER_PATHS = {
    "gpt_5_6_sol": "gpt_5_6_sol_via_hermes_openai_codex",
    "claude_opus_4_8": "claude_opus_4_8_via_claude_code",
}

CONFIG = """[tiers.hard]
command = "/usr/bin/true {prompt_file}"

[tiers.medium]
command = "/usr/bin/true {prompt_file}"

[tiers.easy]
command = "/usr/bin/true {prompt_file}"

[limits]
max_parallel = 3
capsule_max_chars = 4000
worker_timeout_minutes = 60
"""


def assemble_artifacts(artifacts: Mapping[str, bytes]) -> bytes:
    """Concatenate only the ordered, in-boundary bytes without measurement framing."""
    if tuple(artifacts) != ARTIFACT_ORDER:
        raise ValueError("activation artifacts must use the canonical order and boundary")
    return b"".join(artifacts[name] for name in ARTIFACT_ORDER)


def exact_metrics(data: bytes) -> dict[str, int | str]:
    text = data.decode("utf-8")
    return {
        "characters": len(text),
        "bytes": len(data),
        "lines": len(text.splitlines()),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def estimated_tokens(byte_count: int) -> dict[str, object]:
    """Return a deliberately broad, reproducible estimate, not a tokenizer claim."""
    return {
        "status": "ESTIMATE — authoritative model tokenizer/API differential unavailable",
        "path": "standard-library UTF-8 bytes/4 heuristic",
        "estimated_tokens": math.ceil(byte_count / 4),
        "conservative_range_tokens": [
            math.ceil(byte_count / 6),
            math.ceil(byte_count / 2),
        ],
    }


def load_provider_evidence(path: Path, payload: bytes) -> dict[str, object]:
    """Validate recorded provider usage evidence without making a network request."""
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("status") == "retired":
        raise ValueError("provider evidence is retired and does not apply to this revision")
    payload_hash = hashlib.sha256(payload).hexdigest()
    if evidence.get("payload_bytes") != len(payload) or evidence.get("payload_sha256") != payload_hash:
        raise ValueError("provider evidence does not match the generated activation payload")

    token_paths = {}
    for key, model in MODEL_PATHS:
        evidence_key = PROVIDER_PATHS[key]
        record = evidence.get(evidence_key)
        tested_path = evidence.get("tested_paths", {}).get(key)
        if not isinstance(record, dict) or not isinstance(tested_path, dict):
            raise ValueError("provider evidence is missing " + evidence_key)
        counts = [
            record.get("baseline_1_logical_input_tokens"),
            record.get("payload_logical_input_tokens"),
            record.get("baseline_2_logical_input_tokens"),
            record.get("payload_differential_tokens"),
        ]
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("provider evidence contains an invalid token count")
        baseline_1, payload_count, baseline_2, differential = cast(
            tuple[int, int, int, int], tuple(counts)
        )
        if baseline_1 != baseline_2 or payload_count - baseline_1 != differential:
            raise ValueError("provider evidence differential or baseline is inconsistent")
        if record.get("model") != tested_path.get("model"):
            raise ValueError("provider evidence model labels are inconsistent")
        token_paths[key] = {
            "model": model,
            "status": "PROVIDER-REPORTED DIFFERENTIAL",
            "path": tested_path["harness_path"],
            "tested_model": record["model"],
            "provider_reported_differential_tokens": differential,
            "baseline_logical_input_tokens": baseline_1,
            "payload_logical_input_tokens": payload_count,
            "logical_input_accounting": evidence["logical_input_accounting"],
            "scope": evidence["interpretation"],
            "fallback": estimated_tokens(len(payload)),
        }
    return token_paths


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("BATON_"):
            environment.pop(name)
    return environment


def generate_artifacts(repo_root: Path, project: Path) -> dict[str, bytes]:
    """Initialize and configure a disposable project, then capture loaded artifacts."""
    project.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    environment = _clean_environment()
    subprocess.run(
        [str(repo_root / "framework" / "baton"), "init", str(project)],
        cwd=project,
        env=environment,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    runtime = project / ".baton"
    (runtime / "config.toml").write_text(CONFIG, encoding="utf-8")
    brief = subprocess.run(
        [str(runtime / "baton"), "orchestrator", "brief", "--phase", "start"],
        cwd=project,
        env=environment,
        check=True,
        capture_output=True,
    ).stdout
    return {
        "activation_instructions": (repo_root / "prompts" / "use-framework.md").read_bytes(),
        "installed_orchestrator_manual": (runtime / "orchestrator.md").read_bytes(),
        "generated_start_brief": brief,
    }


def measure(
        repo_root: Path,
        keep_artifacts: Path | None = None,
        provider_evidence: Path | None = None,
) -> dict[str, object]:
    repo_root = repo_root.resolve()
    with tempfile.TemporaryDirectory(prefix="baton-context-") as temporary:
        project = Path(temporary) / "fresh-project"
        artifacts = generate_artifacts(repo_root, project)
        assembled = assemble_artifacts(artifacts)
        if keep_artifacts is not None:
            keep_artifacts.mkdir(parents=True, exist_ok=True)
            for name, data in artifacts.items():
                (keep_artifacts / (name + ".txt")).write_bytes(data)
            (keep_artifacts / "activation-context.txt").write_bytes(assembled)
    total = exact_metrics(assembled)
    if provider_evidence is None:
        token_paths = {
            key: {"model": model, **estimated_tokens(int(total["bytes"]))}
            for key, model in MODEL_PATHS
        }
    else:
        token_paths = load_provider_evidence(provider_evidence, assembled)
    return {
        "boundary": {
            "point": "after install, activation, and configured routing; before the first coding goal",
            "included": list(ARTIFACT_ORDER),
            "routing_text": (
                "the configured routes intentionally loaded in the installed orchestrator manual; "
                "a fully configured start brief adds no missing-level routing ask"
            ),
            "excluded": list(STANDARD_EXCLUSIONS),
            "assembly": "raw artifact bytes concatenated in included order; no separator or report labels",
        },
        "artifacts": {name: exact_metrics(data) for name, data in artifacts.items()},
        "total": total,
        "token_counts": token_paths,
    }


def render_text(result: Mapping[str, Any]) -> str:
    boundary = result["boundary"]
    lines = [
        "Baton activation context footprint",
        "Boundary: " + boundary["point"],
        "Included: " + ", ".join(boundary["included"]),
        "Excluded: " + "; ".join(boundary["excluded"]),
        "",
        "Exact artifact metrics:",
    ]
    for name, metrics in result["artifacts"].items():
        lines.append(
            f"- {name}: characters={metrics['characters']} bytes={metrics['bytes']} "
            f"lines={metrics['lines']} sha256={metrics['sha256']}"
        )
    total = result["total"]
    lines.extend([
        f"- TOTAL: characters={total['characters']} bytes={total['bytes']} "
        f"lines={total['lines']} sha256={total['sha256']}",
        "",
        "Model token paths:",
    ])
    for token_result in result["token_counts"].values():
        if token_result["status"] == "PROVIDER-REPORTED DIFFERENTIAL":
            fallback = token_result["fallback"]
            low, high = fallback["conservative_range_tokens"]
            lines.append(
                f"- {token_result['model']}: {token_result['status']}; "
                f"path={token_result['path']}; tested_model={token_result['tested_model']}; "
                f"tokens={token_result['provider_reported_differential_tokens']}; "
                f"logical_input={token_result['logical_input_accounting']}; "
                f"offline_fallback_estimate={fallback['estimated_tokens']}; "
                f"offline_fallback_range={low}-{high}"
            )
        else:
            low, high = token_result["conservative_range_tokens"]
            lines.append(
                f"- {token_result['model']}: {token_result['status']}; "
                f"path={token_result['path']}; estimated_tokens={token_result['estimated_tokens']}; "
                f"conservative_range_tokens={low}-{high}"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1],
        help="Baton source checkout (default: parent of tools/)",
    )
    parser.add_argument("--keep-artifacts", type=Path)
    evidence = parser.add_mutually_exclusive_group()
    evidence.add_argument(
        "--provider-evidence", type=Path,
        help="applicable live provider differential JSON (default: offline estimate)",
    )
    evidence.add_argument(
        "--offline-estimate-only", action="store_true",
        help="do not ingest provider evidence; report the reproducible bytes heuristic",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    provider_evidence = None if args.offline_estimate_only else args.provider_evidence
    result = measure(args.repo_root, args.keep_artifacts, provider_evidence)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
