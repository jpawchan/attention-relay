# Context placement rationale

Baton places one generated Critical Context Capsule verbatim at both edges of its worker launch prompt. Here, "edges" means the beginning and end of the launch prompt that Baton controls. It does not mean the absolute edges of the model's context. Host system prompts, tool schemas, and other wrappers can surround Baton's prompt. Of the two capsule copies, the trailing copy is the one nearest the generation boundary.

## Why the same capsule appears twice

Re-reading the same text gives a model a second, globally informed pass over it. RE2 reports benefits from this pattern on question-answering and reasoning tasks. Work on information position in long contexts also finds U-shaped behavior in which the beginning and end are often privileged relative to the middle. These benchmark results are suggestive for this harness, not proof that dual-edge placement improves every Baton task. Applying them to compliance-oriented worker prompts is a design judgment.

Baton uses byte-identical copies so their equality can be checked by digest. Because both are generated from the same capsule, the two copies cannot drift from each other. This guarantees only that the copies match. It does not guarantee that the source task specification is correct, complete, or current.

## Alternatives not adopted

Baton does not paraphrase the trailing copy of gating text. A paraphrase can weaken negation, qualifiers, or scope. Its variation would also make the result nondeterministic and harder to audit. EchoPrompt reports general benefits from paraphrasing, but that result does not make paraphrase suitable for compliance text whose exact constraints matter.

Baton also does not split the capsule into leading and trailing halves by default. Each item would then receive only one edge position, while primacy and recency dominance varies with the model and context length. Splitting would also remove the re-read benefit. Under a hard token budget, selectively duplicating only failure-critical items is a legitimate but unexplored alternative.

The trailing copy is not mirrored into reverse section order. There is no direct empirical study establishing that reversal would help. Reversal can break discourse order, such as placing a correction before the rule it qualifies. It would also combine two changes, order and repetition, making any outcome hard to attribute. The current section order already approximates a useful primacy/recency gradient: Task, Objective, and Acceptance criteria are near the leading edge; Verification, Referenced memory, and Retry delta are near the trailing edge.

## Importance and future evaluation

Importance is structural and human-decided. The task specification's sections provide the ranking rather than an inferred importance score. Referenced memory and the newest retry feedback join that generated placement when present.

`.baton/baton stats` provides operational evidence such as attempt counts, failure codes, and phase-receipt coverage. It is explicitly not a placement evaluator. A future placement experiment must attach per-task layout or treatment labels, predeclare an outcome rubric, and control for model, task type, prompt length, and retries. Without those preconditions, differences cannot be attributed to placement.

## Sources

The source classifications, claim mapping, and transfer limits are developed in
[Long-context research synthesis](research-synthesis.md).

- Liu et al., [“Lost in the Middle: How Language Models Use Long Contexts”](https://arxiv.org/abs/2307.03172) — peer-reviewed TACL paper.
- Hsieh et al., [“Found in the Middle: Calibrating Positional Attention Bias Improves Long Context Utilization”](https://aclanthology.org/2024.findings-acl.890/) — peer-reviewed Findings of ACL 2024 paper.
- Tian et al., [“Distance between Relevant Information Pieces Causes Bias in Long-Context LLMs”](https://arxiv.org/abs/2410.14641) — peer-reviewed Findings of ACL 2025 paper.
- Xu et al., [“Re-Reading Improves Reasoning in Large Language Models”](https://arxiv.org/abs/2309.06275) — peer-reviewed EMNLP 2024 paper.
- Mekala, Razeghi, and Singh, [“EchoPrompt: Instructing the Model to Rephrase Queries for Improved In-context Learning”](https://aclanthology.org/2024.naacl-short.35/) — peer-reviewed NAACL 2024 short paper.
- Guo and Vosoughi, [“Serial Position Effects of Large Language Models”](https://aclanthology.org/2025.findings-acl.52/) — peer-reviewed Findings of ACL 2025 paper.
- Han et al., [“Read Before You Think: Mitigating LLM Comprehension Failures with Step-by-Step Reading”](https://arxiv.org/abs/2504.09402) — primary preprint.
- Anthropic, [“Prompt engineering for Claude's long context window”](https://www.anthropic.com/news/prompting-long-context) — practitioner guidance.
