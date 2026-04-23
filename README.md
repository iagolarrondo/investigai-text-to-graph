# InvestigAI — graph investigation prototype (PoC v1 + scalable synthetic generation)

## 1. Project overview

This repository is a **small prototype** for an **LTC fraud-investigation copilot** built around a **graph**: people, policies, claims, banks, addresses, and businesses as **nodes**, and relationships (for example *insured on policy*, *claim against policy*, *shared bank account*) as **edges**.

**What you can do today**

- **Generate** configurable synthetic datasets (small or large), build graph files from **generated** or **legacy** seed tables, or load a **Neo4j-style export** with the column names expected by the loader.
- Open **`src/app/app.py`**, where an LLM runs a **tool-planner** (with graph tools), a **coverage judge** reads the **full** tool trace (outer loop until satisfied), then **synthesis** produces the **Answer** and a **graph focus** for the summary pyvis view. By default (**`INVESTIGATION_MERGE_JUDGE_SYNTHESIS`**, see **`.env.example`**) the judge may return the answer in the same JSON when satisfied, skipping a separate synthesis call. Configure **`INVESTIGATION_LLM`** and API keys as in **§4** (Gemini, Anthropic, or local Ollama with a **tool-capable** model, for example `ollama pull llama3.1`).
- Use **`src/llm/router.py`** for **optional Claude intent routing** (same ``SYSTEM_INTENT_ROUTER`` as prompts; needs **`ANTHROPIC_API_KEY`**) in other scripts or experiments—the main Streamlit path is planner → judge → synthesis.

**Synthetic data:** All bundled datasets in this repository are synthetic and not real customer data. Your `data/processed/` files may come from the builders, the synthetic pipeline, or another export—see **How the app works** below.

---

## 2. How the app works

The UI is **`src/app/app.py`**. Everything below happens **on your machine** using the CSVs in `data/processed/`.

### 2.1 Load the graph

1. `query_graph.load_graph()` reads **`nodes.csv`** and **`edges.csv`**.
2. It builds an **in-memory directed graph** ([NetworkX](https://networkx.org/))—there is no graph database server in this PoC.
3. The loader supports **two CSV shapes**: the **builder** format (`node_id`, `edge_type`, …) and a **Neo4j export** format (`id`, `labels`, `relationship_type`, `start_id`, `end_id`). See `src/graph_query/query_graph.py` for details.

### 2.2 Investigation flow (planner → judge → synthesis)

1. You enter a **question** and click **Run investigation**.
2. **`run_tool_planner_agent`** (`src/llm/tool_agent.py`, delegating to **`run_investigation_orchestrator`** in `src/llm/orchestration.py`) runs **Gemini**, **Anthropic Claude**, or **Ollama** (see §2.3) with a **tool catalog** mapped to `query_graph` functions. The planner may call tools in multiple rounds until it stops requesting tools.
3. A **coverage judge** (``SYSTEM_COVERAGE_JUDGE`` or merged ``SYSTEM_COVERAGE_JUDGE_MERGED`` in `prompts.py`) reads the **full** tool inputs and outputs (not truncated for the judge) and decides whether the trace answers the whole question. If not, the planner runs again with reviewer feedback (outer loop is uncapped in code; use sensible questions to control cost).
4. **Synthesis** (standalone ``SYSTEM_INVESTIGATION_SYNTHESIS``, or fields from the merged judge JSON when enabled) produces the **only** user-visible narrative and a **`graph_focus_node_id`** for the summary graph when possible.
5. **All graph math is deterministic** — traversal lives in **`src/graph_query/query_graph.py`**. The LLM **selects tools** and **writes prose**; it does not invent edges.
6. Below the **Answer**, an **Investigation graph** (pyvis) appears **once per run**: one **focus** node (synthesis ``graph_focus_node_id`` when set, otherwise heuristics from anchors), then an **undirected N-hop ball** on the full graph (all node and edge types in range). The hop slider widens or tightens that neighbourhood without re-running the LLM. Use the **Interactive Graph** page for unconstrained exploration. There are no separate graphs per tool step.

**Preflight and optional extensions** — Before the planner, a **preflight** LLM pass classifies whether the **current** tool catalog can answer the question fully and efficiently (`sufficient` / `insufficient` / `sufficient_but_inefficient`) and may suggest a short plan; that text is appended to the planner’s first user turn when present. With **`INVESTIGATION_EXTENSION_AUTHORING=1`** (see **`.env.example`**), a non-`sufficient` preflight can trigger **code authoring**: a new module under **`src/graph_query/generated/`**, an entry in **`src/graph_query/extension_registry.json`**, and a **`pytest`** smoke gate (`tests/test_graph_extensions_smoke.py`). Successful extensions merge into the tool list for the rest of the run and after restart; **commit** those files to share. Default is authoring **off**.

**Tools (high level)** — Include `get_graph_relationship_catalog`, `search_nodes`, `get_neighbors`, `summarize_graph`, `get_claim_network`, `get_claim_subgraph_summary`, `get_person_subgraph_summary`, `get_policy_network`, `get_person_policies`, `policies_with_related_coparties`, `find_shared_bank_accounts`, `find_related_people_clusters`, `find_business_connection_patterns`. See **§2.4** for schema introspection.

**Copilot prompts** (`SYSTEM_COPILOT_ANSWER`, intent router JSON, few-shots) remain available for other entrypoints; the main Streamlit investigation path is planner → judge → synthesis only.

### 2.3 LLM configuration (Gemini, Anthropic, or local Ollama)

**Gemini (default)** — Set **`GEMINI_API_KEY`** (or **`GOOGLE_API_KEY`**) in **`.env`** (see §4). Optional: **`GEMINI_MODEL`** (defaults to `gemini-2.5-flash`). Prompts live in **`src/llm/prompts.py`**.

**Anthropic Claude** — Set **`ANTHROPIC_API_KEY`** in **`.env`** and **`INVESTIGATION_LLM=anthropic`** (or **`claude`**). Optional: **`ANTHROPIC_MODEL`** (defaults to **`claude-sonnet-4-6`**; use any id from [Anthropic’s model list](https://docs.anthropic.com/en/docs/about-claude/models/all-models) — older snapshot names such as `claude-3-5-sonnet-20241022` may **404**). The planner, judge, and synthesis steps use the **full** prompts in `prompts.py`, including **`<graph_llm_summary>`** from `data/raw/graph/graph_llm_summary.md` (same pattern as Gemini — not the Ollama compact variants).

**Local Ollama** — Install [Ollama](https://ollama.com/), run `ollama serve` (or use the desktop app), pull a model that supports **tool calling** (for example `ollama pull llama3.1`). In **`.env`**, set **`INVESTIGATION_LLM=ollama`** (or **`local`**). Optional: **`OLLAMA_HOST`** (default `http://127.0.0.1:11434`), **`OLLAMA_MODEL`** (default `llama3.1`), **`OLLAMA_TIMEOUT`** (HTTP timeout in seconds for each Ollama request; default **600**, use **`0`** for no timeout). Quality and JSON reliability vary by model; if tools misfire, try another tool-capable tag from the Ollama library.

**Planner speed:** Each **tool round** is a separate model call inside a planner segment, and each **planner segment** can repeat after the judge. Defaults (when **`INVESTIGATION_PLANNER_MAX_ROUNDS`** is unset): **14** tool rounds per segment for **Gemini** and **Anthropic**, **12** for **Ollama** — raise (e.g. `20`) for depth, or lower (e.g. `8`) for speed. Optional **`INVESTIGATION_MAX_PLANNER_PHASES`** caps outer planner–judge cycles before synthesis (e.g. **`2`**); omit for unlimited. For **Ollama**, `1` is fastest but often shallow; **`2`–`4`** balances depth and time. Independently, **`INVESTIGATION_MAX_TOOL_STEPS`** caps **recorded tool executions** per investigation across all planner phases (default **20**; set **`0`** for no cap). See **`.env.example`**.

**Ollama can feel slow or “stuck”** because each investigation runs many **sequential** calls with a **large** prompt. Mitigations: **GPU** / larger quant, the limits above, and **`OLLAMA_TIMEOUT`**.

**Ollama JSON answers:** Judge and synthesis use **compact prompts** (no full domain-doc block), **truncated traces** (see **`OLLAMA_MAX_TRACE_CHARS`** in `.env.example`), and Ollama **`format=json`** for parseable output. If the model still returns an empty JSON `answer`, the app runs a **short plain-text synthesis fallback** so you still get prose.

**API usage:** Hosted models (**Gemini**, **Anthropic**) bill per request/token. Each planner **tool round** is separate traffic; **judge** and **synthesis** are separate calls unless merged mode skips synthesis after a satisfied judge. **Ollama** avoids hosted cost but uses local RAM/CPU or GPU.

### 2.4 Graph schema introspection (future-proofing)

**`get_graph_relationship_catalog()`** builds a table of every directed triple **`(from_node_type, edge_type, to_node_type)`** with **counts**, from whatever is in the loaded CSVs. It updates **automatically** when you swap or rebuild `nodes.csv` / `edges.csv`—no Python change required when new relationship types appear.

The tool planner exposes this as the **`get_graph_relationship_catalog`** tool so the model can see **how** entity types connect before chaining `search_nodes` / `get_neighbors` / composite helpers. That reduces reliance on adding a new named function for every novel question shape.

**Tests:** `tests/test_graph_outputs.py` includes `test_relationship_catalog_sums_to_edge_count` (catalog counts sum to total edges).

### End-to-end summary

```text
User question
        → (optional) Tool preflight on catalog → (optional) extension authoring + registry merge
        → LLM tool-calling loop (Gemini, Anthropic, or Ollama) → query_graph.* (zero or more tool calls per planner phase)
        → Coverage judge on full trace → repeat if needed
        → Synthesis → Streamlit: tool trace + reviewer rounds + Answer + investigation graph
```

**Full Interactive Graph** (`src/app/pages/1_Full_Interactive_Graph.py`) uses pyvis; the **Node inspector** and sidebar **Focus node** share one focus so choosing a node updates the N-hop subgraph the same as clicking that node in the view. The main investigation page focuses on the tool trace and answer.

---

## 3. Folder structure (summary)

| Path | Purpose |
|------|--------|
| `data/interim/poc_v1_seed/` | Legacy bundled PoC seed extracts (still supported). |
| `data/interim/generated_seed_small/` | Generated operational seed tables for a fast local dataset. |
| `data/interim/generated_seed_large/` | Generated operational seed tables for a ~1000-node-class dataset. |
| `eval/generated_small/` | Hidden evaluation metadata (scenario labels, mappings) for the small dataset. |
| `eval/generated_large/` | Hidden evaluation metadata (scenario labels, mappings) for the large dataset. |
| `data/processed/` | **Graph used at runtime:** `nodes.csv`, `edges.csv` (from the build script or an external export). |
| `src/synthetic/` | Configurable synthetic data generation + validation tooling. |
| `src/graph_build/` | Builds graph CSVs from a seed directory (`build_graph_files.py`). |
| `src/graph_query/` | Loads the graph and runs investigation-style queries; optional **`extension_registry.json`** + **`generated/*.py`** for LLM-authored tools. |
| `src/llm/` | **Tool planner** (`tool_agent.py`), **Gemini** / **Anthropic** / **Ollama** clients, **orchestrator** (`orchestration.py`), **prompts** (`prompts.py`), **router** (`router.py`, rule-based routing for optional flows). |
| `src/app/` | Streamlit UI: **`app.py`** (planner → judge → synthesis + summary graph); **`investigation_graph.py`**; optional **pages** under `src/app/pages/`. |
| `tests/` | Smoke tests on processed CSVs (supports builder and Neo4j column layouts). |
| `docs/` | Design notes and **[demo scenario cheat sheet](docs/demo_cases.md)**. |
| `notebooks/` | Optional exploration (not required to run the app). |

---

## 4. Setup instructions

**You need:** [Python](https://www.python.org/downloads/) **3.10+** (3.11–3.13 work) and a terminal.

**Step A — Open a terminal in the project folder**

- The folder that contains `src/`, `data/`, and `requirements.txt`.

**Step B — (Recommended) use a virtual environment**

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (Command Prompt):

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

**Step C — Install dependencies**

```bash
pip install -r requirements.txt
```

This installs runtime dependencies for the Streamlit app (including **`pyvis`** for graph pages, and **`anthropic`** if you use Anthropic-hosted models or optional router helpers).

**Investigations (hosted or local LLM):** create a **`.env`** file in the project root. Copy from **`.env.example`** if present. Do not commit **`.env`**. At minimum, set keys for your chosen backend—for example:

```env
GEMINI_API_KEY=your-key-from-google-ai-studio
# Optional:
# GEMINI_MODEL=gemini-2.5-flash
# INVESTIGATION_LLM=anthropic
# ANTHROPIC_API_KEY=...
```

See **§2.3** for Gemini, Anthropic, and Ollama options.

**Optional — tests:** if pytest is not installed:

```bash
pip install pytest
```

If `pip` or `python` fails, try `python3` and `pip3` instead.

If you use a virtual environment, run all commands with that environment active (or call binaries directly, e.g. `.venv/bin/pip`, `.venv/bin/streamlit`).

---

## 5. Generate synthetic data

Two configs are provided:

- `src/synthetic/configs/small.yaml` (fast iteration)
- `src/synthetic/configs/large.yaml` (default, ~1000 target node entities across core tables)

Generate a dataset:

```bash
python src/synthetic/generate_dataset.py --config src/synthetic/configs/small.yaml
python src/synthetic/generate_dataset.py --config src/synthetic/configs/large.yaml
```

This writes:

- **Operational seed** CSVs (consumed by graph build) into `data/interim/generated_seed_*`
- **Hidden eval metadata** into `eval/generated_*`

Hidden eval files are intentionally separated so scenario labels are not available in operational graph data.

## 6. Build graph files

From the **project root**:

```bash
# Legacy PoC seed (default)
python src/graph_build/build_graph_files.py

# Generated small seed
python src/graph_build/build_graph_files.py --seed-dir data/interim/generated_seed_small

# Generated large seed
python src/graph_build/build_graph_files.py --seed-dir data/interim/generated_seed_large
```

This writes:

- `data/processed/nodes.csv`
- `data/processed/edges.csv`

**If something goes wrong:** check that the seed folder still contains the CSV files. The script prints warnings if a seed file is missing.

If you use a **Neo4j export** instead, place compatible `nodes.csv` / `edges.csv` under `data/processed/` yourself; the tests in `tests/test_graph_outputs.py` accept both schemas.

---

## 7. Validate generated data and pipeline

Run validation checks (optionally rebuilding graph first):

```bash
python src/synthetic/validate_pipeline.py \
  --seed-dir data/interim/generated_seed_large \
  --eval-dir eval/generated_large \
  --run-build
```

Checks include:

- operational data internal consistency
- no hidden-label leakage into operational seed columns
- graph edge endpoints map to valid nodes
- current investigation queries still surface key suspicious patterns
- hidden eval metadata contains ambiguous scenarios

## 8. One-command pipeline (recommended)

Run everything in sequence (generate → build → validate):

```bash
python src/synthetic/run_pipeline.py --config src/synthetic/configs/small.yaml
python src/synthetic/run_pipeline.py --config src/synthetic/configs/large.yaml
```

Optionally launch the app immediately after successful validation:

```bash
python src/synthetic/run_pipeline.py --config src/synthetic/configs/large.yaml --launch-app
```

## 9. How to run the app

**Ensure `data/processed/nodes.csv` and `edges.csv` exist** (sections 5–6 or your own export).

From the **project root**, with the venv activated:

```bash
PYTHONPATH=. streamlit run src/app/app.py
```

Your browser should open (often at `http://localhost:8501`). If it does not, copy the URL from the terminal.

**Tips**

- **Same environment:** use the venv’s Python for both `pip install` and `streamlit` (e.g. `python -m streamlit run ...`) so imports resolve.
- **Another terminal:** while Streamlit is running, that terminal stays busy. Open a **new** tab for rebuilds or tests, or press **Ctrl+C** to stop the app.
- **After replacing the graph CSVs:** restart Streamlit or use **Clear cache** so the in-memory graph reloads.
- **Import errors:** `PYTHONPATH=.` (as above) ensures `src` is importable.

---

## 10. How to run tests

Tests check that processed graph files exist, are non-empty, and are internally consistent (endpoints, expected node/edge vocabulary). They support **both** builder and Neo4j-style CSV columns. One test asserts that **`get_graph_relationship_catalog`** row counts sum to the total edge count (guards the introspection aggregation).

**Order matters:** ensure `data/processed/` is populated, then:

```bash
pytest tests/test_graph_outputs.py -v
```

To run everything under `tests/`:

```bash
pytest tests/ -v
```

---

## 11. Demo scenarios and questions

Full **presenter-oriented** walkthrough: **[`docs/demo_cases.md`](docs/demo_cases.md)**.

Type a **question** and run the investigation—the tool planner will call the right `query_graph` helpers. Example angles:

| Scenario | Example phrasing / tools used |
|-----------|------------------------------|
| Schema / unfamiliar graph | Mentions “what connects to what” — model may call `get_graph_relationship_catalog` first. |
| Person-centric policies | “What policies is Person\|1004 on?” — often `search_nodes` / `get_person_policies`. |
| Policy + related party | “Same policy as someone they know?” — `policies_with_related_coparties`. |
| Claim / policy / parties | “Writing agent vs claimant on Claim\|C001” — `get_claim_network` with a **claim** id in the question. |
| Shared banks, clusters, business colocation | “Joint accounts”, “family clusters”, “business at same address” — global find-* tools. |
| Neighborhood (claim) | “Entities within N hops of claim …” — `get_claim_subgraph_summary` with a **claim** id. |
| Neighborhood (person) | “What surrounds this insured / party …” — `get_person_subgraph_summary` with a **Person** id. |
| Policy-centric | “Who is on this policy / what claims hit it?” — `get_policy_network` with a **Policy** id (after `search_nodes` if needed). |

**CLI sanity check** (optional):

```bash
PYTHONPATH=. python src/graph_query/query_graph.py
```

prints sample query output in the terminal.

---

## 12. Synthetic design notes

Current synthetic generation follows a layered approach while preserving existing schema and app compatibility:

1. baseline world generation
2. explicit suspicious motif injection
3. ambiguous weak-signal injection
4. structural bridge-like anomaly injection

Scenario truth labels are stored only under `eval/` and are not fed into graph build, routing, or investigation logic.

## Where this fits in the bigger picture

Longer term, the idea is to connect **documentation and enterprise data** to a **single explorable graph** and an assistant that helps investigators navigate it.

This PoC keeps **query logic in code**. The app uses a configured LLM (**Gemini**, **Anthropic Claude**, or **Ollama**) for **multi-step tool planning**, **coverage review**, and the final **Answer** text. **Schema introspection** (`get_graph_relationship_catalog`) stays useful as the export evolves. Everything runs **locally** on CSVs for demos and stakeholder reviews.
