# InvestigAI — graph investigation prototype (PoC v1)

## 1. Project overview

This repository is a **small prototype** for an **LTC fraud-investigation copilot** built around a **graph**: people, policies, claims, banks, addresses, and businesses as **nodes**, and relationships (for example *insured on policy*, *claim against policy*, *shared bank account*) as **edges**.

**What you can do today**

- Turn synthetic **seed tables** into graph files (`nodes.csv`, `edges.csv`), or load a **Neo4j-style export** with the same column names expected by the loader.
- Open a **Streamlit app** (**`src/app/app.py`**) where **Claude** runs a **tool-planner loop**: it chooses and executes real `query_graph` functions (search, relationship catalog, claim/person queries, global scans, …), shows each tool step, then writes an **Answer**. **`ANTHROPIC_API_KEY`** is required for the UI to run investigations.

**Synthetic data:** Example seed data under `data/interim/poc_v1_seed/` is **not** real customer data. Your `data/processed/` files may come from that pipeline or from another export—see **How the app works** below.

---

## 2. How the app works

The UI is **`src/app/app.py`**. Everything below happens **on your machine** using the CSVs in `data/processed/`.

### 2.1 Load the graph

1. `query_graph.load_graph()` reads **`nodes.csv`** and **`edges.csv`**.
2. It builds an **in-memory directed graph** ([NetworkX](https://networkx.org/))—there is no graph database server in this PoC.
3. The loader supports **two CSV shapes**: the **builder** format (`node_id`, `edge_type`, …) and a **Neo4j export** format (`id`, `labels`, `relationship_type`, `start_id`, `end_id`). See `src/graph_query/query_graph.py` for details.

### 2.2 Investigation flow (tool planner only)

1. You enter a **question** and click **Run investigation**.
2. **`run_tool_planner_agent`** (`src/llm/tool_agent.py`) calls **Claude** with a **tool catalog** mapped to `query_graph` functions. The model may call tools multiple times (tool-use loop), then returns a final narrative.
3. **All graph math is deterministic** — traversal lives in **`src/graph_query/query_graph.py`**. The LLM only **selects tools and summarizes**; it does not invent edges.
4. Below the **Answer**, an **Investigation graph** (pyvis) appears **once per run**: anchors are **ranked** (tool inputs first, then ids from tool results, then the written answer). For **claim** or **policy** investigations it prefers a **dense slice** aligned with the claim/policy tools (claim ↔ policies ↔ people on claim/policy—not a random hop through unrelated entities). Other modes use tailored type filters or person–person edges. Hop count is adjustable without re-running the LLM. Use the **Interactive Graph** page for unconstrained exploration. There are no separate graphs per tool step.

**Tools (high level)** — Include `get_graph_relationship_catalog`, `search_nodes`, `get_neighbors`, `summarize_graph`, `get_claim_network`, `get_claim_subgraph_summary`, `get_person_subgraph_summary`, `get_policy_network`, `get_person_policies`, `policies_with_related_coparties`, `find_shared_bank_accounts`, `find_related_people_clusters`, `find_business_connection_patterns`. See **§2.4** for schema introspection.

**Other modules** — `router.py`, `investigation_agent.py`, and copilot prompts remain in the repo for **library / CLI / tests** use; the Streamlit entrypoint no longer exposes Auto routing, manual templates, or the template agent.

### 2.3 API key

Set **`ANTHROPIC_API_KEY`** in a **`.env`** file in the project root (see §4). The main app **requires** it to run investigations. Prompts live in **`src/llm/prompts.py`**.

### 2.4 Graph schema introspection (future-proofing)

**`get_graph_relationship_catalog()`** builds a table of every directed triple **`(from_node_type, edge_type, to_node_type)`** with **counts**, from whatever is in the loaded CSVs. It updates **automatically** when you swap or rebuild `nodes.csv` / `edges.csv`—no Python change required when new relationship types appear.

The tool planner exposes this as the **`get_graph_relationship_catalog`** tool so the model can see **how** entity types connect before chaining `search_nodes` / `get_neighbors` / composite helpers. That reduces reliance on adding a new named function for every novel question shape.

**Tests:** `tests/test_graph_outputs.py` includes `test_relationship_catalog_sums_to_edge_count` (catalog counts sum to total edges).

### End-to-end summary

```text
User question
        → Claude tool_use loop → query_graph.* (zero or more tool calls)
        → Streamlit: expandable tool trace + final Answer
```

**Interactive Graph** (`src/app/pages/1_Interactive_Graph.py`) uses pyvis; the **Node inspector** and sidebar **Focus node** share one focus so choosing a node updates the N-hop subgraph the same as clicking that node in the view. The main investigation page focuses on the tool trace and answer.

---

## 3. Folder structure (summary)

| Path | Purpose |
|------|--------|
| `data/interim/poc_v1_seed/` | Input CSV extracts when using the bundled builder (policies, claims, resolved people, etc.). |
| `data/processed/` | **Graph used at runtime:** `nodes.csv`, `edges.csv` (from the build script or an external export). |
| `src/graph_build/` | Builds graph CSVs from the seed (`build_graph_files.py`). |
| `src/graph_query/` | Loads the graph and runs investigation-style queries. |
| `src/llm/` | **Tool-planner agent** (`tool_agent.py`), **prompts** (`prompts.py`), **routing / template agent** (`router.py`, `investigation_agent.py`) for reuse, **result text** (`result_serialize.py`). |
| `src/app/` | Streamlit UI: **`app.py`** (tool-planner + summary graph); **`investigation_graph.py`** (anchors + subgraph for the main app); optional **pages** under `src/app/pages/`. |
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

**Anthropic (required for investigations):** create a `.env` file in the project root:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
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

This PoC keeps **query logic in code**. The app uses **Claude** only for **multi-step tool planning** and the final **Answer** text. **Schema introspection** (`get_graph_relationship_catalog`) stays useful as the export evolves. Everything runs **locally** on CSVs for demos and stakeholder reviews.
