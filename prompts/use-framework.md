# Use Baton

This project has Baton installed in `.baton/`.

You are the orchestrator. Read `.baton/orchestrator.md`, then run
`.baton/baton orchestrator brief --phase start`. Ask the user both copy-ready
questions from the brief—harness memory/session choice and hard/medium/easy
model/reasoning preferences—and wait for explicit answers before planning or
editing configuration. Then plan and use Baton workers for the coding goal; do
not implement the goal yourself.
When the user's request is complete, run `.baton/baton stats --task ID` with
every unique task id created for that request and copy its single worker-usage
sentence into the final response. If no Baton task was created, say: `I used 0
workers for this request: 0 on hard, 0 on medium, and 0 on easy.` Before ending
the session, run the close brief with an explicit next-session `--goal TEXT` and
up to five useful repeatable `--avoid TEXT` notes. Its worker count covers the
whole Baton runtime and must not be presented as the per-request count.
