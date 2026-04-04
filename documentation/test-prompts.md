# Test Prompts

Here are some prompts we used to generate some of the documents seen in documentation/example_research_output.

## Azure Solutions Agent

### IT Centralization

I need to centralize the applications IT manages. They are a mix of modern and legacy systems. We want to containerize them and have the ability to scale-up and scale-down. we have need of a service bus for app messaging and need alerts based on high usage and or errors in the application itself.

## Deep Research Prompts

### Pre-Fill

Research how RAG, Vector based, and Memory based pre-fill for system prompts work. Give a Summary of how each works with diagrams, Give pros and cons of each approach. Give a combined strResearch how RAG, Vector based, and Memory based pre-fill for system prompts work. Give a Summary of how each works with diagrams, Give pros and cons of each approach. Give a combined strategy for using all three.

### Autonomous Agents

Compare autonomous agent architectures: ReAct, Plan-and-Execute, and Tree of Thoughts. Analyze each framework's decision-making loop, failure recovery mechanisms, and token efficiency. Include a decision matrix for when to use each pattern in production systems.

### Agent Communication

Compare A2A against a simple inbox pattern and a third commonly used pattern for communication among agent teams of your choice. Compare and contrast the differences and the pros and cons of each.

### 3 Fine Tuning Approaches

Compare and contrast three approaches to fine-tuning large language models: Full Fine-Tuning, LoRA/QLoRA (parameter-efficient), and RLHF/DPO (alignment-based). For each method, explain how it works mechanically, what data requirements and compute costs look like, and where it excels vs. falls short. Include a decision matrix for when to use each based on dataset size, budget, and use case. Provide concrete testing and evaluation recommendations for each approach — how to detect overfitting, catastrophic forgetting, and alignment drift, with specific metrics and benchmark strategies.

### Data into Fabric for Warehousing

Compare sqlmesh and dbt for usage as a transitional layer to move raw/bronze to silver/gold. Also source me a third option (like data bricks). How would these help or work on fabric lakehouse => fabric lakehouse or sql => fabric lakehouse. Can they be used natively from Fabric? what's the right medium for their usage. Right now we use the Mirror technology that Azure provides to move to fabric our sources, but this simply brings in "raw" and doesn't account for bronze / silver. There are data flows and factories and notebooks native to Fabric but want to also consider alternatives.

rejoinder:

Add an additional section on \"Discipline for Notebooks\" solving the code sprawl concern. I like the concept of notebooks but they do get to be \"a lot\" and you brought up a good point, they are just code, so how should they be organized. Solve this and you really don't need the rest. Notebooks / Data Flows / Factories can do what you need for that silver / bronze level.

### Research Prompt Crafting

#### Combined Prompt (too large — caused 30min synthesis timeout)

Research the three primary approaches to fine-tuning custom LLMs: Full Fine-Tuning, LoRA/QLoRA (parameter-efficient fine-tuning), and RLHF/DPO (alignment fine-tuning). For each approach:

How it works — the core mechanism in 2-3 sentences
Pros — concrete advantages (cost, quality, speed, data requirements)
Cons — concrete disadvantages and failure modes
When to use it — the specific conditions that make this the right choice
Current Market Tools — The tools people are currently using to effect the fine tuning
Azure Offering — If it's available in Azure and how to do it in Azure.

Then produce a comparison section covering three real-world scenarios:

Scenario A: Fine-tuning wins over RAG — A situation where retrieval-augmented generation falls short and a custom fine-tuned model is the better solution. Explain why RAG fails here.
Scenario B: RAG wins over fine-tuning — A situation where RAG is clearly sufficient and fine-tuning would be wasteful. Explain why fine-tuning is overkill here.
Scenario C: Both together — A situation where combining a fine-tuned model with RAG produces results neither approach achieves alone. Explain what each component contributes.
For each scenario, be specific: name an industry, a use case, approximate data volumes, and the decision criteria that tip the balance.

Write a comprehensive research paper on the context window limitation in current large language models.

Executive Summary — State the core problem in business terms: what context windows are, why they matter, and what the practical ceiling is today.

Section 1: The Crux — What is the context window, how is it measured (tokens), and what are the current limits across major models (GPT-4, Claude, Gemini)? What happens when you exceed it — not theoretically, but in observable output quality?

Section 2: Memory — Machine vs. Human — Compare how LLMs "remember" (attention over a fixed window) vs. how humans remember (selective encoding, chunking, long-term retrieval). Where does the analogy hold and where does it break? Why can a human read a 500-page novel and discuss themes, but a model with 200k tokens loses the thread?

Section 3: Why Bigger Isn't Better — Explain why simply scaling the context window doesn't solve the problem. Cover the quadratic attention cost, the "lost in the middle" phenomenon (needle-in-a-haystack degradation), and the diminishing returns on retrieval accuracy as context grows. Include empirical evidence.

Section 4: Current Research Approaches — Survey the active research tackling this limitation:

Sparse attention and efficient attention mechanisms (e.g., Ring Attention, Longformer)
Retrieval-Augmented Generation (RAG) as external memory
Memory-augmented architectures (MemGPT, Infini-attention)
Compression and summarization techniques (context distillation)
State-space models as an alternative to transformers (Mamba)
For each, explain the mechanism, current results, and open problems.

Technical Addendum — Connect the sections into a unified analysis. Include a comparison table of approaches (mechanism, max effective context, compute cost, maturity). Cite primary sources — arXiv papers, conference publications (NeurIPS, ICML, ACL), and official model documentation. No blog posts or secondary summaries as primary citations.

Format: Academic structure with numbered sections, clear headings, and a references section with proper citations.

#### Broken Up Into Separate Prompts

The combined prompt above asked for two unrelated research papers in one swarm. The synthesis agent tried to write both — 19 minutes of work before the 30-minute timeout killed it. Lesson: one topic per swarm, and strip formatting concerns from worker tasks.

**Prompt 1 of 3: Fine-Tuning Decision Framework**

Research the three primary approaches to fine-tuning custom LLMs: Full Fine-Tuning, LoRA/QLoRA (parameter-efficient fine-tuning), and RLHF/DPO (alignment fine-tuning). For each approach:

How it works — the core mechanism in 2-3 sentences
Pros — concrete advantages (cost, quality, speed, data requirements)
Cons — concrete disadvantages and failure modes
When to use it — the specific conditions that make this the right choice
Current Market Tools — The tools people are currently using to effect the fine tuning
Azure Offering — If it's available in Azure and how to do it in Azure.

Then produce a comparison section covering three real-world scenarios:

Scenario A: Fine-tuning wins over RAG — A situation where retrieval-augmented generation falls short and a custom fine-tuned model is the better solution. Explain why RAG fails here.
Scenario B: RAG wins over fine-tuning — A situation where RAG is clearly sufficient and fine-tuning would be wasteful. Explain why fine-tuning is overkill here.
Scenario C: Both together — A situation where combining a fine-tuned model with RAG produces results neither approach achieves alone. Explain what each component contributes.
For each scenario, be specific: name an industry, a use case, approximate data volumes, and the decision criteria that tip the balance.

**Prompt 2 of 3: Context Window Technical Deep Dive**

Research the context window limitation in current large language models. Focus on substance over formatting — produce a thorough technical document, not a polished paper.

Section 1: The Problem — What is the context window, how is it measured (tokens), and what are the current limits across major models (GPT-4, Claude, Gemini)? What happens in practice when you exceed it — observable output quality degradation, not just theory.

Section 2: Machine vs. Human Memory — Compare how LLMs "remember" (attention over a fixed window) vs. how humans remember (selective encoding, chunking, long-term retrieval). Where does the analogy hold and where does it break? Why can a human read a 500-page novel and discuss themes, but a model with 200k tokens loses the thread?

Section 3: Why Bigger Isn't Better — Why simply scaling the context window doesn't solve the problem. Cover the quadratic attention cost, the "lost in the middle" phenomenon (needle-in-a-haystack degradation), and diminishing returns on retrieval accuracy as context grows.

Section 4: What Researchers Are Doing About It — Survey active approaches: sparse/efficient attention (Ring Attention, Longformer), RAG as external memory, memory-augmented architectures (MemGPT, Infini-attention), context compression/distillation, and state-space models (Mamba). For each: mechanism, current results, open problems.

Include a comparison table of approaches (mechanism, max effective context, compute cost, maturity level).

**Prompt 3 of 3: Executive Distillation (run after Prompt 2 completes)**

Use refinement chat on the Prompt 2 output, or run as a second swarm with the technical document as context:

Distill the context window research into a 2-3 page executive overview for leadership. Structure it as: What's the problem (1 paragraph), Why it matters to our organization (business impact), What's being done about it (plain-language summary of approaches with maturity levels), and What we should watch or act on (recommendations).