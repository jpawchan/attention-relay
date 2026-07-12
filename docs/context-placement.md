# Context placement rationale

Attention Relay places one generated Critical Context Capsule verbatim at both edges of its worker launch prompt. Here, "edges" means the beginning and end of the launch prompt that Relay controls. It does not mean the absolute edges of the model's context. Host system prompts, tool schemas, and other wrappers can surround Relay's prompt. Of the two capsule copies, the trailing copy is the one nearest the generation boundary.

## Why the same capsule appears twice

Re-reading the same text gives a model a second, globally informed pass over it. RE2 reports benefits from this pattern on question-answering and reasoning tasks. Work on information position in long contexts also finds U-shaped behavior in which the beginning and end are often privileged relative to the middle. These benchmark results are suggestive for this harness, not proof that dual-edge placement improves every Relay task. Applying them to compliance-oriented worker prompts is a design judgment.

Relay uses byte-identical copies so their equality can be checked by digest. Because both are generated from the same capsule, the two copies cannot drift from each other. This guarantees only that the copies match. It does not guarantee that the source task specification is correct, complete, or current.

## Alternatives not adopted

Relay does not paraphrase the trailing copy of gating text. A paraphrase can weaken negation, qualifiers, or scope. Its variation would also make the result nondeterministic and harder to audit. EchoPrompt reports general benefits from paraphrasing, but that result does not make paraphrase suitable for compliance text whose exact constraints matter.

Relay also does not split the capsule into leading and trailing halves by default. Each item would then receive only one edge position, while primacy and recency dominance varies with the model and context length. Splitting would also remove the re-read benefit. Under a hard token budget, selectively duplicating only failure-critical items is a legitimate but unexplored alternative.

The trailing copy is not mirrored into reverse section order. There is no direct empirical study establishing that reversal would help. Reversal can break discourse order, such as placing a correction before the rule it qualifies. It would also combine two changes, order and repetition, making any outcome hard to attribute. The current section order already approximates a useful primacy/recency gradient: Task, Objective, and Acceptance criteria are near the leading edge; Verification, Referenced memory, and Retry delta are near the trailing edge.

## Importance and future evaluation

Importance is structural and human-decided. The task specification's sections provide the ranking rather than an inferred importance score. Referenced memory and the newest retry feedback join that generated placement when present.

`relay stats` provides operational evidence such as attempt counts, failure codes, and phase-receipt coverage. It is explicitly not a placement evaluator. A future placement experiment must attach per-task layout or treatment labels, predeclare an outcome rubric, and control for model, task type, prompt length, and retries. Without those preconditions, differences cannot be attributed to placement.

## Sources

- Lost in the Middle (arXiv 2307.03172)
- Found in the Middle (arXiv 2406.16008)
- Distance-bias study (arXiv 2410.14641)
- Re-Reading/RE2 (arXiv 2309.06275)
- EchoPrompt (arXiv 2309.10687)
- Serial Position Effects of LLMs (arXiv 2406.15981; ACL Findings 2025)
- Read Before You Think (arXiv 2504.09402)
- Anthropic long-context prompting guidance
