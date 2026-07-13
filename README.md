# Baton

## What is Baton?

Baton is a standard-library Python framework for delegating scoped coding tasks to separate agent processes under one reviewing orchestrator.

Fresh task contexts can keep relevant constraints easier to use and avoid carrying completed-task history into every later worker request; scoped parallelism, explicit dependencies, and central review provide additional control. These are potential quality and token-efficiency gains, not guarantees, and delegation has a fixed activation cost.

The orchestrator turns a goal into small tasks, launches non-overlapping tasks in parallel waves, and reviews each worker's report and Git diff. Baton generates a task-specific Critical Context Capsule at both edges of every worker prompt, asks workers to re-read current briefs before consequential phases, and carries only a bounded state handoff between orchestrator sessions. Scope checks, lease-bound finish tokens, evidence-bound review tokens, and exact changed-path checks make mistakes visible before acceptance; they do not sandbox an agent that shares the user's operating-system permissions.

The orchestrator can be any coding agent that can read files and run commands. Workers can use Hermes Agent, Claude Code, Codex, OpenCode, or another noninteractive CLI agent and may accept a prompt or prompt-file argument; optional context hooks are specific to Claude Code.

## Why can this improve quality and reduce token use?

### Quality

Long agent sessions grow quickly with tool output, reasoning, corrections, and finished-subtask detail. Research shows that models can use information unevenly by position and can degrade when related facts are far apart; in practice, a growing transcript can contribute to missed constraints, stale assumptions, contradictory edits, and unsupported details. The effect depends on the model, prompt, and task, so Baton assumes no universal token threshold or sudden context cliff.

Baton gives each fresh worker one scoped task and a generated capsule containing its objective, acceptance criteria, restrictions, verification, latest retry feedback, and summaries of explicitly referenced worker memory. The same capsule appears at both prompt edges, related constraints remain adjacent, and workers re-read phase briefs before editing, verification, and reporting. The orchestrator then reviews bounded evidence—the report, declared and observed paths, and Git diff—rather than trusting completion text alone. Fresh context, narrow scope, evidence review, and edge placement reduce avoidable context pressure; they cannot repair an incorrect task specification or guarantee a correct implementation.

No cited study or Baton benchmark directly compares GPT 5.6 Max with GPT 5.6 Sol at xhigh. Nominal context capacity does not mean that every part of a long context is used uniformly: routing a scoped task to a fresh GPT 5.6 Sol at xhigh worker may reduce irrelevant live context, while GPT 5.6 Max may make direct execution preferable for some goals. Baton does not claim that either route universally wins.

### Token consumption

In a single growing conversation, completed-task detail becomes dead context: it may remain in the model's logical input and context window, and depending on provider caching and pricing, may also be billed again on later requests. Baton starts each worker with a fresh task context, while the orchestrator receives the worker's report and relevant diff instead of the worker's full transcript.

This can reduce repeated irrelevant input on multi-task goals, but every worker also incurs harness and Baton context. Small goals can cost fewer tokens when executed directly.

### Why not just summarize?

Whole-history summarization is useful, but it is lossy: a broad paraphrase can omit a negation, qualifier, failed approach, or exact acceptance condition, and repeated summaries can compound that loss. It also begins with the entire transcript rather than deciding what the next task actually needs.

Baton selectively generates each capsule from named task-spec sections and referenced-memory summaries, keeps related items together, and repeats the resulting capsule verbatim at both worker-prompt edges. Its orchestrator handoff is separately bounded and generated from current task state; it is not a compressed copy of the whole conversation. The distinction is selective task context plus bounded state transfer, not a claim that summarization is inherently ineffective.

### Research

Primary studies show systematic primacy/recency or U-shaped position effects in several long-context settings, while newer multi-piece evaluation finds that distance between related facts can be a sharper problem than middle position alone. Separate experiments find that re-reading or restating the input can improve comprehension and reasoning, which supports giving a model a second pass over compact, related instructions. Together with practitioner guidance on boundary placement and extracting relevant material, this makes Baton's capsule layout a reasonable engineering choice. None of these sources evaluates Baton, and their results across retrieval, summarization, in-context learning, and reasoning tasks do not establish a universal threshold, a guaranteed compliance gain, or a Baton effect size. Fresh-worker quality and token savings are therefore testable design inferences whose value must exceed Baton's measured activation overhead.

The detailed claim-to-source analysis and limitations are in [Long-context research synthesis](docs/research-synthesis.md) and [Context placement rationale](docs/context-placement.md).

### Research sources

- Liu et al., [“Lost in the Middle: How Language Models Use Long Contexts”](https://arxiv.org/abs/2307.03172) — peer-reviewed TACL paper and primary study.
- Hsieh et al., [“Found in the Middle: Calibrating Positional Attention Bias Improves Long Context Utilization”](https://aclanthology.org/2024.findings-acl.890/) ([arXiv](https://arxiv.org/abs/2406.16008)) — peer-reviewed Findings of ACL 2024 paper and primary study.
- Tian et al., [“Distance between Relevant Information Pieces Causes Bias in Long-Context LLMs”](https://arxiv.org/abs/2410.14641) — peer-reviewed Findings of ACL 2025 paper and primary study.
- Xu et al., [“Re-Reading Improves Reasoning in Large Language Models”](https://arxiv.org/abs/2309.06275) — peer-reviewed EMNLP 2024 paper and primary study.
- Mekala, Razeghi, and Singh, [“EchoPrompt: Instructing the Model to Rephrase Queries for Improved In-context Learning”](https://aclanthology.org/2024.naacl-short.35/) ([arXiv](https://arxiv.org/abs/2309.10687)) — peer-reviewed NAACL 2024 short paper and primary study.
- Guo and Vosoughi, [“Serial Position Effects of Large Language Models”](https://aclanthology.org/2025.findings-acl.52/) — peer-reviewed Findings of ACL 2025 paper and primary study.
- Han et al., [“Read Before You Think: Mitigating LLM Comprehension Failures with Step-by-Step Reading”](https://arxiv.org/abs/2504.09402) — primary preprint; the linked page does not identify peer review.
- Anthropic, [“Prompt engineering for Claude's long context window”](https://www.anthropic.com/news/prompting-long-context) — practitioner guidance, not peer-reviewed research.
- A. Laurent, [“LLM Position Bias: Primacy and Recency Effects in Prompts”](https://intuitionlabs.ai/articles/llm-position-bias-primacy-recency-effects) — secondary synthesis, not primary research.
- David William Silva, [“Lost in the Middle: The Context Crisis of LLMs”](https://davidwsilva.substack.com/p/lost-in-the-middle-the-context-crisis) — secondary article, not primary research.

## Requirements

### Generate Baton from a prompt

A coding agent that can create files and run local verification can generate Baton from `prompts/create-framework.md`; use a fresh agent with `prompts/improve-framework.md` to audit and repair the result. The generated framework requires Python 3.11 or newer, Git, and macOS or Linux.

### Run the ready-to-use framework

The ready version requires Python 3.11 or newer, Git on `PATH`, macOS or Linux, and a Git worktree without tracked submodules. Baton has no third-party Python dependencies.

### Supported agent harnesses

The interactive orchestrator needs file and command access. Worker routing accepts a configurable noninteractive prompt command: the included configuration documents Hermes Agent, Claude Code, and Codex examples, while OpenCode and other CLI agents can be used when their locally verified noninteractive invocation accepts one prompt or prompt-file argument. Baton does not install agents, credentials, models, wrappers, or routing profiles.

### Measured framework token usage

The revision recorded in [Activation context footprint](docs/context-footprint.md) reproducibly measures the Baton-authored activation payload: `prompts/use-framework.md`, the freshly installed orchestrator manual, and a generated start brief after `hard`, `medium`, and `easy` are configured. It excludes the host harness's base prompt and tool schemas, unrelated saved memory, source code, task specs, worker prompts, and later capsules.

The startup communication changed after the previously recorded live provider differential, so Baton no longer applies those stale exact token counts to the current payload. The measurement command reports exact characters, UTF-8 bytes, lines, and SHA-256 plus a clearly labeled standard-library offline estimate and range. New provider counts require genuine bracketing baseline/payload/baseline evidence for these exact bytes.

Activation is overhead. If a goal will probably use fewer direct-execution tokens than the applicable footprint, run it directly; use Baton when decomposition, fresh-worker focus, parallelism, review, or risk control is expected to justify that cost.

## Install

### Build from the prompt

Get the generation and review prompts:

```bash
git clone https://github.com/jpawchan/baton
cd baton
```

Open `prompts/create-framework.md` from the checkout, start a coding agent in
the target project's Git root, and give it that prompt. Then give
`prompts/improve-framework.md` to a fresh agent in the same target. The first
prompt contains the normative specification; the second requires implementation
and safety checks rather than assuming the first result is correct.

### Install the ready-to-use version

```bash
git clone https://github.com/jpawchan/baton
cd baton
framework/baton init /path/to/project
```

`init` installs the local, Git-ignored `.baton/` runtime in the target project's Git root.

## How to use

1. Install Baton, then tell the main coding agent to read `.baton/orchestrator.md` and run:

   ```bash
   .baton/baton orchestrator brief --phase start
   .baton/baton validate
   .baton/baton tiers
   ```

2. Answer both copy-ready start questions before planning: whether the orchestrator should use existing harness memory/project rules or move to a fresh session, and whether to keep or change the current model/reasoning preferences for `hard`, `medium`, and `easy`. A fresh session is usually preferable for a new goal, but preserve session-only facts in project memory or a close handoff first. Baton launches each worker in a fresh task process/context; only commands configured with the harness's isolation option also suppress persistent harness memory and project rules. The included Hermes command does so with `--ignore-rules`.

3. After an explicit preference answer, configure and verify all three worker levels in `.baton/config.toml`. The documented defaults are GPT 5.6 Sol/high for `hard`, GPT 5.6 Sol/medium for `medium`, and Claude Code Opus 4.8/xhigh for `easy`, with GPT 5.6 Terra/high only when Claude usage is exhausted. Preserve or create the wrappers/profiles that make those choices real, then run `validate` and `tiers` and restate the effective settings. Baton does not register models, select effort, implement fallback, or infer truthful display metadata from commands.

4. Describe the goal. The orchestrator assigns one explicit configured difficulty to every task, previews generated context, runs non-conflicting workers, and reviews evidence before acceptance. Its core commands are:

   ```bash
   .baton/baton task create --title "Add email validation" --scope "src/auth/**" --tier hard
   .baton/baton task capsule T001-add-email-validation
   .baton/baton run --dry-run
   .baton/baton run
   .baton/baton orchestrator brief --phase review T001-add-email-validation
   ```

5. When the request is complete, count only the workers used for that request by
   passing every task id the orchestrator created for it:

   ```bash
   .baton/baton stats --task T001-add-email-validation --task T002-add-tests
   ```

   Copy the command's single sentence into the final response. It counts retries
   as additional workers and reports the hard, medium, easy, and—when needed—
   other-level breakdown. If the request created no Baton task, say: `I used 0
   workers for this request: 0 on hard, 0 on medium, and 0 on easy.`

6. Before ending an orchestrator session, run a close brief with a concrete next-session goal:

   ```bash
   .baton/baton orchestrator brief --phase close --goal "Continue with the next concrete objective"
   ```

   The close brief also reports all recorded worker launches in this Baton
   runtime for continuity and audit. That fallback may span several user
   requests; do not present it as the request-scoped count.

Optional Claude Code hooks can inject the start brief at session start and after compaction, and inject bounded current next actions before each user prompt:

```bash
.baton/baton hooks claude-code
.baton/baton hooks claude-code --write
```

The hook merge is idempotent and preserves existing hook arrays. Do not use Claude Code's `--bare` mode with this integration because that mode disables hooks.

## What is in this repository?

| Path | Contents |
| --- | --- |
| `framework/baton` | Ready-to-use Baton CLI. |
| `framework/orchestrator.md` | Installed orchestrator workflow and review guidance. |
| `framework/worker.md` | Installed worker contract and report format. |
| `framework/config.example.toml` | Installed worker, tier, limit, and gate configuration template. |
| `framework/memory.md` | Installed indexed-memory template. |
| `prompts/create-framework.md` | Standalone framework-generation prompt containing the normative specification. |
| `prompts/improve-framework.md` | Prompt for independently testing and repairing a generated implementation. |
| `prompts/use-framework.md` | Short prompt for activating an installed orchestrator. |
| `skill/SKILL.md` | Portable skill metadata and operating guidance. |
| `docs/context-placement.md` | Capsule-placement rationale, tradeoffs, and limits. |
| `docs/research-synthesis.md` | Long-context evidence synthesis and source notes. |
| `docs/context-footprint.md` | Reproducible activation-context measurement and break-even guidance. |
| `docs/bug-audit.md` | Correctness audit, reproductions, and fix dispositions. |
| `docs/performance.md` | Profiling method, benchmark results, and rejected optimizations. |
| `docs/github-description.txt` | Short GitHub repository description. |
| `tools/` | Standard-library measurement and benchmark scripts plus explicitly retired historical provider evidence. |
| `tests/test_baton.py` | End-to-end Baton test suite. |
| `tests/test_context_footprint.py` | Activation-footprint reproducibility tests. |
| `SPEC.md` | Normative behavior and safety contract. |
| `summary.md` | Code-verified maintainer guide. |
| `.github/workflows/ci.yml` | Python 3.11/3.13 test matrix for macOS and Ubuntu. |
| `LICENSE` | MIT license text. |

## License

MIT. See [LICENSE](LICENSE).