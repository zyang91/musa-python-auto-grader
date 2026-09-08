# MUSA Grader

Semi-automatic grading for Jupyter Notebook assignments in **MUSA 5500: Geospatial
Data Science in Python**. Built to the prototype specification in [design.md](design.md),
and graded against the real student template in
[assignment_template/assignment-1.ipynb](assignment_template/assignment-1.ipynb).

The guiding principle: **automate what is objectively testable, surface ambiguity,
and make human review fast.** Every deduction traces back to a deterministic test,
a structural check, a notebook result, or an explicit human judgement.

## Grading works, not outputs

Students download their own Zillow ZHVI extract, and Zillow revises and extends
that file every month. Row counts, ZIP counts and final percentages therefore
differ legitimately between submissions, so the grader never compares against a
stored answer. It asks whether each step in the instructions *worked*, and
verifies it against the student's own data:

| Instruction | How it is checked |
|---|---|
| Load the data | pandas import, a `read_*` call, a relative path, a wide frame with many month columns |
| Trim to Philadelphia | every ZIP in the subset is a Philadelphia ZIP, and City/State hold no other place |
| Melt to tidy | rows equal **this student's own** (unique ZIPs x unique dates), values in a column named `ZHVI` |
| Split Center City | the two frames partition **this student's own** Philadelphia ZIP set, using the template's ZIP list |
| Percent increase function | called on a frame the grader builds, so the right answer is known whatever data was loaded |
| Compare the two groups | both averages exist, are plausible, and run in the Donut Effect direction |

The only fixed values in `rubrics/hw1.yaml` are the ones the assignment itself
fixes: the Center City ZIP list printed in the student template, and the two
comparison dates (2020-03-31 and 2022-03-31) named in the instructions.

A regression test proves the point: the same notebook graded against a shorter,
smaller, rescaled ZHVI file still scores 100/100.

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

That builds seven submissions covering the cases a TA meets: two correct, one with
plausible mistakes, one with two notebooks, one that crashes partway, one with no
notebook, and the untouched template.

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

`calculate_percent_increase(group_df)` takes a DataFrame, so it cannot be tested
with literal arguments. Instead the probe reads the column names and date dtype of
the student's own tidy frame, builds a synthetic group frame from interpolated
anchor points using those names, and calls the function with it. The expected
answer follows from the anchors, so it is known regardless of what the student
loaded. If the notebook crashed before producing a tidy frame, the probe falls
back to a frame carrying every common spelling (`date`/`Date`, `ZHVI`/`value`) at
once, so the function can still be tested.

The anchors deliberately imply a *different* answer for the first and last rows
than for the two dates named in the assignment. That is how the most common wrong
implementation is identified by name rather than just marked wrong:

| What the function does | Result |
|---|---|
| uses 2020-03-31 and 2022-03-31 | pass |
| uses the first and last rows | 50% credit, named in the feedback |
| returns `0.5` instead of `50` | 60% credit, named as a units slip |
| left as the unfilled template | 0, detected by parsing the body, not by searching for the template comment |

Hidden test *calls* run inside the student's kernel; the credit ratios and the
expected values stay on the grading host. Nothing in the container, and nothing in
the executed notebook saved back to `results/`, reveals the answer key — the probe
cells are stripped before the notebook is stored. A test asserts this.

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

Everything the grader expects lives in `rubrics/hw1.yaml` — the Center City ZIP
list, the comparison dates, the hidden test anchors, the credit ratios for common
near-misses. Change the YAML, press **Regrade**; no Python edits required.

> **Before grading a real class**, check the two things the assignment fixes:
> the `center_city_zips` list matches the one printed in the student template,
> and `start_date`/`end_date` match the dates in the instructions. Nothing else
> needs updating when the data changes — that is the point of the design above.

`examples/data/` holds a synthetic ZHVI file used only to exercise the pipeline.
It is not an answer key: no check compares against it.

---

## Optional LLM grading

Off by default, and unused by Assignment 1 — that assignment asks for no written
answer, so it has no qualitative rubric item. The machinery is here for the later
assignments, which do ask students to interpret their results. When enabled
(Settings → Qualitative grading, plus `ANTHROPIC_API_KEY` in the environment) it
grades only free-text responses.

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
tests/                  76 tests
examples/               synthetic data, three demo notebooks, seven submissions
assignment_template/    the notebooks handed to students
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
python -m pytest              # 76 tests, ~23s
python -m pytest -m "not slow"  # skip the ones that execute real kernels
```

---

## Scope

Implemented: Assignment 1, Streamlit UI, Docker isolation, rubric engine, review
queue, manual overrides, regrading, exports, optional LLM grading.

Not built (per design.md §37): Canvas API integration, authentication, cloud
deployment, student accounts, a database, live scraping, Assignments 3–6. Their
templates are in `assignment_template/` and the architecture is ready for them —
each needs a rubric YAML and a grader class.

Adding an assignment means a rubric YAML plus a grader class in `assignments/`
that registers `check_<rubric_id>` methods — `assignments/base.py` handles
dispatch, the execution check and error containment.
