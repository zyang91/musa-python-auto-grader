"""Build demo notebooks and a submissions folder that exercise the HW2 grader.

Four cases a TA actually meets: a submission that does everything the assignment
asks (including the extra credit), one that misses in the ways students really
miss — a pan/zoom `.interactive()` mistaken for a brush, only two Altair charts,
no conclusions under half the charts, an absolute path — one whose own run
errored, and one handed in without ever being run.

The important detail is that these notebooks are **executed here and saved with
their outputs, then handed in without the dataset**. That is how the class
submits: the grader has no copy of the student's data, cannot re-run anything,
and has to read the charts out of the outputs already in the file. Shipping
demo notebooks with empty outputs would exercise a path that never happens.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "philly_311_sample.csv"
SUBMISSIONS = HERE / "hw2_submissions"

TITLE = (
    "# Assignment #2: Exploring Philadelphia 311 Service Requests\n\n"
    "Data: 311 service and information requests, OpenDataPhilly."
)

LOAD = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    "import seaborn as sns\n"
    "import altair as alt\n\n"
    'requests = pd.read_csv("data/philly_311_sample.csv", parse_dates=["requested_datetime"])\n'
    'requests["month"] = requests["requested_datetime"].dt.to_period("M").dt.to_timestamp()\n'
    "requests.head()"
)


def good_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(TITLE),
        new_markdown_cell("## Load the data"),
        new_code_cell(LOAD),
        new_markdown_cell(
            "## 1. Requests over time (matplotlib)\n\n"
            "I want to show how the monthly volume of requests moves across two years. "
            "This is a single continuous series, and matplotlib is the right tool here "
            "because I need direct control over the axis ticks and the annotation "
            "marking the seasonal peak — seaborn and altair both make that harder than "
            "it needs to be for one line."
        ),
        new_code_cell(
            'monthly = requests.groupby("month").size()\n\n'
            "fig, ax = plt.subplots(figsize=(10, 4.5))\n"
            'ax.plot(monthly.index, monthly.values, color="#1f4e79", linewidth=2)\n'
            'ax.fill_between(monthly.index, monthly.values, color="#1f4e79", alpha=0.12)\n'
            'ax.set_title("Monthly 311 service requests, 2023-2024")\n'
            'ax.set_xlabel("Month")\n'
            'ax.set_ylabel("Requests")\n'
            'ax.grid(axis="y", alpha=0.3)\n'
            "plt.show()"
        ),
        new_markdown_cell(
            "Request volume is broadly flat month to month, with the busiest months "
            "in late spring. There is no sustained trend upward or downward across the "
            "two years, so the main conclusion is that 311 demand here is seasonal "
            "rather than growing."
        ),
        new_markdown_cell(
            "## 2. Time to close by category (seaborn)\n\n"
            "I chose a seaborn boxplot because the question is about the *distribution* "
            "of closure times within each category, not just the average. A boxplot "
            "shows the median, the spread and the long tail of slow cases in one pass, "
            "and seaborn draws one grouped by a categorical column with a single call."
        ),
        new_code_cell(
            "fig, ax = plt.subplots(figsize=(10, 5))\n"
            'sns.boxplot(data=requests, y="service_name", x="days_to_close",\n'
            '            palette="crest", ax=ax)\n'
            'ax.set_xlabel("Days to close")\n'
            'ax.set_ylabel("")\n'
            'ax.set_title("Days to close by request type")\n'
            "plt.tight_layout()\n"
            "plt.show()"
        ),
        new_markdown_cell(
            "Median closure time is similar across categories, but the tails are not: "
            "a handful of requests in every category stay open far longer than the "
            "median. The conclusion is that the category of a request predicts its "
            "typical closure time much less than whatever drives those outliers."
        ),
        new_markdown_cell("## 3. Requests by ZIP code (altair, with a transformation)"),
        new_code_cell(
            "alt.Chart(requests).mark_bar().encode(\n"
            '    x=alt.X("zipcode:N", title="ZIP code"),\n'
            '    y=alt.Y("count():Q", title="Requests"),\n'
            '    color=alt.Color("count():Q", scale=alt.Scale(scheme="blues"), legend=None),\n'
            '    tooltip=["zipcode", "count()"],\n'
            ').properties(title="311 requests by ZIP code", width=600)'
        ),
        new_markdown_cell(
            "Requests are concentrated in a handful of ZIP codes rather than spread "
            "evenly across the city. The busiest ZIP codes generate roughly twice the "
            "volume of the quietest ones."
        ),
        new_markdown_cell("## 4. Closure time distribution (altair, binned)"),
        new_code_cell(
            "alt.Chart(requests).mark_bar().encode(\n"
            '    x=alt.X("days_to_close:Q", bin=alt.Bin(maxbins=30), title="Days to close"),\n'
            '    y=alt.Y("count():Q", title="Requests"),\n'
            ').properties(title="How long requests stay open", width=600)'
        ),
        new_markdown_cell(
            "The distribution is strongly right-skewed: most requests close within "
            "about two weeks, and a thin tail runs out past sixty days. The mean is a "
            "poor summary of this variable and the median should be preferred."
        ),
        new_markdown_cell("## 5. Volume over time with a brush selection (altair)"),
        new_code_cell(
            'brush = alt.selection_interval(encodings=["x"])\n\n'
            "alt.Chart(requests).mark_line(point=True).encode(\n"
            '    x=alt.X("yearmonth(requested_datetime):T", title="Month"),\n'
            '    y=alt.Y("count():Q", title="Requests"),\n'
            '    color=alt.condition(brush, alt.value("#1f4e79"), alt.value("#c9d6e3")),\n'
            ").add_params(brush).properties(\n"
            '    title="Monthly requests — drag to select a period", width=600\n'
            ")"
        ),
        new_markdown_cell(
            "Dragging across the line confirms what the matplotlib version showed: the "
            "selected months in spring carry more requests than the winter months on "
            "either side of them."
        ),
        new_markdown_cell(
            "## Extra credit: cross-filtered dashboard\n\n"
            "Brushing the timeline filters the category chart beside it."
        ),
        new_code_cell(
            "period = alt.selection_interval(encodings=['x'])\n\n"
            "timeline = alt.Chart(requests).mark_area().encode(\n"
            '    x=alt.X("yearmonth(requested_datetime):T", title="Month"),\n'
            '    y=alt.Y("count():Q", title="Requests"),\n'
            ").add_params(period).properties(width=340, height=200)\n\n"
            "by_agency = alt.Chart(requests).mark_bar().encode(\n"
            '    x=alt.X("count():Q", title="Requests"),\n'
            '    y=alt.Y("agency_responsible:N", sort="-x", title=""),\n'
            ").transform_filter(period).properties(width=340, height=200)\n\n"
            "timeline | by_agency"
        ),
        new_markdown_cell(
            "Selecting any window on the timeline leaves the ranking of agencies "
            "essentially unchanged, which suggests the mix of responsible agencies is "
            "stable over time even as volume moves."
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def partial_notebook() -> nbformat.NotebookNode:
    """The realistic near-miss.

    Absolute path, an unlabelled matplotlib chart, only two Altair charts,
    `.interactive()` where a brush was asked for, and conclusions written under
    only some of the charts.
    """
    cells = [
        new_markdown_cell(TITLE),
        new_code_cell(
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            "import seaborn as sns\n"
            "import altair as alt\n\n"
            'requests = pd.read_csv("/Users/student/Desktop/philly_311_sample.csv")\n'
            "requests.head()"
        ),
        new_markdown_cell("## Matplotlib"),
        new_code_cell(
            'counts = requests["service_name"].value_counts()\n'
            "plt.bar(counts.index, counts.values)\n"
            "plt.show()"
        ),
        new_markdown_cell("## Seaborn"),
        new_code_cell('sns.histplot(data=requests, x="days_to_close")\nplt.show()'),
        new_markdown_cell(
            "A histogram was the natural choice because I wanted to see the shape of "
            "the closure-time variable, and seaborn's histplot picks sensible bins "
            "without any tuning."
        ),
        new_markdown_cell("## Altair"),
        new_code_cell(
            'alt.Chart(requests).mark_bar().encode(x="status:N", y="count()")'
        ),
        new_markdown_cell("Most requests are closed."),
        new_code_cell(
            'alt.Chart(requests).mark_point().encode(x="lon:Q", y="lat:Q").interactive()'
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def broken_notebook() -> nbformat.NotebookNode:
    """Downloads its data instead of submitting it, then fails on a typo.

    The host is deliberately a reserved `.invalid` name. Docker execution has no
    network at all, but local mode does — and pointing a fixture at a real open
    data endpoint would make the test suite download a live dataset.
    """
    cells = [
        new_markdown_cell(TITLE),
        new_code_cell(
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            "import altair as alt\n\n"
            'requests = pd.read_csv("https://opendataphilly.invalid/311/public_cases_fc.csv")\n'
            "requests.head()"
        ),
        new_markdown_cell("## Matplotlib"),
        new_code_cell(
            'plt.plot(requests["requested_datetimee"], requests["days_to_close"])\n'
            "plt.show()"
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def _metadata() -> dict:
    return {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    }


NOTEBOOKS = {
    "hw2_good_submission.ipynb": good_notebook,
    "hw2_partial_submission.ipynb": partial_notebook,
    "hw2_broken_submission.ipynb": broken_notebook,
}

# student folder -> (saved notebook, submitted filename, keep the outputs?)
LAYOUT = {
    "student_101": ("hw2_good_submission.ipynb", "assignment-2.ipynb", True),
    "student_102": ("hw2_partial_submission.ipynb", "musa5500_hw2.ipynb", True),
    "student_103": ("hw2_broken_submission.ipynb", "assignment2.ipynb", True),
    # Did the work, then handed in a notebook they never ran: no outputs, so
    # there is nothing for the grader to read and no data to regenerate it from.
    "student_104": ("hw2_good_submission.ipynb", "assignment-2.ipynb", False),
}


def execute(nb: nbformat.NotebookNode, timeout: int = 120) -> nbformat.NotebookNode:
    """Run a demo notebook next to the data, the way a student would.

    Errors are allowed through on purpose: one of these notebooks is meant to
    be handed in with a traceback still in it.
    """
    from nbclient import NotebookClient

    with tempfile.TemporaryDirectory() as workdir:
        target = Path(workdir) / "data"
        target.mkdir()
        shutil.copy2(DATA, target / DATA.name)
        NotebookClient(
            nb, timeout=timeout, kernel_name="python3", allow_errors=True,
            resources={"metadata": {"path": workdir}},
        ).execute()
    return nb


def strip_outputs(nb: nbformat.NotebookNode) -> nbformat.NotebookNode:
    for cell in nb.cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    return nb


def write_notebooks() -> None:
    """Build, run and save the demo notebooks with their outputs."""
    for filename, builder in NOTEBOOKS.items():
        nbformat.write(execute(builder()), str(HERE / filename))


def build_submissions(dest: Path) -> Path:
    """Lay out the demo submissions under ``dest``.

    Reads the saved notebooks written by ``write_notebooks`` so the outputs are
    already there — building them from the cell definitions alone would produce
    empty notebooks and test nothing. No data file is copied: the class does not
    hand one in.

    Tests call this with a temporary directory so they never depend on — or
    overwrite — whatever is sitting in `examples/hw2_submissions/`.
    """
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for student, (saved, filename, keep_outputs) in LAYOUT.items():
        source = HERE / saved
        nb = nbformat.read(str(source), as_version=4) if source.is_file() else NOTEBOOKS[saved]()
        if not keep_outputs:
            nb = strip_outputs(nb)
        folder = dest / student
        folder.mkdir(parents=True, exist_ok=True)
        nbformat.write(nb, str(folder / filename))
    return dest


def main() -> None:
    if not DATA.is_file():
        raise SystemExit("Run examples/make_hw2_data.py first.")
    write_notebooks()
    build_submissions(SUBMISSIONS)
    print(f"wrote {len(NOTEBOOKS)} notebooks and {len(LAYOUT)} submissions under {SUBMISSIONS}")


if __name__ == "__main__":
    main()
