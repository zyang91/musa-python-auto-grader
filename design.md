# MUSA Grader

## Prototype Specification

### Purpose

Build a local, semi-automatic grading system for Jupyter Notebook assignments in **MUSA 5500: Geospatial Data Science in Python**.

The system should provide a simple graphical interface that allows an instructor or TA to:

- upload or select student submissions
- run the autograder
- monitor grading progress
- review rubric-level results
- inspect flagged submissions
- manually adjust scores
- export final grades and feedback

The first prototype should focus on **Assignment 1**, while keeping the architecture modular enough to support Assignments 2–6 later.

---

# 1. Core Philosophy

The grader should separate grading into three categories.

## 1.1 Deterministic grading

Use Python tests whenever an answer can be objectively verified.

Examples:

- notebook executes successfully
- required functions exist
- functions return correct results
- expected columns exist
- filtering is correct
- numeric answers fall within tolerance
- required transformations are completed

These tests should directly contribute to the score.

---

## 1.2 Structural grading

Inspect notebook structure and execution results.

Examples:

- required markdown responses exist
- plots exist
- requested libraries are used
- functions are defined
- notebook executes top-to-bottom
- outputs are generated
- relative rather than absolute paths are used

Structural grading should be deterministic whenever possible.

---

## 1.3 Qualitative grading

Some rubric items require interpretation.

Examples:

- explanation quality
- interpretation of results
- visualization readability
- discussion of patterns
- reasoning

For the prototype, qualitative sections should support:

```text
manual grading
or
optional LLM-assisted grading
```

LLM grading should never silently determine uncertain scores.

Low-confidence judgments must be flagged for human review.

---

# 2. Prototype Scope

The first version should include:

```text
Assignment 1 support
Jupyter Notebook submissions
local grading
Docker-based isolated execution
Streamlit UI
rubric-level grading
manual score adjustment
manual review queue
CSV export
student feedback export
class summary
```

Do not build Canvas integration yet.

---

# 3. Primary User Workflow

The intended workflow is:

```text
Open MUSA Grader
       ↓
Select Assignment 1
       ↓
Upload Canvas submission ZIP
or choose local submissions folder
       ↓
System discovers students/notebooks
       ↓
Click "Run Grader"
       ↓
Notebooks execute in isolated environments
       ↓
Rubric tests run
       ↓
Results appear in dashboard
       ↓
TA reviews flagged submissions
       ↓
TA can manually override scores
       ↓
Finalize grades
       ↓
Export grades.csv + feedback
```

The UI should make this workflow understandable without requiring command-line use.

---

# 4. Technology Stack

Recommended prototype stack:

```text
Frontend/UI:
Streamlit

Core grading:
Python

Notebook handling:
nbformat
nbclient
nbconvert

Data:
pandas

Configuration:
YAML

Isolation:
Docker

Charts:
Altair or Plotly

Optional LLM:
provider-independent interface
```

The grading engine must remain separate from Streamlit.

The UI should call grading functions rather than contain grading logic directly.

Example architecture:

```text
Streamlit UI
     ↓
Grading service
     ↓
Notebook executor
     ↓
Assignment grader
     ↓
Rubric engine
     ↓
Results store
```

---

# 5. UI Layout

The application should use a left sidebar and a main workspace.

## Sidebar

Include:

```text
MUSA Grader

Assignment
[ Assignment 1 ▼ ]

Submissions
[ Upload Canvas ZIP ]

or

[ Select Local Folder ]

Execution Mode
● Docker
○ Unsafe Local

Qualitative Grading
☐ Enable LLM grading

[ Run Grader ]
```

The sidebar should also show grader version.

Example:

```text
MUSA Grader v0.1
Rubric: HW1-v1
```

---

# 6. Main Dashboard

Before grading:

```text
------------------------------------------------

MUSA Grader
Assignment 1

No grading session currently loaded.

Upload student submissions using the sidebar.

------------------------------------------------
```

After submissions are loaded:

```text
Assignment 1

52 submissions detected

[ Run Grader ]

Students detected
────────────────────────

✓ student_001
✓ student_002
✓ student_003
⚠ student_004 — multiple notebooks
...
```

---

# 7. Grading Progress UI

When grading begins, show progress.

Example:

```text
Grading Assignment 1

████████████████░░░░  38 / 52

Currently grading:
student_039

Notebook execution     ✓
Structural checks      ✓
Hidden tests           running
Feedback generation    waiting
```

Do not freeze the interface without feedback.

Display counts:

```text
Completed       38
Successful      34
Flagged          3
Failed           1
Remaining       14
```

---

# 8. Class Overview Dashboard

Once grading finishes, show summary cards.

Example:

```text
┌──────────────────┐
│ 52               │
│ Submissions      │
└──────────────────┘

┌──────────────────┐
│ 87.4             │
│ Mean Grade       │
└──────────────────┘

┌──────────────────┐
│ 9                │
│ Need Review      │
└──────────────────┘

┌──────────────────┐
│ 4                │
│ Execution Errors │
└──────────────────┘
```

Below the cards, display grade distribution.

Example:

```text
Grade Distribution

100 ┤
 90 ┤        ███████
 80 ┤    █████████████
 70 ┤   ███████
 60 ┤ ██
```

Also display common issues.

Example:

```text
Most Common Issues

14   Incorrect Center City ZIP classification
9    Absolute file paths
7    Percent-change function failed hidden tests
4    Notebook execution failures
```

---

# 9. Submission Table

The main dashboard should contain a searchable student table.

Example:

| Student | Score | Execution | Confidence | Review |
|---|---:|---|---:|---|
| student_001 | 96 | ✓ | 100% | |
| student_002 | 88 | ✓ | 96% | |
| student_003 | 74 | ⚠ | 71% | Review |
| student_004 | — | ✕ | — | Review |

Support:

```text
search
sort
filter
```

Filters:

```text
All
Needs Review
Execution Failed
Score < 70
Low Confidence
Completed
```

Clicking a student opens the Submission Review page.

---

# 10. Student Review Page

This is the most important UI screen.

Header:

```text
student_003

Current Score: 84 / 100

Status: Needs Review

[ Previous Student ]     [ Next Student ]
```

Display rubric items as expandable sections.

Example:

```text
✓ Notebook Execution
10 / 10

Notebook executed successfully.
```

```text
✓ Philadelphia Subset
15 / 15

Expected Philadelphia observations were found.

Confidence: 100%
```

```text
⚠ Center City Classification
10 / 15

Expected ZIP codes:
19102
19103
19106
19107

Student output differs in two ZIP codes.

Confidence: 82%

[ View Evidence ]
```

```text
✕ Percent Increase Function
12 / 20

Hidden Tests

✓ 100 → 120
✓ 50 → 75
✕ 200 → 100
✓ 40 → 40
```

---

# 11. Manual Score Adjustment

Every rubric item should allow TA intervention.

Example:

```text
Automatic Score
12 / 20

Manual Score
[ 15 ]

TA Comment
[ Student used a valid alternative approach. ]

☑ Override automatic grade

[ Save ]
```

The system should preserve both:

```text
automatic_score
final_score
```

Example:

```json
{
  "automatic_score": 12,
  "manual_override": true,
  "final_score": 15,
  "override_reason": "Alternative valid implementation."
}
```

Never overwrite the original automated result.

---

# 12. Evidence Viewer

Each rubric item should provide evidence explaining the grade.

Possible evidence:

```text
student code
function output
dataframe preview
hidden test results
execution traceback
markdown answer
plot existence
```

Example:

```text
Evidence

Detected dataframe:
Name: center_city_df
Rows: 412

Columns:
zipcode
date
value
group

Detected ZIP values:
19102
19103
19106
19107
19123
```

The UI should emphasize traceability.

A TA should always be able to understand why points were deducted.

---

# 13. Notebook Viewer

The student page should provide access to the notebook.

Tabs:

```text
[ Grading ]
[ Notebook ]
[ Execution Log ]
[ Raw Results ]
```

Notebook tab should show:

- markdown cells
- code cells
- outputs
- execution errors

A full notebook editor is not required.

Read-only rendering is sufficient.

---

# 14. Review Queue

Provide a dedicated page:

```text
Review Queue
```

Example:

| Student | Reason | Score |
|---|---|---:|
| student_003 | Low-confidence dataframe match | 84 |
| student_014 | Notebook execution failed | 65 |
| student_028 | Multiple notebook files | — |
| student_041 | Qualitative response review | 91 |

Selecting an item opens that student's review page.

After review:

```text
[ Mark Reviewed ]
```

Reviewed submissions should disappear from the unresolved queue.

---

# 15. Status Colors

Use consistent visual status categories.

```text
Green
Passed / high confidence

Yellow
Warning / partial / moderate confidence

Red
Error / failed / requires review

Gray
Not graded / unavailable
```

Do not use color alone to communicate status.

Always include icons or text.

---

# 16. Input Structure

The application should support either:

### Option A — Canvas ZIP

```text
canvas_download.zip
```

The application extracts and identifies submissions.

### Option B — Local Folder

```text
submissions/
├── student_001/
│   ├── assignment1.ipynb
│   └── data/
├── student_002/
│   ├── homework1.ipynb
│   └── data/
└── student_003/
    └── submission.ipynb
```

Notebook filenames should not need to be standardized.

---

# 17. Submission Discovery

For each student directory:

1. find `.ipynb` files
2. identify the most likely assignment notebook
3. identify included data
4. copy files into isolated working directory
5. prepare notebook for execution

If there are multiple plausible notebooks:

```text
status = manual_review
reason = multiple_notebooks
```

Do not guess aggressively.

---

# 18. Execution Requirements

Never execute student notebooks directly in the host environment by default.

Use Docker isolation.

Each grading container should have:

```text
network disabled
CPU limit
RAM limit
execution timeout
temporary filesystem
no host credentials
no secret environment variables
```

Flow:

```text
copy submission
→ create container
→ execute notebook
→ save executed notebook
→ capture artifacts
→ destroy container
```

The UI may provide:

```text
Execution Mode

● Safe Docker
○ Unsafe Local
```

Unsafe Local should include a visible warning.

---

# 19. Execution Checks

Record:

```yaml
execution:
  success: true
  execution_time_seconds: 14.2
  timeout: false
  error_cell: null
  error_message: null
```

If execution fails:

- preserve traceback
- identify failing cell
- continue any grading that remains possible
- flag submission for review

Do not automatically assign zero.

---

# 20. Rubric Configuration

Rubrics should be YAML-based.

Example:

```text
rubrics/
├── hw1.yaml
├── hw2.yaml
├── hw3.yaml
├── hw4.yaml
├── hw5.yaml
└── hw6.yaml
```

Example:

```yaml
assignment:
  id: hw1
  name: Assignment 1
  total_points: 100

rubric:

  - id: notebook_execution
    name: Notebook executes successfully
    points: 10
    type: execution

  - id: data_loading
    name: Data loaded correctly
    points: 10
    type: structural

  - id: philadelphia_subset
    name: Philadelphia subset created correctly
    points: 15
    type: deterministic

  - id: tidy_transformation
    name: Data reshaped into tidy format
    points: 15
    type: deterministic

  - id: center_city_definition
    name: Center City ZIP codes identified correctly
    points: 15
    type: deterministic

  - id: percent_change_function
    name: Percent change function works correctly
    points: 20
    type: hidden_test

  - id: interpretation
    name: Written interpretation
    points: 15
    type: qualitative
```

---

# 21. Avoid Variable-Name Dependence

Do not assume students use official solution variable names.

Avoid:

```python
assert "philly_df" in namespace
```

Instead inspect available objects.

Example:

```python
def find_dataframe_with_columns(namespace, required_columns):
    candidates = []

    for name, obj in namespace.items():
        if isinstance(obj, pd.DataFrame):
            if set(required_columns).issubset(obj.columns):
                candidates.append((name, obj))

    return candidates
```

Candidate matching may use:

```text
column names
row counts
value ranges
index structure
expected dates
expected geography
expected transformed shape
```

Ambiguous matching should trigger review.

---

# 22. Hidden Tests

Functions should be tested independently.

Example:

```python
assert calculate_percent_increase(100, 120) == 20
assert calculate_percent_increase(50, 75) == 50
assert calculate_percent_increase(200, 100) == -50
```

Use tolerance where appropriate:

```python
math.isclose(
    actual,
    expected,
    rel_tol=1e-4,
    abs_tol=1e-4
)
```

Hidden tests must not appear in student notebooks.

---

# 23. Assignment 1 Prototype Tests

Implement tests for:

## Notebook reproducibility

Check:

```text
notebook parses
notebook executes
relative paths
required data available
```

Flag absolute paths such as:

```text
/Users/student/Desktop/data.csv
C:\Users\student\Downloads\data.csv
```

---

## Philadelphia subset

Find dataframe candidates consistent with the expected Philadelphia subset.

Check:

```text
correct geographic filter
expected columns
reasonable row count
absence of unrelated observations
```

---

## Wide-to-tidy transformation

Look for expected tidy structure.

Check:

```text
date/year values represented as rows
identifier columns preserved
expected value column
expected approximate row count
```

---

## Center City classification

Store expected ZIP definitions in rubric/configuration.

Example:

```yaml
expected_center_city_zips:
  - "19102"
  - "19103"
  - "19106"
  - "19107"
```

Verify against the actual assignment before finalizing the list.

---

## Percent increase function

Locate the relevant student-defined function.

Run hidden inputs.

Grade:

```text
formula
sign
numeric result
generalization to unseen values
```

---

## Final result

Check final expected value using tolerance.

Example:

```yaml
expected_value: 31.42
tolerance: 0.1
```

Replace with official solution values.

---

## Written response

Detect required markdown response.

For first prototype:

```text
response exists
response has meaningful content
```

Qualitative correctness may remain manual.

---

# 24. Test Result Format

Each rubric item returns:

```json
{
  "rubric_id": "percent_change_function",
  "name": "Percent change function",
  "points_possible": 20,
  "automatic_score": 18,
  "final_score": 18,
  "status": "partial",
  "confidence": 1.0,
  "feedback": "The function fails one hidden test.",
  "evidence": {
    "tests_passed": 4,
    "tests_failed": 1
  }
}
```

Statuses:

```text
pass
partial
fail
warning
manual_review
execution_error
not_found
```

---

# 25. Confidence System

Deterministic test:

```text
confidence = 1.0
```

Object inference may use lower confidence.

Example:

```text
one uniquely matching dataframe
0.98

two plausible objects
0.75

high ambiguity
0.40
```

Suggested review threshold:

```text
confidence < 0.80
→ manual review
```

---

# 26. LLM-Assisted Grading

LLM use must be optional.

The LLM should primarily handle:

```text
written explanations
interpretation
qualitative reasoning
```

Interface:

```python
class QualitativeGrader:

    def grade(
        self,
        question,
        student_response,
        rubric
    ):
        return {
            "score": 8,
            "max_score": 10,
            "confidence": 0.82,
            "feedback": "...",
            "manual_review": False
        }
```

Return structured JSON.

Do not send student names to the LLM.

Low confidence:

```text
manual_review = true
```

---

# 27. Academic Integrity

Do not implement:

```text
AI writing detection
ChatGPT detection
plagiarism speculation
writing-style classification
```

The grader evaluates assignment performance, not whether AI was used.

---

# 28. Results Storage

Store grading session data.

Example:

```text
results/
├── grades.csv
├── grading_session.json
├── summary.json
├── flagged_submissions.csv
├── feedback/
│   ├── student_001.md
│   └── ...
├── executed_notebooks/
│   ├── student_001.ipynb
│   └── ...
└── raw_results/
    ├── student_001.json
    └── ...
```

---

# 29. Export UI

Add an Export page.

Buttons:

```text
[ Download grades.csv ]

[ Download all feedback ]

[ Download flagged submissions ]

[ Download full grading archive ]
```

Grades CSV:

```csv
student_id,total_score,max_score,execution_status,manual_review
student_001,94,100,success,false
student_002,82,100,success,true
student_003,67,100,error,true
```

---

# 30. Student Feedback

Generate readable feedback.

Example:

```markdown
# Assignment 1 Feedback

Score: 91 / 100

## Notebook Execution
10 / 10

Notebook executed successfully.

## Philadelphia Subset
15 / 15

The expected observations were identified.

## Tidy Transformation
13 / 15

The transformation is mostly correct, but one identifier column was not preserved.

## Percent Increase Function
18 / 20

Four of five hidden tests passed.

## Review Status

Reviewed.
```

---

# 31. Regrading

The grader must support reproducible regrading.

If tests or rubric weights change:

```text
Re-run grading
```

should regenerate automated grades.

Manual overrides should optionally be preserved.

UI option:

```text
Regrade submissions

☑ Preserve manual overrides
☐ Re-run qualitative grading

[ Regrade ]
```

---

# 32. Application Navigation

Recommended Streamlit navigation:

```text
🏠 Overview
📥 Submissions
▶ Grading
👥 Students
⚠ Review Queue
📊 Class Analytics
📤 Export
⚙ Settings
```

For MVP, these may be implemented as tabs rather than separate routes.

---

# 33. Settings Page

Basic settings:

```text
Execution timeout
Memory limit
Confidence threshold
Docker image
LLM grading enabled
LLM provider
```

Advanced configuration does not need to be exposed yet.

Rubric editing may remain YAML-only in the first version.

---

# 34. Recommended Project Structure

```text
musa-grader/
│
├── app.py
├── README.md
├── requirements.txt
├── pyproject.toml
│
├── ui/
│   ├── overview.py
│   ├── submissions.py
│   ├── grading.py
│   ├── student_review.py
│   ├── review_queue.py
│   ├── analytics.py
│   └── export.py
│
├── grader/
│   ├── __init__.py
│   ├── executor.py
│   ├── discovery.py
│   ├── notebook.py
│   ├── scoring.py
│   ├── feedback.py
│   ├── results.py
│   └── utils.py
│
├── assignments/
│   ├── base.py
│   └── hw1.py
│
├── rubrics/
│   └── hw1.yaml
│
├── tests/
│   ├── test_execution.py
│   ├── test_hw1.py
│   └── fixtures/
│
├── docker/
│   └── Dockerfile
│
└── examples/
    ├── good_submission.ipynb
    ├── partial_submission.ipynb
    └── broken_submission.ipynb
```

---

# 35. Future Assignment Support

## HW2

Future checks:

```text
matplotlib figures
seaborn
Altair
interactive selection
transformations
chart encodings
written interpretation
```

Visualization quality remains partly manual.

---

## HW3

Future checks:

```text
GeoDataFrame
CRS
spatial joins
geometry
aggregation
NDVI
maps
```

---

## HW4

Future checks:

```text
OSMnx network
spatial filtering
crash aggregation
network analysis
scraping parser
```

Use frozen HTML fixtures rather than live Craigslist grading.

---

## HW5

Future checks:

```text
Census variables
restaurant data
joins
aggregation
correlations
geographic consistency
```

---

## HW6

Future checks:

```text
train/test split
Pipeline
GridSearchCV
cross-validation
metrics
model comparison
error analysis
poverty/fairness analysis
```

---

# 36. Prototype Development Phases

## Phase 1 — UI Shell

Build Streamlit application with:

```text
sidebar
submission upload
student table
mock overview dashboard
student review page
review queue
export page
```

Use fake data initially.

The goal is to establish the workflow.

---

## Phase 2 — Core Grading Engine

Implement:

```text
submission discovery
notebook parsing
notebook execution
rubric engine
structured results
```

Connect these results to the UI.

---

## Phase 3 — Assignment 1 Autograding

Implement real tests for:

```text
Philadelphia subset
tidy transformation
Center City classification
percent increase function
final answer
```

---

## Phase 4 — Safety and Review

Add:

```text
Docker isolation
timeouts
review flags
confidence scores
manual overrides
execution logs
```

---

## Phase 5 — Optional LLM Grading

Add qualitative grading support.

Do not make it required for the application to function.

---

# 37. What Not to Build Yet

Do not implement:

```text
Canvas API integration
authentication
cloud deployment
student-facing accounts
complex database infrastructure
React frontend
live scraping
automatic plagiarism detection
AI-use detection
all six graders
```

Use Streamlit and local files for the prototype.

---

# 38. Definition of Success

The prototype succeeds if a TA can:

1. launch the application
2. upload a folder or Canvas ZIP
3. see detected students
4. click **Run Grader**
5. monitor grading progress
6. view rubric-level scores
7. inspect evidence for deductions
8. review flagged submissions
9. manually adjust scores
10. export final grades and feedback

The system should reduce repetitive TA work while preserving transparency.

Every deduction must be traceable to:

```text
a deterministic test
a structural check
a notebook result
or an explicit human/LLM qualitative judgment
```

The core design principle is:

> **Automate what is objectively testable, surface ambiguity, and make human review fast.**