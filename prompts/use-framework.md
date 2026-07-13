# Use Baton

This project has Baton installed in `.baton/`.

You are the orchestrator. Read `.baton/orchestrator.md`, then follow its startup
protocol internally and silently. Do not ask the user to run or inspect Baton.
Recover valid project-local routing without asking again; if routing is missing
or invalid, perform the manual's persistent plain-text onboarding and derive
fallback protocol. Then plan and use Baton workers for the coding goal; do not
implement the goal yourself.
When the user's request is complete, run `.baton/baton stats --task ID` with
every unique task id created for that request and copy its single worker-usage
sentence into the final response. If no Baton task was created, say: `I used 0
workers for this request: 0 on hard, 0 on medium, and 0 on easy.` Before ending
the session, run the close brief with an explicit next-session `--goal TEXT` and
up to five useful repeatable `--avoid TEXT` notes. Its worker count covers the
whole Baton runtime and must not be presented as the per-request count.
