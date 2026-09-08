# MUSA Grader

Semi-automatic grading for Jupyter Notebook assignments in **MUSA 5500: Geospatial
Data Science in Python**. Built to the prototype specification in [design.md](design.md).

The guiding principle: **automate what is objectively testable, surface ambiguity,
and make human review fast.** Every deduction traces back to a deterministic test,
a structural check, a notebook result, or an explicit human judgement.

---

## Quickstart

```bash
pip install -r requirements.txt
```

Build the grading container once (recommended — student code is untrusted):

```bash
docker build -t musa-grader:latest -f docker/Dockerfile .
```

Generate the demo data and example submissions:

```bash
python examples/make_example_data.py && python examples/make_example_submissions.py
```

Start the app:

```bash
streamlit run app.py
```

Then, in the sidebar: pick **Assignment 1**, load `examples/submissions`, choose an
execution mode, and press **Run Grader**.

A terminal equivalent exists for scripted runs:

```bash
python cli.py grade examples/submissions --mode docker
```

---

## The TA workflow

```
Select Assignment 1
  → upload a Canvas ZIP or point at a submissions folder
  → review what discovery found
  → Run Grader (notebooks execute in isolated containers)
  → class overview: mean, distribution, most common issues
  → review queue: only the submissions that need a decision
  → per-student page: rubric scores, evidence, manual override
  → export grades.csv and per-student feedback
```

Pages: Overview · Submissions · Grading · Students · Review Queue · Class
Analytics · Export · Settings.

---

## How grading works

```
Streamlit UI  →  GradingService  →  executor  →  assignment grader  →  rubric engine  →  results store
```

The UI contains no grading logic; it calls `grader.service.GradingService` and
renders what comes back.

### 1. Discovery

Notebook filenames are not standardised, so submissions are scored by name hints,
depth and size. When two files look equally plausible the submission is **flagged,
not guessed** — it reaches the review queue with `multiple_notebooks`.

Both layouts from the spec are supported: a folder of student folders, and a flat
Canvas export ZIP (`doejane_12345_67890_assignment1.ipynb`, `_late_` included).

### 2. Execution

Each submission is copied into its own working directory, the notebook is
instrumented with probe cells, and a subprocess executes it — by default inside a
container with no network, capped memory and CPU, a read-only root filesystem and
no host environment variables (see [docker/README.md](docker/README.md)).

Errors do not stop grading. `allow_errors` is on, so the notebook runs to the end,
the first failing cell and its traceback are recorded, and every check that can
still run does. **A failed notebook never becomes an automatic zero.**

### 3. Inspection without variable names

Students do not use the solution's variable names, so the probe describes the
kernel's namespace rather than looking anything up by name: for every DataFrame it
records shape, columns, dtypes, a head sample, numeric summaries, low-cardinality
value samples, and — for boolean flag columns — which identifiers they mark.

The assignment grader then looks for objects that *look like* the expected result
(right ZIP prefix, right row count, right roles) and reports how many plausible
candidates it saw. One unique match is high confidence; two is 0.75; more is 0.40.
Anything below the threshold (default 0.80) goes to the review queue.

### 4. Hidden tests

Hidden test *calls* run inside the student's kernel; the *expected values* stay on
the grading host. Nothing in the container, and nothing in the executed notebook
saved back to `results/`, reveals the answer key — the probe cells are stripped
before the notebook is stored. A test suite asserts this.

Common near-misses are graded as near-misses rather than as failures: returning
`0.2` instead of `20` is scored as a units slip, and an inverted sign is scored as
an inverted sign.

### 5. Confidence and review

| Signal | Result |
|---|---|
| deterministic test | confidence 1.0 |
| one uniquely matching object | 0.98 |
| two plausible objects | 0.75 → review |
| high ambiguity | 0.40 → review |
| execution failure, multiple notebooks, missing objects | review |
| qualitative item without LLM grading | review |

### 6. Manual overrides

Both scores are always kept:

```json
{ "automatic_score": 12, "manual_override": true,
  "final_score": 15, "override_reason": "Alternative valid implementation." }
```

Re-running the grader regenerates the automatic scores; **Preserve manual
overrides** restores the human decisions on top.

---

## Configuring the rubric

Everything the grader expects lives in `rubrics/hw1.yaml` — ZIP lists, row counts,
tolerances, hidden test cases, the final answer. Change the YAML, press
**Regrade**; no Python edits required.

> **Before grading a real class**, replace the values marked `VERIFY` with the
> official solution's numbers. The shipped values are the ground truth of the
> synthetic dataset in `examples/data/`, which `examples/make_example_data.py`
> generates and whose answers it prints.

To point the grader at the real assignment data: drop the official CSV into the
students' `data/` folders, re-run the solution notebook, and update
`expected_zip_count`, `expected_row_count`, `expected_center_city_zips` and
`expected_value` to match.

---

## Optional LLM grading

Off by default. When enabled (Settings → Qualitative grading, plus
`ANTHROPIC_API_KEY` in the environment) it grades only the written response.

The interface is provider-independent: `LLMQualitativeGrader` takes any
`complete(system, user) -> str` callable. Two rules are enforced in code rather
than left to the caller — student names, emails and ids are redacted before the
text is sent, and any low-confidence judgement is routed to a human instead of
being applied silently.

With LLM grading off, written responses are scored structurally (does a real
response exist, is it substantial) and always sent to the review queue.

There is deliberately **no AI-writing detection, no plagiarism scoring and no
writing-style classification**. The grader evaluates assignment performance.

---

## Project structure

```
app.py                  Streamlit entry point
cli.py                  headless grading
ui/                     one module per page, plus shared components and state
grader/
  service.py            orchestration; the only entry point the UI needs
  discovery.py          folders, Canvas ZIPs, notebook selection
  executor.py           instrumentation, Docker/local execution
  probe_runtime.py      injected into the student kernel; never runs on the host
  notebook_runner.py    standalone runner executed in the subprocess/container
  notebook.py           static analysis and read-only rendering
  inspection.py         candidate matching over the probe payload
  scoring.py            review policy, class summary
  feedback.py           student markdown feedback
  results.py            session persistence and exports
  llm.py                optional qualitative grading
assignments/
  base.py               rubric dispatch, shared execution check
  hw1.py                Assignment 1 checks
rubrics/hw1.yaml        the answer key, as configuration
docker/                 grading image
tests/                  70 tests
examples/               synthetic data, three demo notebooks, six submissions
```

---

## Results on disk

```
results/<session_id>/
├── grades.csv                 student_id, score, execution status, review flags
├── grading_session.json       full state; reload it from the Overview page
├── summary.json               class summary
├── flagged_submissions.csv    the review queue
├── class_report.md
├── feedback/<student>.md      student-facing markdown
├── executed_notebooks/        probe cells stripped
└── raw_results/<student>.json rubric-level detail with evidence
```

---

## Tests

```bash
python -m pytest              # 70 tests, ~17s
python -m pytest -m "not slow"  # skip the ones that execute real kernels
```

---

## Scope

Implemented: Assignment 1, Streamlit UI, Docker isolation, rubric engine, review
queue, manual overrides, regrading, exports, optional LLM grading.

Not built (per design.md §37): Canvas API integration, authentication, cloud
deployment, student accounts, a database, live scraping, Assignments 2–6.

Adding an assignment means a rubric YAML plus a grader class in `assignments/`
that registers `check_<rubric_id>` methods — `assignments/base.py` handles
dispatch, the execution check and error containment.
