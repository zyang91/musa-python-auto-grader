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


## Three assignments, three different things to grade against

The dataset decides what can be checked, and the three assignments hand the
grader three different situations:

| | Assignment 1 — The Donut Effect | Assignment 2 — Exploratory Visualization | Assignment 3 — Evictions and the NDVI |
|---|---|---|---|
| Dataset | One Zillow file, **downloaded by each student** | The student's own choice, **never handed in** | **One zip, distributed with the assignment** |
| Is there an answer key? | No — Zillow revises the file monthly, so counts and percentages differ legitimately | No — every student explores a different dataset | **Yes** — everyone runs the same five files |
| What is graded | Whether each step *worked*, against the student's own data | Whether the student can *produce the required elements* | Whether each result *is the right one* |
| Where the evidence comes from | The grading run's own execution | The outputs the student saved in the notebook | **Both** — the answers the notebook shows, confirmed by a re-run when one is possible |

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

## Assignment 3 — grading answers, for once

Assignment 3 hands out `assignment3-data.zip` and everyone works from it. That
one difference changes the whole design: for the first time the right answers
exist, so the grader checks results rather than inferring intent.

Philadelphia has **384** census tracts in `PA-tracts.geojson`. The fifteen listed
violation types cover **34,108** of the 434,052 rows of `li_violations.csv`. The
tidy eviction frame is **5,376** rows holding **149,472** evictions. The median
NDVI is **0.2025** inside the city limits and **0.3748** in the suburbs, and
**2,480** street trees sample to a median of **0.178**. None of those is an
opinion about a solution — they are facts about the shipped files, and every one
of them was re-computed under the variations students legitimately produce
(`crop=True` and `crop=False`, masked and filled arrays, `sjoin(how="inner")` and
`how="left"`) before it was written into `rubrics/hw3.yaml`. Where a step has two
defensible answers — the `unstack(fill_value=0).stack()` fill the instructions
mark *optional* gives 5,535 groups instead of 4,000 — both are listed rather than
one being called wrong.

That also changes what confidence means. In Assignment 1 several frames may
plausibly be "the Philadelphia subset", and the ambiguity is itself the finding.
Here a frame either holds 384 Philadelphia tracts or it does not; if one does,
the step demonstrably happened, and which variable holds it does not matter. So a
matched expected value scores at confidence 1.0, and confidence drops only where
the grader is choosing between readings of a partial answer.

### The answers come out of the notebook, not out of a re-run

Assignment 1 supplies one data file. Assignment 3 supplies five, and each has to
land at whatever relative path that student happened to write — sometimes built
with `os.path.join`, sometimes from a variable, sometimes `../data/`. When the
placement misses, the notebook dies at the first `read_file` and every step after
it is invisible: a submission that was entirely correct grades as a column of
zeros, for a reason that is nobody's fault.

The student's own run did not have that problem. They ran it with their data in
place and handed in the file with its outputs:

```
In  [3]: len(phl)
Out [3]: 384
```

That `384` is the answer to 1.1.2, sitting in the file. So is `34108`, and
`(368606317.0763259, 462551418.69179374)`, and `Median NDVI, city: 0.2025`. So is
`:HoloMap [year]` — the repr of the chart in 1.1.5, which states whether
`dynamic=False` was passed. Even the numbers a chart plots survive: bokeh writes
each column into the notebook as a base64 buffer, so the fourteen yearly totals
are still there to be summed.

So `grader/answers.py` reads them, and every item is graded on **two independent
readings**: what the submitted notebook shows, and what this grading run
produced. Neither is reliably better — a re-run can die on a path, a saved output
can be stale or hand-edited — so they are not ranked, they are combined: **a step
counts as done if either source shows the right answer.** Execution stops being
load-bearing and becomes corroboration.

| | The correct demo submission scores |
|---|---|
| with all five data files supplied | 99.5 / 100 |
| with no data supplied at all | 99.5 / 100 |

The data is therefore **optional** in the sidebar. Supply it and 19 of the 22
items come back confirmed by both readings independently; leave it out and the
grade comes from the submitted notebook alone, one confidence step lower (0.9
rather than 1.0), which is what a claim about someone else's run is worth.

Two rules keep this honest. A number must be *shown* to count — the cell values
inside a `head()` repr are not answers, and harvesting them would invent matches
against a rubric full of exact numbers. And source code alone is never full
marks: writing `gpd.sjoin(...)` is not evidence that it returned the right thing,
so a step the source plainly performs but never displays earns 70% and a look
from a person.

### The plots are graded on the objects, not the source

Two thirds of Part 1 is `hvplot`, and an hvplot call returns a holoviews object
that knows what it is. The probe reads those objects out of the kernel — from
`Out` as well as from named variables, because `df.hvplot(...)` on the last line
of a cell is never bound to a name — and the same structure is in the submitted
notebook as the object's saved repr. Either way the plotting requirements are
graded by their effect:

| The instructions ask for | What the object says (in the kernel, or in the saved repr) | Verdict |
|---|---|---|
| `groupby="year"`, `dynamic=False` | `HoloMap`, kdims `[year]`, 14 frames of `Polygons` | widget choropleth ✓ |
| the same, `dynamic=False` omitted | `DynamicMap`, **0 frames** | nothing renders — named, 60% credit |
| one map per violation type | `HoloMap`, kdims `[violationdescription]`, 15 frames | ✓ |
| two maps side by side | `Layout`, shape `(1, 2)`, children `[Polygons, Polygons]` | ✓ |
| the same, panels never trimmed | `Layout` whose children are `HoloMap` | still carries its widget — 75% |
| the yearly eviction trend | `Curve`, 14 points **summing to 149,472** | graded on the numbers plotted |

The last row is the point: a chart is not checked for existing, it is checked for
plotting the right numbers.

### Named mistakes, not just wrong answers

The rubric spends most of its configuration on telling the common near-misses
apart, because "wrong" is not useful feedback and a deduction a TA cannot explain
is a deduction they have to re-derive:

| What the student did | How it is recognised | Result |
|---|---|---|
| `points_from_xy(lat, lng)` | the data spans 39.8–40.1 east, not −75.2 | named as a coordinate swap, 30% |
| joined before trimming | the join carries 434,052 rows, not 34,108 | right step, wrong order — 70% |
| joined across two CRSs | the join lost rows, and none should be lost | named, 50% |
| NDVI from bands 3 and 4 | medians come back at −0.02, not 0.20 | off-by-one band index, named, 50% |
| `np.median` on a masked array | the medians are NaN | named as the NaN trap, 40% |
| suburbs = the envelope | its area is city + suburbs | `difference()` never applied, 50% |
| tracts left in EPSG:4326 | the polygon's area is 0.037, not 369 km² | named as degrees vs metres, 40% |

### What still goes to a person

One item, worth 3 points. The assignment marks the two street-tree figures on
being "clear and well-styled", and that is a statement about a picture. Labelling
and colour calls are extracted automatically and a provisional score is attached,
capped below full marks, but the item always returns as `manual_review`. The 1.4
extra credit carries 0 points and is flagged with a suggested bonus, the same way
Assignment 2's dashboard is.

And the standing rule is unchanged: **anything short of full marks reaches a
person**, whatever the rubric decided. The exact numbers above are what lets the
grader *clear* a submission with confidence — not what lets it mark one down
unattended.

### Where the 100 points go

| | Item | Points |
|---|---|---|
| | Notebook executes | 10 |
| 1.1.1 | Eviction data loaded with geopandas | 3 |
| 1.1.2 | Trimmed to Philadelphia (384 tracts) | 5 |
| 1.1.3 | Melted to tidy format (5,376 rows) | 6 |
| 1.1.4 | Yearly eviction trend with hvplot | 5 |
| 1.1.5 | Year-by-year choropleth with a widget | 5 |
| 1.2.1 | Violations loaded as a point GeoDataFrame | 4 |
| 1.2.2 | Trimmed to the fifteen types (34,108 rows) | 4 |
| 1.2.3 | Hex bin map with tracts overlaid | 4 |
| 1.2.4 | Spatial join to census tracts | 5 |
| 1.2.5 | Counted per type and tract | 5 |
| 1.2.6 | Merged back onto tract geometries | 3 |
| 1.2.7 | Choropleth per violation type with a widget | 5 |
| 1.3 | Evictions and violations side by side | 4 |
| 2.1.1 | Landsat scene opened with rasterio | 3 |
| 2.1.2 | City and suburb polygons | 5 |
| 2.1.3 | Masked, and the NDVI computed | 6 |
| 2.1.4 | Median NDVI compared | 4 |
| 2.2.1 | Street tree data loaded | 3 |
| 2.2.2 | NDVI sampled at the tree locations | 4 |
| 2.2.3 | Histogram and mapped tree points | 4 |
| 2.2.3 | Figure styling — *judged by a person* | 3 |
| 1.4 | Extra credit — *0 points, flagged, suggested 5* | 0 |
| | **Total** | **100** |

Execution is 10, Part 1 is 58 across thirteen steps, Part 2 is 32 across eight.
Part 1 carries more because it is more of the work — thirteen of the twenty steps
— and Part 2's items are individually larger because each one is a bigger piece
of reasoning. Within each part the weight follows what the step is worth getting
right: the melt, the spatial join and the NDVI masking are where the assignment
is actually taught, and the loading steps are worth 3 or 4 because they are hard
to get wrong and cheap to fix.

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

For Assignment 3:

```bash
python examples/make_hw3_submissions.py
```

That builds four submissions — one that does everything including the extra
credit, one that makes the near-misses students really make, one that swaps
latitude and longitude and crashes partway, and the untouched template — and
**runs them against the assignment zip so their outputs are saved**, which is how
the class hands this one in. It needs the geospatial stack installed; without it
the notebooks are written empty and it says so.

Then pick **Assignment 3**, load `examples/hw3_submissions`, and run. **No data
file is needed**: the answers are in the outputs each student saved.

```bash
python cli.py grade examples/hw3_submissions --rubric rubrics/hw3.yaml
```

Scores: 99.5, 68.5, 34.5 and 10 out of 100. The 0.5 the correct one does not get
is the styling item's ceiling — no submission reaches full marks on a judgement
item without a person.

To have the grader re-run each notebook and confirm what it shows, unzip the data
and supply all five files:

```bash
unzip assignment_template/assignment3-data.zip -d /tmp/hw3
```

```bash
python cli.py grade examples/hw3_submissions --rubric rubrics/hw3.yaml \
  --data /tmp/hw3/assignment3-data/PA-tracts.geojson \
  --data /tmp/hw3/assignment3-data/li_violations.csv \
  --data /tmp/hw3/assignment3-data/landsat8_philly.tif \
  --data /tmp/hw3/assignment3-data/City_Limits.geojson \
  --data /tmp/hw3/assignment3-data/ppr_tree_canopy_points_2015.geojson
```

The correct submission still scores 99.5 — with 19 of its items now confirmed by
both readings independently — and the two that only partly worked score higher,
because a re-run sees steps whose results they never displayed. The sidebar names
any of the five files that are missing, since supplying four of them silently
weakens every step that reads the fifth.

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
Upload the file (or, for Assignment 3, all five files) once — sidebar, or `--data`
on the CLI — and before each submission runs it places them at:

* every relative path the notebook actually reads from — parsed out of the
  notebook, including paths held in a variable rather than passed inline, and
* the conventional `data/<name>` and `<name>` locations, for notebooks whose path
  is built dynamically.

So a notebook reading `data/zillow.csv` and one reading
`data/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` both find their file,
with no naming convention imposed on the class. With several supplied files each
target path takes the one whose name is closest to it, so Assignment 3's five
files land where the notebook asks for each of them. The file is **hard-linked**, not
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

Assignment 3 put four more object kinds in the namespace, so the probe describes
those too: a GeoDataFrame's CRS, geometry types and total area; a numpy array's
NaN-aware statistics, which is the only way to describe an NDVI array that is
mostly NaN outside the polygon that produced it; shapely geometries and open
rasterio datasets in place; and holoviews objects — their key dimensions, frame
count, layout shape and the values actually plotted — read from `Out` as well as
from named variables, since a chart on the last line of a cell is never bound to
a name. One summary is deliberately compact: 384 GEOIDs are far past the
value-sample cap, so instead of the list the probe sends a histogram of their
first five characters, which answers "is every row in Philadelphia County?" in a
handful of bytes.

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
| deterministic test, or a matched expected value | confidence 1.0 |
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

`rubrics/hw3.yaml` is the opposite extreme, and it is the one file to check when
the assignment's data changes. Every expected count and median in it was computed
from `assignment_template/assignment3-data.zip`; hand out a different zip and
they all move together. Re-run the reference solution and update the numbers, or
widen the tolerances — no Python changes either way. Those numbers are also what
makes grading from saved outputs possible at all: `384` in a notebook means
something only because the rubric knows Philadelphia has 384 tracts in this file.

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
  answers.py            the answers a notebook's own saved outputs state
  inspection.py         candidate matching over the probe payload
  scoring.py            review policy, class summary
  feedback.py           student markdown feedback
  results.py            session persistence and exports
  llm.py                optional qualitative grading
assignments/
  base.py               rubric dispatch, shared execution check
  hw1.py                Assignment 1 checks
  hw2.py                Assignment 2 checks
  hw3.py                Assignment 3 checks
rubrics/hw1.yaml        the grading policy, as configuration
rubrics/hw2.yaml        the grading policy, as configuration
rubrics/hw3.yaml        the answer key, as configuration
docker/                 grading image
tests/                  301 tests
examples/               synthetic data, nine demo notebooks, fifteen submissions
assignment_template/    the notebooks handed to students, and HW3's data zip
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
python -m pytest              # 301 tests, ~40s
python -m pytest -m "not slow"  # skip the ones that execute real kernels
```

---

## Scope

Implemented: Assignments 1, 2 and 3, Streamlit UI, Docker isolation, rubric
engine, review queue, manual overrides, regrading, exports, optional LLM grading.

Not built (per design.md §37): Canvas API integration, authentication, cloud
deployment, student accounts, a database, live scraping, Assignments 4–6. Their
templates are in `assignment_template/` and the architecture is ready for them —
each needs a rubric YAML and a grader class.

Adding an assignment means a rubric YAML plus a grader class in `assignments/`
that registers `check_<rubric_id>` methods — `assignments/base.py` handles
dispatch, the execution check and error containment.
