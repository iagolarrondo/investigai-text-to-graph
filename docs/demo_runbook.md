# Demo runbook — PoC v1 (team walkthrough)

**Time target:** ~15–20 minutes of live demo, plus Q&A. **Data:** 100% synthetic; safe to share screen.

---

## 1. Before the meeting (setup)

- [ ] Clone or sync the repo; open the **project root** (folder with `src/`, `data/`, `requirements.txt`).
- [ ] Create/activate a **virtual environment** and install deps: `pip install -r requirements.txt`.
- [ ] **Build the graph once** so `data/processed/nodes.csv` and `edges.csv` exist and are current.
- [ ] **Smoke-test the app** locally (start Streamlit, click one demo); fix Wi‑Fi / VPN if the browser cannot reach `localhost`.
- [ ] Optional: open **`docs/demo_cases.md`** on a second monitor or printed — your **talking-point** cheat sheet.
- [ ] Close unrelated tabs; set screen share to **whole window** or browser tab so the Streamlit UI is readable.

---

## 2. Commands to run

From the **project root**, in a terminal:

```bash
# 1) Fresh graph (run after any seed change, or if processed/ is missing)
python src/graph_build/build_graph_files.py

# 2) Start the UI (this terminal stays busy — use another tab for anything else)
streamlit run src/app/app.py
```

If imports fail:

```bash
PYTHONPATH=. streamlit run src/app/app.py
```

Optional sanity check (terminal output, not required for the meeting):

```bash
PYTHONPATH=. python src/graph_query/query_graph.py
```

---

## 3. What to open

| What | Where |
|------|--------|
| **Main demo** | Browser tab at the URL Streamlit prints (usually `http://localhost:8501`). |
| **Presenter notes** | `docs/demo_cases.md` — scenario names, entities, “what to mention.” |
| **If asked “where does data come from?”** | `data/interim/poc_v1_seed/` (inputs) → `data/processed/*.csv` (graph export). |

Do **not** rely on notebooks for the core demo unless you explicitly want a detour.

---

## 4. Suggested order on screen

1. **Landing / sidebar** — In one sentence: *synthetic graph, investigation-style answers, small subgraph each time.*
2. **Graph health (if exposed in UI)** or skip to demos — keep momentum.
3. Run the **four demos below in order** (they match the app’s numbered themes and `demo_cases.md`).
4. **Optional:** type one **free-text** question that mirrors scenario 1 or 2 (e.g. “Maria Garcia claim network”) to show routing — only if it worked in your prep run.
5. **Wrap** — limitations + next steps (section 6).

---

## 5. Which demo cases to use (and app alignment)

Use **`docs/demo_cases.md`** for detail; in the meeting hit these **in order**:

| Order | Demo case (name) | What you’re showing |
|-------|------------------|---------------------|
| 1 | **The agent on the claim** | Claim network around **Maria** / **CLM-2024-00102** — multiple claims on one policy + agent/claimant overlap flag. |
| 2 | **Policy concentration** (same data, different angle) | Claim network from **Jane** / **CLM-2024-00091** — busy policy without forcing the agent story first. |
| 3 | **Same bank account, different mailboxes** | Shared bank demo — two holders, two addresses. |
| 4 | **Care business at the insureds’ address** | Business–address colocation — **RESOLVE CARE** / shared Maple St address. |

**People / family cluster** (fifth pattern in `demo_cases.md`): run if time — app supports **related people clusters**; good bridge between “who’s connected” and claims.

For each stop, briefly point at: **tables** → **why you’re seeing this** → **supporting links** → **subgraph**.

---

## 6. What to say: limitations and next steps

**Limitations (honest, ~30 seconds)**

- Data is **fabricated** for the lab; not production volume, freshness, or access control.
- The graph is **CSV + in-memory** Python, not an enterprise graph database.
- **Natural language** is **rule-based** in v1 — not a trained fraud model and not legal advice.
- Visuals are **illustrative**, not a full analytics workstation.

**Next steps (constructive, not a promise)**

- Richer synthetic (or later, governed) data; more query templates; optional graph DB spike; clearer path to **integration** with real SIU workflows if the story lands.
- Send people to **`README.md`** to run it themselves and **`docs/roadmap.md`** for the longer view.

---

**Related:** [demo_cases.md](demo_cases.md) · [team_briefing.md](team_briefing.md) · [README.md](../README.md)
