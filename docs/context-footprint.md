# Activation context footprint

This measurement answers one narrow question: how much Baton-authored context is
loaded after a fresh install is activated and its conventional difficulty routes
are configured, but before the user supplies the first coding goal?

## Boundary

The standard activation number includes, in the order an orchestrator is told to
load them:

1. the exact activation instructions in `prompts/use-framework.md`;
2. the installed `.baton/orchestrator.md` copied by `baton init` into a disposable
   Git project; and
3. stdout from `.baton/baton orchestrator brief --phase start` in that fresh
   project after `hard`, `medium`, and `easy` have been configured.

The configured route descriptions intentionally loaded before the goal are
already in the installed orchestrator manual. They are counted there, once. The
fully configured start brief still asks whether the user wants to keep or change
those preferences, but it prints no missing-tier command skeletons.
`config.toml` itself is machine configuration rather than agent context, so it
is not added as another context component.

The number excludes the host harness's base system prompt and tool schemas,
unrelated user profile or saved harness memory, `summary.md`, Baton source code,
`worker.md`, task specifications, worker prompts, and later Critical Context
Capsules. It also excludes provider message framing that is not present in these
artifacts. Characters are Unicode code points, bytes are UTF-8 bytes, and lines
are Python `str.splitlines()` entries. The total is the raw bytes of the three
artifacts concatenated in the listed order, with no measurement labels or
separators inserted.

## Reproduce it

From the repository root, run:

```bash
python3 tools/measure_context.py
python3 tools/measure_context.py --json
```

The standard-library-only script creates a new temporary Git project, runs the
current checkout's `framework/baton init`, writes a complete disposable routing
configuration, invokes the installed start brief, measures the resulting bytes,
and removes the project. It reports a standard-library offline estimate by
default and does not access the network. To inspect exactly what was counted,
use `--keep-artifacts DIR`; the directory receives each component and their raw
concatenation. `tools/context-provider-differential.json` is explicitly retired
historical evidence for the preceding payload and is rejected if supplied. New
evidence may be passed with `--provider-evidence FILE` only after a genuine live
bracketing measurement of the exact current bytes.

Run the command twice and compare the total and per-artifact SHA-256 values. The
focused automated check does this too:

```bash
python3 tests/test_context_footprint.py
```

## Result for this revision

Two independent fresh temporary installs produced identical metrics and hashes:

| Artifact | Characters | Bytes | Lines | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| activation instructions | 1,017 | 1,021 | 17 | `6b310ea472170e3f9f6cb56335a0632ed1f44eb9250859e006c89f3c8467484a` |
| installed orchestrator manual | 15,108 | 15,110 | 329 | `6f94f32cb214c4b07f8da1a5623fc2d58fecc59e50da1dae95c2a0a86cfd8225` |
| generated configured start brief | 3,411 | 3,421 | 27 | `d7fe9d45d9456bf36fe6fd56f9eae8bfda47689c2b56bbbf1c9c18bdea342c3e` |
| **Total** | **19,536** | **19,552** | **373** | `22ff623fe88291ae9f2c284a351b37924c82a906ffe9bf08f22cc5edb92f21b8` |

These values are revision-specific. Re-run the script whenever the activation
prompt, installed manual, or start brief changes rather than carrying this table
forward as an estimate.

## Model-aware token result

No live provider differential was collected for the exact 19,552-byte payload
above. The preceding payload's genuine provider evidence remains in
`tools/context-provider-differential.json` with `status: retired`; the default
result does not load it, and explicit loading rejects it. This avoids fabricating
new precision by adding an estimated delta to old token counts.

The current result is explicitly labeled `ESTIMATE`: `ceil(bytes / 4)` gives
4,888 estimated tokens, with a deliberately broad conservative range from
`ceil(bytes / 6)` through `ceil(bytes / 2)`, or 3,259–9,776 tokens, for either
named model path. Matching fallback values do not imply matching tokenization;
the heuristic only measures the same UTF-8 bytes. A similarly named tokenizer,
generic GPT encoding, or third-party Claude approximation is not authoritative
for these provider paths. Publishing a new provider figure requires identical
baseline requests before and after the exact payload request and genuine usage
accounting from each tested harness/model path.

## Context tokens, cache, and billing

This footprint is framework-attributable input context, not a prediction of an
invoice. Prompt caching can make repeated manual or activation prefixes cheaper
to bill, but cached tokens are still present in the model's context and still
consume context-window capacity. The current offline estimate uses only UTF-8
bytes and has no cache accounting. Any new live differential for this boundary
must sum uncached, cache-read, and cache-write input (cache creation) so cache
placement does not erase logical input. Providers may price those categories
differently and may separately report output and reasoning tokens; neither is
part of this activation input measurement.

Conversely, a billed input count can be larger because it may include the host
system prompt, tool definitions, conversation framing, and unrelated messages
excluded by this boundary. It can also differ because provider APIs serialize
roles or attachments in ways that cannot be reconstructed from plain artifact
bytes. Compare Baton runs and direct runs using the same model, harness, cache
state, and provider usage fields; do not subtract this measurement from a mixed
billing total as though both used the same boundary.

## Break-even implication

Activation is overhead. A coding goal likely to consume fewer tokens than this
activation footprint is usually better executed directly rather than delegated
through Baton. Without current live provider evidence, compare the likely direct
goal against the 4,888-token offline estimate while keeping its 3,259–9,776
range visible. Baton is most defensible when task decomposition, fresh-worker
focus, parallelism, and review are expected to save enough context to exceed
that overhead or to provide quality and risk-control benefits worth the cost.