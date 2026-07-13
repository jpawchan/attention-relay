---
name: baton
description: "Coordinate fresh, scoped coding agents with generated context capsules and evidence-bound diff review."
version: 0.3.0
author: JPawchan
license: MIT
metadata:
  hermes:
    tags: [coding-agents, orchestration, delegation, code-review, token-efficiency]
    related_skills: [hermes-agent, codex, opencode]
---

# Baton

Use Baton when a coding goal should be split across fresh workers without
losing central review. Do not use it for a single small edit where delegation
costs more than it saves.

The activation overhead is revision- and harness-specific. Read
`docs/context-footprint.md` for the current reproducible byte measurement and
offline estimate; no live provider count is claimed for the current payload.
Use direct execution when a small goal is unlikely to justify that cost.

## Install

```bash
git clone https://github.com/jpawchan/baton
cd baton
framework/baton init /path/to/project
```

Requirements: Git, Python 3.11+, macOS or Linux, and a worktree without tracked
submodules.

Then tell the main coding agent to read `.baton/orchestrator.md`; it runs the
start brief internally and silently. A fresh project asks once for explicit
project-local hard, medium, and easy model/reasoning routes. Valid later sessions
recover those routes without asking again and state that settings can change at
any time. Missing or invalid routing uses the manual's persistent plain-text
question, capability discovery, consent-before-lowering, and no-consent fallback.
A copy-ready instruction is in `prompts/use-framework.md`.

Hermes Agent, Claude Code, Codex, OpenCode, and other noninteractive CLI agents
can be workers when their locally verified command accepts one prompt or prompt
file argument. Optional host hooks are specific to Claude Code.

To generate the same framework instead of copying it, use
`prompts/create-framework.md`, then review the result with
`prompts/improve-framework.md`.

## Preserve these rules

- Tasks have explicit scopes and dependencies.
- Only non-overlapping tasks run together.
- Workers submit results and exact changed paths; Baton checks declarations
  against scoped diffs before the orchestrator approves them.
- Changes to Git-visible files outside a wave’s scopes block approval; workers
  never modify Git-ignored files.
- Memory contains durable project facts, not task history.
- Fresh config contains no worker command or tier; every task tier is explicit,
  configured, and project-local. There is no `default` route.
- Executable commands or wrappers must implement displayed model/reasoning
  settings; metadata alone is never routing.
- Startup and compaction use the same route-validity rule and never ask a
  harness-memory or fresh-session question.
- Request completion uses `stats --task ID` for every task created for that
  request; the final response copies its hard/medium/easy worker breakdown.
- Close briefs retain a separately labeled runtime-wide count for continuity,
  never as a substitute for the request-scoped sentence.
- The runtime remains local and Git-ignored, and Baton adds no third-party
  Python packages.
