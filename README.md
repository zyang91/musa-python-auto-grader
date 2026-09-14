# MUSA Grader

Semi-automatic grading for Jupyter Notebook assignments in **MUSA 5500: Geospatial
Data Science in Python**. 
The guiding principle: **automate what is objectively testable, surface ambiguity,
and make human review fast.** Every deduction traces back to a deterministic test,
a structural check, a notebook result, or an explicit human judgement. 

**Grading principle**: The grader is a screening tool, not a scoring tool. It can only clear a submission, never mark one down: any submission that does not come back at full marks is read by a person, and the deduction stands or falls on that reading. Efficiency comes from the submissions the grader clears, not from trusting it where it is uncertain.

## Note on student data 
- Grading runs entirely on the instructor's or TA's machine; submissions are never uploaded anywhere.
- The Streamlit UI binds to localhost, and notebooks execute in a Docker container with no network access.
- Failure pattern is reproduced in tests/ with synthetic fixtures, and no student file, name, or identifier appears in this repository for model calibration only.
- We only used LLM to assist build this tool, but no student assignments were upload to LLM.


## Two assignments, two ways of not having an answer key

| | Assignment 1 — The Donut Effect | Assignment 2 — Exploratory Visualization |
|---|---|---|
| Dataset | One Zillow file, **supplied by the grader** | The student's own choice, **never handed in** |
| Why there is no answer key | Zillow revises the file monthly, so counts and percentages differ legitimately | Every student explores a different dataset |
| What is graded | Whether each step *worked*, against the student's own data | Whether the student can *produce the required elements* |
| Where the evidence comes from | The grading run's own execution | The outputs the student saved in the notebook |

---

## Assignment 1 — grading works, not outputs

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

## Assignment 2 — grading elements, not answers

Students pick their own dataset and hand in **the notebook alone**. The grader has
no copy of the data, so it cannot re-run anything: every submission dies at
`read_csv`. Nothing about the *content* of a chart was ever checkable, and this
assignment does not ask it to be — it asks whether the student can produce the
required elements.

So the rubric splits down the middle of the assignment text.

**Facts, graded automatically (70 points).** An Altair chart compiles to a
Vega-Lite specification, and that specification sits in the notebook's own saved
output. A mean/count/bin transformation, an interval brush and a
`transform_filter()` cross-filter are *read out of it* rather than guessed from
source text — which is what lets the grader tell apart the three things students
most often confuse:

| Student wrote | Vega-Lite says | Verdict |
|---|---|---|
| `alt.selection_interval()` + `add_params` | `params: [{select: {type: interval}}]` | brush ✓ |
| `.interactive()` | the same, plus `bind: "scales"` | pan/zoom, **not** a brush |
| `alt.selection_point()` | `select: {type: point}` | a selection, half credit |
| `transform_filter("datum.x > 5")` | `filter` with no param | a subset, **not** a transformation |
| `transform_filter(brush)` across `hconcat` | `filter: {param: …}` + two views | cross-filter ✓ extra credit |

**Judgement, graded by a person (30 points).** The assignment marks the matplotlib
chart on "colour choices and clarity" and asks for written reasoning under each
chart. A picture's quality and a paragraph's substance are not machine facts.
Those items come back as `manual_review` **always, whatever they score**, carrying
a provisional score built from real signals — labelling and colour calls extracted
from the source, word counts and the position of each markdown cell — plus the
text itself. A TA confirms or adjusts a number instead of starting from a blank
box.

Where the evidence is read from is recorded per chart. When an instructor *does*
supply the dataset, a freshly executed chart takes over from the saved one
automatically, and the confidence rises from 0.85 to 0.95.

The extra credit dashboard carries **0 points** in the rubric so it never inflates
the maximum. When it is found, the item is flagged with the suggested bonus; a
manual override on it adds to the student's total without changing what they are
graded out of.

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

That builds seven Assignment 1 submissions covering the cases a TA meets: two
correct, one with plausible mistakes, one with two notebooks, one that crashes
partway, one with no notebook, and the untouched template. They contain notebooks
only — no data — exactly as the class hands work in.

For Assignment 2:

```bash
python examples/make_hw2_data.py && python examples/make_hw2_submissions.py
```

Those four are **executed against the data and saved with their outputs, then
handed in without it** — which is how the class submits, and the only reason there
is anything to grade. One does everything including the extra credit, one makes
the usual near-misses, one errored in the student's own run, and one was never run
at all.

Start the app:

```bash
streamlit run app.py
```

Then, in the sidebar: pick **Assignment 1**, **upload the assignment data file**
(for the demo, `examples/data/zillow_zhvi.csv`), load `examples/submissions`,
choose an execution mode, and press **Run Grader**.

Assignment 2 needs no data file at all: pick **Assignment 2**, load
`examples/hw2_submissions`, and run. Every notebook will fail to execute, and that
is expected — the rubric grades the outputs the students saved.

For a real class, download the ZHVI extract from
[Zillow research data](https://www.zillow.com/research/data/) — *ZHVI All Homes,
by ZIP code* — and upload that instead. Nothing else changes.

The sidebar takes the file by **upload**, so it does not have to live anywhere in
particular; uploads are kept in `.musa_grader_data/` and survive a restart. If the
file is already on the grading machine, the *"or use a file already on this
machine"* expander takes a path instead. Either way the files currently in use are
listed with their size and can be removed individually, and the app refuses to
start a run until at least one is set.

A terminal equivalent exists for scripted runs:

```bash
python cli.py grade examples/submissions --mode docker --data examples/data/zillow_zhvi.csv
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

### 0. The data comes from you, not the students

Students hand in **a notebook and nothing else**, so the grader supplies the data.
Upload the Zillow extract once (sidebar, or `--data` on the CLI) and before each
submission runs it places that file at:

* every relative path the notebook actually reads from — parsed out of the
  notebook, including paths held in a variable rather than passed inline, and
* the conventional `data/<name>` and `<name>` locations, for notebooks whose path
  is built dynamically.

So a notebook reading `data/zillow.csv` and one reading
`data/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` both find their file,
with no naming convention imposed on the class. The file is **hard-linked**, not
copied, so fifty submissions cost one copy of a 117 MB extract rather than fifty.
A student's own file is never overwritten, and paths that escape the working
directory (`../`, absolute, Windows drive letters) are refused.

Everyone is then graded against the *same* data, which is what makes the class
comparable — and a notebook that hardcodes `/Users/me/Desktop/...` still fails, as
it should, because that path cannot be supplied.

### 1. Discovery

Notebook filenames are not standardised, so submissions are scored by name hints,
depth and size. When two files look equally plausible the submission is **flagged,
not guessed** — it reaches the review queue with `multiple_notebooks`.

Both layouts from the spec are supported: a folder of student folders, and a flat
Canvas export ZIP (`doejane_12345_67890_assignment1.ipynb`, `_late_` included).
Submissions are expected to be notebooks only — the data is supplied by you.

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
| **any deduction at all** | **review** |

The last row is the strongest rule: **anything short of full marks goes to the
review queue.** An automated deduction is a claim about a student's work, so a
person signs off before it becomes a grade. Full marks need no defence and pass
straight through. The queue entry names which items lost points and how many, and
still sorts broken submissions above small deductions. Marking a submission
reviewed — or overriding it back to full marks — clears it. The rule can be turned
off in Settings for a large class.

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

Everything the grader expects lives in `rubrics/hw1.yaml` and `rubrics/hw2.yaml` —
the Center City ZIP
list, the comparison dates, the hidden test anchors, the credit ratios for common
near-misses. Change the YAML, press **Regrade**; no Python edits required.

> **Before grading a real class**, check the two things the assignment fixes:
> the `center_city_zips` list matches the one printed in the student template,
> and `start_date`/`end_date` match the dates in the instructions. Nothing else
> needs updating when the data changes — that is the point of the design above.

For Assignment 2 there is nothing to correct against an official solution — no
expected values exist. What `rubrics/hw2.yaml` holds instead is policy: how much a
chart that never rendered is worth, what counts as a transformation, how many
words make a discussion, and the ceiling on an unreviewed aesthetics score.

`examples/data/` holds a synthetic ZHVI file and a synthetic 311 extract, used
only to exercise the pipeline. Neither is an answer key: no check compares against
them.


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
  charts.py             chart evidence: library attribution, Vega-Lite specs
  inspection.py         candidate matching over the probe payload
  scoring.py            review policy, class summary
  feedback.py           student markdown feedback
  results.py            session persistence and exports
  llm.py                optional qualitative grading
assignments/
  base.py               rubric dispatch, shared execution check
  hw1.py                Assignment 1 checks
  hw2.py                Assignment 2 checks
rubrics/hw1.yaml        the answer key, as configuration
rubrics/hw2.yaml        the grading policy, as configuration
docker/                 grading image
tests/                  197 tests
examples/               synthetic data, six demo notebooks, eleven submissions
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
python -m pytest              # 197 tests, ~33s
python -m pytest -m "not slow"  # skip the ones that execute real kernels
```

---

## Scope

Implemented: Assignments 1 and 2, Streamlit UI, Docker isolation, rubric engine,
review queue, manual overrides, regrading, exports, optional LLM grading.

Not built (per design.md §37): Canvas API integration, authentication, cloud
deployment, student accounts, a database, live scraping, Assignments 3–6. Their
templates are in `assignment_template/` and the architecture is ready for them —
each needs a rubric YAML and a grader class.

Adding an assignment means a rubric YAML plus a grader class in `assignments/`
that registers `check_<rubric_id>` methods — `assignments/base.py` handles
dispatch, the execution check and error containment.
