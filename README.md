# InvestigAI — graph investigation prototype (PoC v1 + scalable synthetic generation)

## 1. Project overview

This repository is a prototype for a fraud-investigation copilot built around a graph: people, policies, claims, banks, addresses, and businesses as nodes, and relationships (for example *insured on policy*, *claim against policy*, *shared bank account*) as edges.

**What you can do today**

- Generate configurable synthetic datasets (small or large), then build graph files (`nodes.csv`, `edges.csv`).
- Open a **Streamlit app** that runs **demo questions** and **free-text** prompts (routed with **simple rules** — **no LLM API key** required).
- See **tables**, short **plain-English explanations**, **supporting graph links**, and a **small subgraph diagram** for each answer.

**Synthetic data:** all datasets in this repo are synthetic and not real customer data.

---

## 2. Folder structure (summary)

| Path | Purpose |
|------|--------|
| `data/interim/poc_v1_seed/` | Legacy bundled PoC seed extracts (still supported). |
| `data/interim/generated_seed_small/` | Generated operational seed tables for a fast local dataset. |
| `data/interim/generated_seed_large/` | Generated operational seed tables for a ~1000-node-class dataset. |
| `eval/generated_small/` | Hidden evaluation metadata (scenario labels, mappings) for small dataset. |
| `eval/generated_large/` | Hidden evaluation metadata (scenario labels, mappings) for large dataset. |
| `data/processed/` | **Generated** graph: `nodes.csv`, `edges.csv` (created by the build script). |
| `src/synthetic/` | Configurable synthetic data generation + validation tooling. |
| `src/graph_build/` | Builds the graph CSVs from the seed. |
| `src/graph_query/` | Loads the graph and runs investigation-style queries. |
| `src/llm/` | Question routing and display helpers (**rule-based** in v1). |
| `src/app/` | Streamlit UI entrypoint. |
| `tests/` | Automated checks on the generated graph files. |
| `docs/` | Design notes and **[demo scenario cheat sheet](docs/demo_cases.md)**. |
| `notebooks/` | Optional exploration (not required to run the app). |

---

## 3. Setup instructions

**You need:** [Python](https://www.python.org/downloads/) **3.10+** (3.11 or 3.12 is fine) and a terminal.

**Step A — Open a terminal in the project folder**

- That is the folder that contains `src/`, `data/`, and `requirements.txt` (often named something like `Manulife Project`).

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

This installs all app/runtime dependencies, including:

- `anthropic` (LLM routing client used by the app/router)
- `pyvis` (interactive graph visualization in the app pages)

**Optional — tests only:** if you want to run pytest and it is not installed yet:

```bash
pip install pytest
```

If `pip` or `python` fails, try `python3` and `pip3` instead.

If you use a virtual environment, run all commands with that environment active (or call binaries directly, e.g. `.venv/bin/pip`, `.venv/bin/streamlit`).

---

## 4. Generate synthetic data

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

## 5. Build graph files

From the **project root** (same folder as `requirements.txt`):

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

---

## 6. Validate generated data and pipeline

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

## 7. One-command pipeline (recommended)

Run everything in sequence (generate -> build -> validate):

```bash
python src/synthetic/run_pipeline.py --config src/synthetic/configs/small.yaml
python src/synthetic/run_pipeline.py --config src/synthetic/configs/large.yaml
```

Optionally launch the app immediately after successful validation:

```bash
python src/synthetic/run_pipeline.py --config src/synthetic/configs/large.yaml --launch-app
```

## 8. How to run the app

**Always build the graph first** (section 4), unless those two CSVs are already up to date.

From the **project root**:

```bash
streamlit run src/app/app.py
```

Your browser should open (often at `http://localhost:8501`). If it does not, copy the URL from the terminal.

**Tips**

- **Another terminal:** while Streamlit is running, that terminal stays busy. Open a **new** terminal tab for other commands (rebuild graph, run tests), or press **Ctrl+C** to stop the app first.
- **After rebuilding the graph:** stop Streamlit (**Ctrl+C**) and start it again, or use Streamlit’s **Clear cache** so the app reloads the new CSVs (the graph is cached for the session).
- **Import errors:** from the project root, try:

  ```bash
  PYTHONPATH=. streamlit run src/app/app.py
  ```

---

## 9. How to run tests

Tests check that the **processed** graph files exist, are non-empty, and look internally consistent (endpoints exist, expected node/edge types appear).

**Order matters:** build the graph, then test.

```bash
python src/graph_build/build_graph_files.py
pytest tests/test_graph_outputs.py -v
```

To run everything under `tests/`:

```bash
pytest tests/ -v
```

---

## 10. Available demo scenarios

Full **presenter-oriented** walkthrough (questions, entities, what to highlight): **[`docs/demo_cases.md`](docs/demo_cases.md)**.

Short version:

| # | Scenario | What to try in the app |
|---|-----------|-------------------------|
| 1 | **The agent on the claim** — Writing agent overlaps with a claimant on a busy policy. | Claim-network style question around **Maria Garcia** / **CLM-2024-00102** (or claim id `claim_C9000000002`). |
| 2 | **Same bank account, different mailboxes** — Two people on one account at different addresses. | Shared-bank / “different addresses” demo. |
| 3 | **The claims sit on a family web** — Spouse and family ties link people who also appear on claims. | People-clusters / relationship demo. |
| 4 | **Care business at the insureds’ address** — A business (e.g. home care) shares an address with multiple people. | Business–address colocation demo. |

The app sidebar also lists **numbered demo questions** that map to these ideas.

**CLI sanity check** (optional): after building the graph,

```bash
PYTHONPATH=. python src/graph_query/query_graph.py
```

prints sample query output in the terminal.

---

## 11. Synthetic design notes

Current synthetic generation follows a layered approach while preserving existing schema and app compatibility:

1. baseline world generation
2. explicit suspicious motif injection
3. ambiguous weak-signal injection
4. structural bridge-like anomaly injection

Scenario truth labels are stored only under `eval/` and are not fed into graph build, routing, or investigation logic.

## Where this fits in the bigger picture

Longer term, the idea is to connect **documentation and enterprise data** to a **single explorable graph** and an assistant that helps investigators navigate it. PoC v1 focuses on a **small synthetic book** and a **working UI** you can run locally without external AI keys.
