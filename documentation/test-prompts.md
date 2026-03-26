# Test Prompts

Here are some prompts we used to generate some of the documents seen in documentation/example_research_output.

## Deep Research

Research how RAG, Vector based, and Memory based pre-fill for system prompts work. Give a Summary of how each works with diagrams, Give pros and cons of each approach. Give a combined strResearch how RAG, Vector based, and Memory based pre-fill for system prompts work. Give a Summary of how each works with diagrams, Give pros and cons of each approach. Give a combined strategy for using all three.

Compare autonomous agent architectures: ReAct, Plan-and-Execute, and Tree of Thoughts. Analyze each framework's decision-making loop, failure recovery mechanisms, and token efficiency. Include a decision matrix for when to use each pattern in production systems.

Compare A2A against a simple inbox pattern and a third commonly used pattern for communication among agent teams of your choice. Compare and contrast the differences and the pros and cons of each.

Compare and contrast three approaches to fine-tuning large language models: Full Fine-Tuning, LoRA/QLoRA (parameter-efficient), and RLHF/DPO (alignment-based). For each method, explain how it works mechanically, what data requirements and compute costs look like, and where it excels vs. falls short. Include a decision matrix for when to use each based on dataset size, budget, and use case. Provide concrete testing and evaluation recommendations for each approach — how to detect overfitting, catastrophic forgetting, and alignment drift, with specific metrics and benchmark strategies.

Compare sqlmesh and dbt for usage as a transitional layer to move raw/bronze to silver/gold. Also source me a third option (like data bricks). How would these help or work on fabric lakehouse => fabric lakehouse or sql => fabric lakehouse. Can they be used natively from Fabric? what's the right medium for their usage. Right now we use the Mirror technology that Azure provides to move to fabric our sources, but this simply brings in "raw" and doesn't account for bronze / silver. There are data flows and factories and notebooks native to Fabric but want to also consider alternatives.

rejoinder:

Add an additional section on \"Discipline for Notebooks\" solving the code sprawl concern. I like the concept of notebooks but they do get to be \"a lot\" and you brought up a good point, they are just code, so how should they be organized. Solve this and you really don't need the rest. Notebooks / Data Flows / Factories can do what you need for that silver / bronze level.