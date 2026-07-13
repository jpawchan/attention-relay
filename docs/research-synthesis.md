# Long-context research synthesis

This note grounds Baton's two central design bets — placing a compact Critical
Context Capsule at both edges of a worker prompt, and delegating scoped work to
fresh workers instead of one growing transcript — in the long-context
literature. It states plainly what the sources establish, what is only a design
inference, and what Baton does not promise. Every source below was opened and
its title, authorship, and central claim were checked against the linked page,
not a snippet.

See [Context placement rationale](context-placement.md) for the resulting Baton
layout decisions and [Activation context footprint](context-footprint.md) for
the separate, revision-specific token-cost measurement.

## Conclusion

The evidence robustly supports the premise Baton is built on: transformer LLMs
attend unevenly by position, favoring the beginning and end of their input over
the middle (Guo & Vosoughi 2025; Hsieh et al. 2024), and a second, globally
informed pass over the same input — re-reading or controlled repetition —
measurably improves comprehension and reasoning (Xu et al. 2024; Han et al.
2025; Mekala et al. 2024). Placing failure-critical constraints at both prompt
edges and repeating them verbatim is therefore a reasonable way to align a
model's positional salience with the instructions that actually matter, and
practitioner guidance for putting the operative request near a boundary and
extracting only relevant material points the same direction (Anthropic 2023).
What the literature does **not** give Baton is a guarantee: the published gains
come from other models and tasks (retrieval, RAG, math word problems, label
selection) and do not transfer automatically to compliance-style worker prompts;
newer models are already fairly robust to the classic "lost in the middle" drop,
with the sharper remaining penalty coming from *distance between* related pieces
rather than mere middle position (Tian et al. 2025); and no source establishes a
universal token threshold or cliff. Baton's win is best understood as keeping
each worker's live, related constraints compact, adjacent, edge-placed, and
re-read — a bet consistent with the evidence, not a proven quality or
token-savings result, and one that cannot rescue an incorrect or incomplete task
spec.

## What the evidence shows

**Positional bias is real, systematic, and mostly primacy/recency-shaped.**
Guo & Vosoughi (2025) document serial position effects — primacy and recency
biases familiar from human psychology — across GPT-family, Llama 2, and T5
models on option-selection and multi-document summarization, with primacy the
more pervasive; they recommend, among other mitigations, placing crucial
information at the start of the prompt. Hsieh et al. (2024) give a mechanistic
account: LLMs carry a *U-shaped attention bias* that gives tokens at the
beginning and end higher attention "regardless of their relevance." That last
phrase is the honest double edge — edge positions are privileged whether or not
the content deserves it, so putting genuinely relevant gating text there is a
way to make salience and relevance coincide, not evidence that any text at the
edges is understood better.

**The "middle" penalty is model-dependent, and distance is the sharper effect.**
Tian et al. (2025) build LongPiBench and test five commercial and six
open-source models with *multiple* relevant pieces. They find most current
models are fairly robust to the single-fact lost-in-the-middle problem, but
degrade significantly as the *spacing between* relevant pieces grows. This both
qualifies the older lost-in-the-middle framing and supports a specific Baton
choice: keep related constraints together and compact rather than scattered.

**Retrieval and reasoning are distinct axes.** The position effects above are
measured largely on retrieval- and selection-style behavior — finding the
relevant passage, choosing a label, ranking, RAG. Reasoning gains, by contrast,
come from interventions that change how the model *reads*: Xu et al. (2024) show
that re-reading the question as input (their RE2 method, a second pass that
lends decoder-only models a "bidirectional" view) consistently improves
reasoning across 14 datasets and is compatible with chain-of-thought; Han et al.
(2025) argue many failures are comprehension failures, not logic failures, and
that increasing the proportion of question-related tokens (via repetition)
"refocuses attention," while backward dependencies remain a bottleneck for
decoder-only models even with chain-of-thought. Mekala et al. (2024) show a
related repetition mechanism — instructing the model to restate the query before
answering — improving in-context learning. So placement chiefly governs *whether
the right instruction is attended*; re-reading chiefly improves *comprehension
of it*. Baton uses both levers.

**Structured long-context prompting has practitioner backing.** Anthropic's 2023
guidance recommends putting the operative query/instructions after long input,
pulling relevant quotes into a scratchpad before answering, and referring to
material by specific identifiers rather than "this document"; it reports a Claude
2 improvement from 0.939 to 0.961 accuracy (a ~36% reduction in errors) on its
task. This is engineering guidance, not a controlled study, but it converges
with the primary findings on where to place the ask and on extracting only what
matters.

## How this maps to Baton, and what is inference

Baton compiles a Critical Context Capsule from the task spec's structured
sections (Objective, Acceptance criteria, Not allowed, Verification, latest
feedback) plus short summaries of a few referenced memory entries, and places a
byte-identical copy at both edges of the worker prompt, with the trailing copy
nearest the generation boundary.

- **Edge placement + verbatim repetition** map directly onto primacy/recency
  (Guo & Vosoughi 2025), the U-shaped attention bias (Hsieh et al. 2024), and
  the re-reading benefit (Xu et al. 2024; Han et al. 2025). That the mechanisms
  exist is evidence-backed; that this *particular* layout improves *Baton
  worker* compliance is a design inference, not a measured result, because none
  of these studies evaluates dual-edge compliance prompting.
- **Verbatim, not paraphrased.** EchoPrompt (Mekala et al. 2024) shows that
  having the model rephrase a query can help reasoning, yet Baton deliberately
  keeps the trailing copy byte-identical: a paraphrase can weaken a negation,
  qualifier, or scope boundary, and exact constraints are the point of gating
  text. Choosing repetition's benefit while refusing paraphrase for compliance
  text is a judgment call, not something these papers prescribe.
- **Rapid context growth in agentic work.** As an agent runs, its transcript
  accumulates tool output, prior reasoning, and finished-subtask chatter. The
  position and distance findings *imply* — but do not prove — that burying live
  constraints inside that growth, and spreading related constraints apart, makes
  them less reliably attended. Crucially, no cited source sets a universal token
  threshold or "cliff," so Baton claims none; the response of handing each
  worker a small, fresh, scoped context is a bet consistent with the evidence.
- **Dead completed-task context.** Baton's orchestrator delegates each task to a
  separate worker whose context is the capsule plus its own scope, so completed
  tasks' details do not ride along as stale middle-of-context material competing
  for attention. This is the same inference applied to cross-task memory: sound
  in direction, unmeasured in magnitude here.
- **Why a selective capsule differs from summarizing the whole transcript.** A
  transcript summary is a single, lossy, paraphrased digest of everything that
  happened, placed once. A Baton capsule is scoped to what *this* task needs,
  kept verbatim so exact constraints survive, kept compact so related items stay
  adjacent (addressing the distance effect of Tian et al. 2025), and repeated at
  both edges (addressing primacy/recency and the re-read benefit). The
  difference is not "shorter vs longer" — it is verbatim-and-scoped-and-edged
  versus paraphrased-and-global-and-buried.

## What Baton does not guarantee

- No transfer of specific numbers. Hsieh et al.'s up-to-10-point RAG
  improvement (2024), EchoPrompt's +5%/+13% figures (Mekala et al. 2024), and
  the 0.939→0.961 result (Anthropic 2023) are from other models, tasks, and
  prompting regimes; they motivate the design but are not Baton's expected
  effect size.
- No universal cliff. None of these sources supports a fixed context length
  (such as 100k tokens) beyond which quality collapses under stated conditions,
  so this note asserts no such threshold.
- Diminishing marginal benefit on robust models. Tian et al. (2025) find many
  current models already handle single-fact middle placement well, so the
  primacy/recency lever may buy less than it once did — while their distance
  finding still favors compact, adjacent constraints.
- Placement cannot fix content. Edge placement and repetition raise the odds a
  constraint is attended and understood; they do nothing for a spec that is
  wrong, incomplete, or internally inconsistent.
- These are correlational/benchmark results, not causal claims about Baton.
  Validating the capsule layout itself would require a controlled experiment
  with per-task layout labels, a predeclared rubric, and controls for model,
  task type, and prompt length.

## Source notes

Classification, verified metadata, the claim each source supports here, and the
link. Primary peer-reviewed papers, practitioner guidance, and secondary
syntheses are marked distinctly; secondary articles are never treated as primary
evidence. All URLs below resolved when checked.

**Primary, peer-reviewed**

- **Hsieh et al., "Found in the Middle: Calibrating Positional Attention Bias
  Improves Long Context Utilization."** Findings of ACL 2024
  (2024.findings-acl.890); preprint arXiv 2406.16008. Establishes a U-shaped
  *attention* bias (edges attended more "regardless of their relevance") as a
  cause of lost-in-the-middle, and a calibration method, *found-in-the-middle*,
  that restores relevance-faithful attention. Two distinct numbers, not to be
  conflated: the published abstract reports improved retrieval-augmented
  generation "outperforming existing methods by up to 10 percentage points,"
  while the separate middle-position result is that, when the gold document is
  placed mid-sequence, calibration improves over the uncalibrated baseline by
  6–10 pp (the earlier arXiv preprint states these two figures as 15 pp and
  6–15 pp respectively). → Supports the mechanistic basis for edge placement,
  and its honest limit (edge attention is relevance-blind).
  <https://aclanthology.org/2024.findings-acl.890/>,
  <https://arxiv.org/abs/2406.16008>
- **Tian et al., "Distance between Relevant Information Pieces Causes Bias in
  Long-Context LLMs."** arXiv 2410.14641; Findings of ACL 2025. Introduces
  LongPiBench; tests five commercial and six open-source models; finds most are
  robust to classic lost-in-the-middle but biased by the *spacing* of multiple
  relevant pieces. → Supports keeping related constraints compact and adjacent;
  qualifies the middle-penalty framing for current models. <https://arxiv.org/abs/2410.14641>
- **Xu et al., "Re-Reading Improves Reasoning in Large Language Models" (RE2).**
  arXiv 2309.06275; EMNLP 2024 (Main). A second pass over the question gives
  decoder-only models a "bidirectional" view; consistent reasoning gains across
  14 datasets / 112 experiments, compatible with chain-of-thought. → Supports
  repeating the capsule verbatim as a second, globally informed pass.
  <https://arxiv.org/abs/2309.06275>
- **Guo & Vosoughi, "Serial Position Effects of Large Language Models."**
  Findings of ACL 2025, pp. 927–953 (paper 52); also arXiv 2406.15981.
  Documents primacy and recency biases across GPT-family, Llama 2, and T5 on
  option-selection and multi-news summarization, with primacy predominant;
  recommends placing crucial information early, among other mitigations. →
  Supports edge placement, especially the leading edge. <https://aclanthology.org/2025.findings-acl.52/>
- **Mekala, Razeghi & Singh, "EchoPrompt: Instructing the Model to Rephrase
  Queries for Improved In-context Learning."** NAACL 2024, Volume 2: Short
  Papers (2024.naacl-short.35); preprint arXiv 2309.10687. Prompting the model
  to restate its query before answering improves in-context learning across
  four families of causal language models; on average it raises
  code-davinci-002's zero-shot chain-of-thought accuracy by +5% on numerical
  tasks (e.g., GSM8K, SVAMP) and +13% on reading comprehension (e.g., DROP). →
  Supports the repetition/restate-before-answering mechanism; Baton adopts the
  repetition while deliberately keeping its compliance text verbatim rather than
  paraphrased. <https://aclanthology.org/2024.naacl-short.35/>,
  <https://arxiv.org/abs/2309.10687>

**Primary, preprint (not yet shown as peer-reviewed at the linked page)**

- **Han et al., "Read Before You Think: Mitigating LLM Comprehension Failures
  with Step-by-Step Reading" (SSR/SSR++).** arXiv 2504.09402. Argues many
  failures are comprehension, not logic; raising the proportion of
  question-related tokens via repetition "refocuses attention"; backward
  dependencies remain a bottleneck for decoder-only models even with
  chain-of-thought. → Explains *why* a trailing re-read near the generation
  boundary and a leading copy both help. <https://arxiv.org/abs/2504.09402>

**Practitioner guidance (not peer-reviewed)**

- **Anthropic, "Prompt engineering for Claude's long context window" (2023).**
  Recommends placing the operative query after long inputs, extracting relevant
  quotes to a scratchpad before answering, and using specific identifiers over
  "this document"; reports Claude 2 accuracy 0.939 → 0.961 (~36% fewer errors)
  on its task. → Supports trailing-edge placement of the ask and
  extract-what-matters over carry-everything. <https://www.anthropic.com/news/prompting-long-context>

**Secondary synthesis (cites others; not original or peer-reviewed research)**

- **IntuitionLabs (A. Laurent), "LLM Position Bias: Primacy and Recency Effects
  in Prompts."** A review consolidating peer-reviewed work (e.g., Wang et al.,
  EMNLP 2023; Wu et al., ICML 2025) into prompt-placement guidance; notes, for
  example, a ChatGPT first-label preference around 65.5% in one cited
  experiment; states no token cliff. Used here only as corroborating context and
  a pointer to primary work, not as evidence itself. <https://intuitionlabs.ai/articles/llm-position-bias-primacy-recency-effects>
- **David William Silva, "Lost in the Middle: The Context Crisis of LLMs"
  (Substack, 2025).** A popular-audience explainer of the lost-in-the-middle
  phenomenon (popularizing Liu et al.'s "Lost in the Middle: How Language Models
  Use Long Contexts") and of the U-shaped curve; its source attributions are
  loose (e.g., paraphrased institution labels) and it repeats a secondhand
  Claude 2.1 "27%→98%" prompt-nudge figure that this note did not verify against
  a primary Anthropic source and therefore does not rely on. Treated strictly as
  a secondary framing of the primary papers above. <https://davidwsilva.substack.com/p/lost-in-the-middle-the-context-crisis>
