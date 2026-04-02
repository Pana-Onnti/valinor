# Grounded Analysis — Research Bibliography

## Last updated: 2026-03-21

Research organized by domain. Each entry includes applicability assessment and implementation priority for Valinor.

---

## 1. ANTI-HALLUCINATION PATTERNS

### Chain-of-Verification (CoVe)
- **Source**: Dhuliawala et al., Meta AI. ACL Findings 2024. [arXiv:2309.11495](https://arxiv.org/abs/2309.11495)
- **Pattern**: Draft → generate verification questions → answer independently → final verified response
- **Valinor**: Implemented in `verification.py:verify_findings()` — claim decomposition + registry matching
- **Status**: IMPLEMENTED (basic), EVOLVE (add re-query verification)

### SAFE (Search-Augmented Factuality Evaluator)
- **Source**: Wei et al., Google DeepMind & Stanford. NeurIPS 2024. [arXiv:2403.18802](https://arxiv.org/abs/2403.18802)
- **Pattern**: Decompose into atomic facts → verify each independently → aggregate verdict
- **Valinor**: Implemented in `verification.py:_decompose_finding()` — breaks findings into atomic claims
- **Status**: IMPLEMENTED (basic), EVOLVE (better decomposition of complex claims)

### CRITIC (Tool-Interactive Self-Verification)
- **Source**: Gou et al. ICLR 2024. [arXiv:2305.11738](https://arxiv.org/abs/2305.11738)
- **Pattern**: Generate → verify with external tools (SQL, Python) → correct → repeat
- **Valinor**: Verification Engine uses query results as the "external tool" for verification
- **Status**: IMPLEMENTED (passive), EVOLVE (add active re-querying)

### Reflexion (Self-Correction via Memory)
- **Source**: Shinn et al. NeurIPS 2023. [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)
- **Pattern**: Agent reflects on failures, stores critique in memory, retries with critique loaded
- **Valinor**: The calibration loop in the skill captures this pattern (human-in-the-loop version)
- **Status**: MANUAL, EVOLVE (automate reflection between pipeline runs)

### Multi-Agent Debate
- **Source**: Du et al. ICML 2024. [arXiv:2305.14325](https://arxiv.org/abs/2305.14325)
- **Pattern**: Multiple LLM instances analyze same data, debate findings, remove uncertain facts
- **Valinor**: Analyst/Sentinel/Hunter already run in parallel; reconcile_swarm resolves conflicts
- **Status**: IMPLEMENTED (basic), EVOLVE (add structured debate rounds)

### VerifiAgent (Adaptive Verification)
- **Source**: Han et al. EMNLP 2025 Findings. [arXiv:2504.00406](https://arxiv.org/abs/2504.00406)
- **Pattern**: Two-level: meta-verification (completeness) + tool-adaptive verification (route to right tool)
- **Valinor**: Not yet implemented. Would sit between agents and narrators.
- **Status**: TODO — high value for structured report verification

---

## 2. SCHEMA UNDERSTANDING & KNOWLEDGE GRAPHS

### SchemaGraphSQL
- **Source**: May 2025. [arXiv:2505.18363](https://arxiv.org/abs/2505.18363)
- **Pattern**: Zero-shot schema linking via graph pathfinding. Single LLM call predicts tables, BFS finds JOIN paths.
- **Valinor**: Core of `knowledge_graph.py:find_join_path()` — BFS over FK graph
- **Status**: IMPLEMENTED

### LLM-FK (Multi-Agent Foreign Key Detection)
- **Source**: March 2026. [arXiv:2603.07278](https://arxiv.org/html/2603.07278v1)
- **Pattern**: 4 agents (Profiler→Interpreter→Refiner→Verifier). F1 0.93-1.00 on benchmarks.
- **Key innovation**: "Unique-Key-Driven Schema Decomposition" reduces candidate pairs by 1000x
- **Valinor**: NOT implemented. Would replace manual relationship definition in entity_map.
- **Status**: TODO — **critical for eliminating manual schema configuration**
- **Priority**: HIGH — this removes the need for human-defined relationships

### RIGOR (RAG-driven Iterative Ontology Generation)
- **Source**: June 2025. [arXiv:2506.01232](https://arxiv.org/html/2506.01232v1)
- **Pattern**: Iterate table-by-table following FKs. 3-source RAG (core ontology + docs + domain repo). Judge-LLM validates each fragment.
- **Valinor**: NOT implemented. Would auto-generate business ontology from schema.
- **Status**: TODO — **critical for auto-understanding business model**
- **Priority**: HIGH — replaces hardcoded business concepts

### AutoSchemaKG
- **Source**: May 2025. [arXiv:2505.23628](https://arxiv.org/html/2505.23628v1)
- **Pattern**: Explore-Construct-Filter for enterprise-scale KG construction
- **Status**: REFERENCE — informs our KG architecture but we use simpler graph

### QueryWeaver (FalkorDB)
- **Source**: Sept 2025. [queryweaver.ai](https://www.queryweaver.ai/)
- **Pattern**: Maps DB schema into FalkorDB KG as semantic layer. MCP server for agents. Supports PostgreSQL/MySQL.
- **Valinor**: NOT integrated. Would replace our query_builder templates with graph-guided SQL.
- **Status**: EVALUATE — open-source, could integrate via MCP
- **Priority**: MEDIUM — alternative to template-based query generation

### Cognee (RDB → Knowledge Graph)
- **Source**: 2025-2026. [cognee.ai](https://www.cognee.ai/blog/deep-dives/relational-database-to-knowledge-graph-cognee-dlt)
- **Pattern**: Schema extraction → node creation → edge mapping → vector embedding. Uses dlt.
- **Valinor**: We already use dlt (VAL-33). Cognee could enhance our KG with vector embeddings.
- **Status**: EVALUATE — compatible with our dlt layer

### SchemaCrawler-AI (MCP Server)
- **Source**: 2026. [github.com/schemacrawler/SchemaCrawler-AI](https://github.com/schemacrawler/SchemaCrawler-AI)
- **Pattern**: MCP Server exposing schema metadata for LLM agents to query interactively
- **Valinor**: Could replace our custom introspection in cartographer.py
- **Status**: EVALUATE — JDBC-based, good for Java ERPs (SAP, Openbravo)

---

## 3. TEXT-TO-SQL & QUERY GENERATION

### MAC-SQL (Multi-Agent Collaborative)
- **Source**: 2024. Wang et al.
- **Pattern**: Selector→Decomposer→Refiner. Explicit JOIN reasoning. Error-aware retry.
- **Valinor**: query_builder.py is static templates; MAC-SQL is dynamic generation
- **Status**: REFERENCE — informs future dynamic query generation

### CHESS (Meta AI)
- **Source**: 2024.
- **Pattern**: Schema Filter (samples actual values) → SQL Generator → SQL Reviser → Evaluator
- **Valinor**: Cartographer's Phase 1 pre-scan is similar to CHESS's Schema Filter
- **Status**: REFERENCE — validates our Phase 1 approach

### BIRD Benchmark (March 2026 update)
- **Source**: [bird-bench.github.io](https://bird-bench.github.io/)
- **Reality check**: Best systems achieve 16.33% on BIRD-Interact-Full. Real ERP schemas (100+ tables) remain unsolved.
- **Implication**: Pure text-to-SQL is NOT sufficient. Need the full KG → semantic catalog → guided generation pipeline.

### Vanna AI
- **Source**: Open-source. [vanna.ai](https://vanna.ai/)
- **Pattern**: RAG over DDL + docs + golden SQL examples → SQL generation
- **Valinor**: Integrated via VAL-32. Enhanced with KG for better schema context.
- **Status**: INTEGRATED, EVOLVE (feed KG context as training documentation)

---

## 4. DATA PROFILING & SEMANTIC DETECTION

### ydata-profiling
- **Source**: [github.com/ydataai/ydata-profiling](https://github.com/ydataai/ydata-profiling)
- **Pattern**: One-line EDA with semantic type detection. JSON output.
- **Status**: EVALUATE — could replace our custom column profiling in cartographer

### GAIT (GNN Semantic Type Detection)
- **Source**: PAKDD 2024. [arXiv:2405.00123](https://arxiv.org/html/2405.00123v1)
- **Pattern**: GNN + language model hybrid for column type detection
- **Valinor**: `knowledge_graph.py:is_low_cardinality` is a simplified version
- **Status**: REFERENCE — our statistical approach is simpler but sufficient

### Sherlock / SATO / TASTE (Contrastive Deep Learning)
- **Source**: Various 2020-2024. [ThirdEyeData summary](https://thirdeyedata.ai/tabular-data-column-semantic-type-identification-with-contrastive-deep-learning/)
- **Pattern**: Deep learning on column data distributions for semantic type classification
- **Status**: REFERENCE — heavy ML, our LLM-based approach is lighter

### ZOES (Zero-Shot Entity Structure Discovery)
- **Source**: EACL 2026. [arXiv:2506.04458](https://arxiv.org/abs/2506.04458)
- **Pattern**: Enrichment → Refinement → Unification for unknown domains
- **Status**: REFERENCE — validates our "start from nothing" approach

---

## 5. INDUSTRY PATTERNS (Palantir, Bloomberg, Kensho)

### Palantir Foundry Ontology
- **Source**: [palantir.com/docs/foundry/ontology](https://www.palantir.com/docs/foundry/ontology/overview)
- **Pattern**: Operational ontology layer between raw data and analysis. All queries go through ontology, never raw tables. ML models expressed in business terms.
- **Valinor**: Our KG + business concepts layer is the lightweight equivalent
- **Key insight**: "Model the business concept and attach the right data to it"

### Bloomberg (Retrieval-First)
- **Pattern**: Always retrieve actual data point BEFORE generating commentary. LLM narrates, never computes.
- **Valinor**: Verification Engine's Number Registry enforces this — narrators can only use registered values

### Kensho (S&P Global)
- **Pattern**: Structured extraction over generation. Confidence scoring on every fact. Below threshold = human review.
- **Valinor**: `verification_report.is_trustworthy` (>80% verification rate) mirrors this

---

## 6. DATA GOVERNANCE & CATALOGS (2026)

### DataHub v1.4.0 (2026)
- AI Agent Context Kit, GenAI documentation, AI classification. 12.5K+ community.
- **Status**: EVALUATE for metadata storage

### OpenMetadata v1.11.x (2026)
- Data contracts (schemas + SLAs + quality guarantees), native quality testing.
- **Status**: EVALUATE — quality testing aligns with our DQ Gate

### Atlan (2026 Gartner Leader)
- Named Leader in 2026 Gartner MQ for Data & Analytics Governance. MCP integration.
- **Status**: REFERENCE — commercial, but validates our architectural direction

---

## 7. NEUROSYMBOLIC & HYBRID ARCHITECTURES

### The Deterministic + Probabilistic Pattern
```
[Intent]      LLM understands what to analyze    (PROBABILISTIC)
[Query]       SQL/Python computes the answer      (DETERMINISTIC)
[Interpret]   LLM reads the result                (PROBABILISTIC)
[Verify]      Tool checks the interpretation      (DETERMINISTIC)
[Narrate]     LLM writes the report               (PROBABILISTIC)
[Validate]    Parser extracts numbers, matches     (DETERMINISTIC)
```

This is the universal pattern in finance AI (Palantir, Bloomberg, Kensho). The more you push into the deterministic layer, the more trustworthy the system.

### IBM EDBT 2026 Schema Linking
- **Source**: [openproceedings.org/2026/conf/edbt/paper-24.pdf](https://www.openproceedings.org/2026/conf/edbt/paper-24.pdf)
- **Key finding**: Including MORE context than strictly necessary improves query generation. Don't minimize — augment.
- **Implication**: Our KG `to_prompt_context()` should include neighboring tables and sample values, not just the minimal schema.
