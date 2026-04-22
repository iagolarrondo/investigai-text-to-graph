# InvestigAI — graph investigation prototype (PoC v1)

## 1. Project overview

This repository is a **small prototype** for an **LTC fraud-investigation copilot** built around a **graph**: people, policies, claims, banks, addresses, and businesses as **nodes**, and relationships (for example *insured on policy*, *claim against policy*, *shared bank account*) as **edges**.

**What you can do today**

- Turn synthetic **seed tables** into graph files (`nodes.csv`, `edges.csv`), or load a **Neo4j-style export** with the same column names expected by the loader.
- Open a **Streamlit app** (**`src/app/app.py`**) where an LLM runs a **tool-planner** (with graph tools), a **coverage judge** reads the **full** tool trace against your question (outer loop until satisfied), then **synthesis** produces the **Answer** and a **graph focus** node for the summary pyvis view. Use **`INVESTIGATION_LLM=gemini`** with **`GEMINI_API_KEY`** (or **`GOOGLE_API_KEY`**), **`INVESTIGATION_LLM=anthropic`** with **`ANTHROPIC_API_KEY`**, or **`INVESTIGATION_LLM=ollama`** with **[Ollama](https://ollama.com/)** and a **tool-capable** model pulled (for example `ollama pull llama3.1`).

**Synthetic data:** Example seed data under `data/interim/poc_v1_seed/` is **not** real customer data. Your `data/processed/` files may come from that pipeline or from another export—see **How the app works** below.

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
3. A **coverage judge** (`SYSTEM_COVERAGE_JUDGE` in `prompts.py`) reads the **full** tool inputs and outputs (not truncated for the judge) and decides whether the trace answers the whole question. If not, the planner runs again with reviewer feedback (outer loop is uncapped in code; use sensible questions to control cost).
4. **Synthesis** (`SYSTEM_INVESTIGATION_SYNTHESIS`) produces the **only** user-visible narrative and a **`graph_focus_node_id`** for the summary graph when possible.
5. **All graph math is deterministic** — traversal lives in **`src/graph_query/query_graph.py`**. The LLM **selects tools** and **writes prose**; it does not invent edges.
6. Below the **Answer**, an **Investigation graph** (pyvis) appears **once per run**: one **focus** node (synthesis ``graph_focus_node_id`` when set, otherwise heuristics from anchors), then an **undirected N-hop ball** on the full graph (all node and edge types in range). The hop slider widens or tightens that neighbourhood without re-running the LLM. Use the **Interactive Graph** page for unconstrained exploration. There are no separate graphs per tool step.

**Preflight and optional extensions** — Before the planner, a **preflight** LLM pass classifies whether the **current** tool catalog can answer the question fully and efficiently (`sufficient` / `insufficient` / `sufficient_but_inefficient`) and may suggest a short plan; that text is appended to the planner’s first user turn when present. With **`INVESTIGATION_EXTENSION_AUTHORING=1`** (see **`.env.example`**), a non-`sufficient` preflight can trigger **code authoring**: a new module under **`src/graph_query/generated/`**, an entry in **`src/graph_query/extension_registry.json`**, and a **`pytest`** smoke gate (`tests/test_graph_extensions_smoke.py`). Successful extensions merge into the tool list for the rest of the run and after restart; **commit** those files to share. Default is authoring **off**.

**Tools (high level)** — Include `get_graph_relationship_catalog`, `search_nodes`, `get_neighbors`, `summarize_graph`, `get_claim_network`, `get_claim_subgraph_summary`, `get_person_subgraph_summary`, `get_policy_network`, `get_person_policies`, `policies_with_related_coparties`, `find_shared_bank_accounts`, `find_related_people_clusters`, `find_business_connection_patterns`. See **§2.4** for schema introspection.

**Copilot prompts** (`SYSTEM_COPILOT_ANSWER`, intent router JSON, few-shots) remain available for other entrypoints; the main Streamlit investigation path is planner → judge → synthesis only.

### 2.3 LLM configuration (Gemini, Anthropic, or local Ollama)

**Gemini (default)** — Set **`GEMINI_API_KEY`** (or **`GOOGLE_API_KEY`**) in **`.env`** (see §4). Optional: **`GEMINI_MODEL`** (defaults to `gemini-2.5-flash`). Prompts live in **`src/llm/prompts.py`**.

**Anthropic Claude** — Set **`ANTHROPIC_API_KEY`** in **`.env`** and **`INVESTIGATION_LLM=anthropic`** (or **`claude`**). Optional: **`ANTHROPIC_MODEL`** (defaults to **`claude-sonnet-4-6`**; use any id from [Anthropic’s model list](https://docs.anthropic.com/en/docs/about-claude/models/all-models) — older snapshot names such as `claude-3-5-sonnet-20241022` may **404**). The planner, judge, and synthesis steps all use the **full** prompts in `prompts.py`, including **`<domain_knowledge>`** (same as Gemini — not the Ollama compact variants).

**Local Ollama** — Install [Ollama](https://ollama.com/), run `ollama serve` (or use the desktop app), pull a model that supports **tool calling** (for example `ollama pull llama3.1`). In **`.env`**, set **`INVESTIGATION_LLM=ollama`** (or **`local`**). Optional: **`OLLAMA_HOST`** (default `http://127.0.0.1:11434`), **`OLLAMA_MODEL`** (default `llama3.1`), **`OLLAMA_TIMEOUT`** (HTTP timeout in seconds for each Ollama request; default **600**, use **`0`** for no timeout). Quality and JSON reliability vary by model; if tools misfire, try another tool-capable tag from the Ollama library.

**Planner speed:** Each **tool round** is a separate model call inside a planner segment, and each **planner segment** can repeat after the judge. Defaults (when **`INVESTIGATION_PLANNER_MAX_ROUNDS`** is unset): **14** tool rounds per segment for **Gemini** and **Anthropic**, **12** for **Ollama** — raise (e.g. `20`) for depth, or lower (e.g. `8`) for speed. Optional **`INVESTIGATION_MAX_PLANNER_PHASES`** caps outer planner–judge cycles before synthesis (e.g. **`2`**); omit for unlimited. For **Ollama**, `1` is fastest but often shallow; **`2`–`4`** balances depth and time. Independently, **`INVESTIGATION_MAX_TOOL_STEPS`** caps **recorded tool executions** per investigation across all planner phases (default **20**; set **`0`** for no cap). See **`.env.example`**.

**Ollama can feel slow or “stuck”** because each investigation runs many **sequential** calls with a **large** prompt. Mitigations: **GPU** / larger quant, the limits above, and **`OLLAMA_TIMEOUT`**.

**Ollama JSON answers:** Judge and synthesis use **compact prompts** (no full domain-doc block), **truncated traces** (see **`OLLAMA_MAX_TRACE_CHARS`** in `.env.example`), and Ollama **`format=json`** for parseable output. If the model still returns an empty JSON `answer`, the app runs a **short plain-text synthesis fallback** so you still get prose.

**API usage:** Hosted models (**Gemini**, **Anthropic**) bill per request/token. Each planner **tool round** and each **judge** / **synthesis** step is separate traffic. **Ollama** avoids hosted cost but uses local RAM/CPU or GPU.

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
| `data/interim/poc_v1_seed/` | Input CSV extracts when using the bundled builder (policies, claims, resolved people, etc.). |
| `data/processed/` | **Graph used at runtime:** `nodes.csv`, `edges.csv` (from the build script or an external export). |
| `src/graph_build/` | Builds graph CSVs from the seed (`build_graph_files.py`). |
| `src/graph_query/` | Loads the graph and runs investigation-style queries; optional **`extension_registry.json`** + **`generated/*.py`** for LLM-authored tools. |
| `src/llm/` | **Tool planner** (`tool_agent.py`), **Gemini** (`gemini_llm.py`), **Anthropic** (`anthropic_llm.py`), **Ollama** (`local_ollama.py`), **orchestrator** (`orchestration.py`), **prompts** (`prompts.py`), **result text** (`result_serialize.py`). |
| `src/app/` | Streamlit UI: **`app.py`** (planner → judge → synthesis + summary graph); **`investigation_graph.py`** (focus + hop-ego subgraph for the main app); optional **pages** under `src/app/pages/`. |
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

**Google Gemini (required for investigations):** create a `.env` file in the project root:

```env
GEMINI_API_KEY=your-key-from-google-ai-studio
# Optional:
# GEMINI_MODEL=gemini-2.5-flash
```

Copy from `.env.example` if present. Do not commit `.env`.

**Optional — tests:** if pytest is not installed:

```bash
pip install pytest
```

If `pip` or `python` fails, try `python3` and `pip3` instead.

---

## 5. How to generate graph files (builder path)

From the **project root**:

```bash
python src/graph_build/build_graph_files.py
```

This reads `data/interim/poc_v1_seed/*.csv` and writes:

- `data/processed/nodes.csv`
- `data/processed/edges.csv`

**If something goes wrong:** check that the seed folder still contains the CSV files. The script prints warnings if a seed file is missing.

If you use a **Neo4j export** instead, place compatible `nodes.csv` / `edges.csv` under `data/processed/` yourself; the tests in `tests/test_graph_outputs.py` accept both schemas.

---

## 6. How to run the app

**Ensure `data/processed/nodes.csv` and `edges.csv` exist** (section 5 or your own export).

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

## 7. How to run tests

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

## 8. Demo scenarios and questions

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

## Where this fits in the bigger picture

Longer term, the idea is to connect **documentation and enterprise data** to a **single explorable graph** and an assistant that helps investigators navigate it.

This PoC keeps **query logic in code**. The app uses **Gemini** only for **multi-step tool planning**, **coverage review**, and the final **Answer** text. **Schema introspection** (`get_graph_relationship_catalog`) stays useful as the export evolves. Everything runs **locally** on CSVs for demos and stakeholder reviews.
