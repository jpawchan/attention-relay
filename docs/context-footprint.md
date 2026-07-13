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
already in the installed orchestrator manual. They are counted there, once. A
fully configured start brief does not print the missing-level routing ask, and
`config.toml` itself is machine configuration rather than agent context, so
neither is added as another context component.

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
and removes the project. It then validates and reports the bundled recorded
provider differential in `tools/context-provider-differential.json`. It does not
access the network. To inspect exactly what was counted, use `--keep-artifacts
DIR`; the directory receives each component and their raw concatenation. Use
`--offline-estimate-only` to reproduce the standard-library bytes heuristic when
recorded provider evidence does not apply.

Run the command twice and compare the total and per-artifact SHA-256 values. The
focused automated check does this too:

```bash
python3 tests/test_context_footprint.py
```

## Result for this revision

Two independent fresh temporary installs produced identical metrics and hashes:

| Artifact | Characters | Bytes | Lines | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| activation instructions | 497 | 497 | 10 | `8869fd2b8088e913d8de0c0bea9045faf958bb45abf8d6e0564be3ffedaaafef` |
| installed orchestrator manual | 13,573 | 13,575 | 305 | `7bf8eeed2ab07c166f1a244086e309a58c800b608d67d4f848bf79ba4a0840c3` |
| generated configured start brief | 1,054 | 1,054 | 19 | `b55a62bbc9fc326736b5e443e6b33ae8d873b5198c4848c84962709dba5ebde1` |
| **Total** | **15,124** | **15,126** | **334** | `f3ca7044b52318effe0e371048e12b4fff4927be928a9d1b11827fefe80d0616` |

These values are revision-specific. Re-run the script whenever the activation
prompt, installed manual, or start brief changes rather than carrying this table
forward as an estimate.

## Model-aware token result

A live provider differential measured the exact 15,126-byte payload above,
inserted between fixed inert-data markers. The baseline was measured before and
after each payload request and was identical on both sides. The result is exact
for that recorded harness/API differential and tested model revision/message
construction; it is **not** claimed to be a standalone tokenizer count or a
universal count for every similarly named model endpoint.

| Model/provider path | Baseline | Payload request | Provider-reported differential |
| --- | ---: | ---: | ---: |
| GPT 5.6 Sol (`gpt-5.6-sol`, Hermes via OpenAI Codex) | 5,011 | 8,437 | **3,426 tokens** |
| Claude Opus 4.8 (`claude-opus-4-8`, Claude Code) | 1,809 | 7,132 | **5,323 tokens** |

Here “logical input” is the provider-reported sum of uncached input, cache-read
input, and cache-write input (cache creation). The recorded JSON preserves the tested
harness/model paths, both bracketing baselines, payload counts, differential,
payload byte count, and payload hash. The script rejects that evidence if a newly
generated payload does not match the recorded bytes and hash, rather than
silently applying stale precision.

For a changed payload or an environment without applicable provider evidence,
the offline fallback remains explicitly labeled `ESTIMATE`: `ceil(bytes / 4)`,
with a deliberately broad conservative range from `ceil(bytes / 6)` through
`ceil(bytes / 2)`. For this payload that is 3,782 estimated tokens, range
2,521–7,563, for either path. The matching fallback values do not imply matching
tokenization; the heuristic only measures the same UTF-8 bytes. A similarly
named tokenizer, generic GPT encoding, or third-party Claude approximation is
not authoritative for these exact provider paths.

## Context tokens, cache, and billing

This footprint is framework-attributable logical input context, not a prediction
of an invoice. Prompt caching can make repeated manual or activation prefixes
cheaper to bill, but cached tokens are still present in the model's context and
still consume context-window capacity. This differential deliberately sums
uncached, cache-read, and cache-write input (cache creation) so cache placement does not
erase logical input. Providers may price those categories differently, and may
separately report output and reasoning tokens; neither is part of this activation
input measurement.

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
through Baton. For the tested paths, compare the likely direct goal against
3,426 GPT-path or 5,323 Claude-path logical input tokens; for other paths, keep
the 3,782-token fallback and 2,521–7,563 range visible. Baton is most defensible
when task decomposition, fresh-worker focus, parallelism, and review are expected
to save more than that fixed cost or to provide quality and risk-control benefits
worth the overhead.