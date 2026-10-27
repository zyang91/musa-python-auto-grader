"""Build demo submissions that exercise the HW5 grader.

Four cases a TA meets: a submission that does everything, one that misses in the
ways students really miss on this assignment (latitude passed as x, the
Census's negative placeholder left in, the tracts never merged with income, an
unlabelled plot with the question unanswered, and the full 8 GB Yelp dump read
instead of the Philadelphia extract), one that crashes at 1.3, and the
untouched template.

Like HW4's, these notebooks are **not executed**: running them would query the
Census API and download TIGER tracts, and the grader never opens the Yelp data.
The saved outputs a student's own run would leave behind are written in
directly, in the shapes Jupyter saves them in.

    python examples/make_hw5_submissions.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_output

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATE = ROOT / "assignment_template" / "assignment-5.ipynb"
SUBMISSIONS = HERE / "hw5_submissions"

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)

# Template cell index -> the step it answers. 1.6 has no code cell in the
# template; students add one after its markdown, at the end.
CELL = {"1.1": 3, "1.2": 5, "1.3": 7, "1.4": 9, "1.5": 11}


def result(text: str, html: str | None = None, count: int = 1):
    data = {"text/plain": text}
    if html:
        data["text/html"] = html
    return new_output("execute_result", data=data, execution_count=count)


def figure():
    return new_output(
        "display_data",
        data={"image/png": PNG, "text/plain": "<Figure size 800x500 with 1 Axes>"},
    )


def error(ename: str, evalue: str):
    return new_output("error", ename=ename, evalue=evalue, traceback=[f"{ename}: {evalue}"])


def frame_html(columns: list[str], rows: int) -> str:
    header = "".join(f"<th>{c}</th>" for c in columns)
    return (
        '<div><table border="1" class="dataframe"><thead><tr><th></th>'
        f"{header}</tr></thead><tbody><tr><th>0</th>"
        + "".join("<td>1</td>" for _ in columns)
        + f"</tr></tbody></table><p>{rows} rows × {len(columns)} columns</p></div>"
    )


GOOD = {
    "1.1": (
        "import cenpy\n"
        "import pandas as pd\n\n"
        'acs = cenpy.remote.APIConnection("ACSDT5Y2021")\n'
        "income = acs.query(\n"
        '    cols=["NAME", "B19013_001E"],\n'
        '    geo_unit="tract:*",\n'
        '    geo_filter={"state": "42", "county": "101"},\n'
        ")\n"
        'income["B19013_001E"] = income["B19013_001E"].astype(float)\n'
        'income = income.loc[income["B19013_001E"] > 0]\n'
        'income = income.rename(columns={"B19013_001E": "median_income"})\n'
        "len(income)",
        [result("388")],
    ),
    "1.2": (
        "import pygris\n\n"
        'tracts = pygris.tracts(state="PA", county="101", year=2021)\n'
        "tracts = tracts.merge(\n"
        '    income, left_on=["STATEFP", "COUNTYFP", "TRACTCE"],\n'
        '    right_on=["state", "county", "tract"],\n'
        ")\n"
        "tracts.head()",
        [result("...", frame_html(["GEOID", "TRACTCE", "median_income", "geometry"], 5))],
    ),
    "1.3": (
        "import geopandas as gpd\n\n"
        'restaurants = pd.read_json("data/restaurants_philly.json.gz", orient="records", lines=True)\n'
        "restaurants = gpd.GeoDataFrame(\n"
        "    restaurants,\n"
        '    geometry=gpd.points_from_xy(restaurants["longitude"], restaurants["latitude"]),\n'
        '    crs="EPSG:4326",\n'
        ")\n"
        "len(restaurants)",
        [result("7350")],
    ),
    "1.4": (
        "restaurants = restaurants.to_crs(tracts.crs)\n"
        'joined = gpd.sjoin(restaurants, tracts[["GEOID", "geometry"]], predicate="within")\n'
        "joined.head()",
        [result("...", frame_html(["name", "stars", "GEOID", "geometry"], 5))],
    ),
    "1.5": (
        'restaurants_income = joined.merge(tracts[["GEOID", "median_income"]], on="GEOID")\n'
        "restaurants_income.head()",
        [result("...", frame_html(["name", "stars", "GEOID", "median_income"], 5))],
    ),
}
GOOD_PLOT = (
    "import seaborn as sns\n"
    "import matplotlib.pyplot as plt\n\n"
    "fig, ax = plt.subplots(figsize=(8, 5))\n"
    'sns.lineplot(data=restaurants_income, x="stars", y="median_income", ax=ax)\n'
    'ax.set_xlabel("Yelp stars")\n'
    'ax.set_ylabel("Median household income ($)")\n'
    'ax.set_title("Neighbourhood income by Yelp rating")'
)
GOOD_ANSWER = (
    "**Answer:** There is a weak positive relationship: restaurants with higher "
    "star ratings tend to sit in tracts with somewhat higher median household "
    "income, though the confidence intervals overlap for most ratings."
)


def _template() -> nbformat.NotebookNode:
    return nbformat.read(str(TEMPLATE), as_version=4)


def _fill(nb, cells: dict) -> int:
    count = 1
    for key, (source, outputs) in cells.items():
        cell = nb.cells[CELL[key]]
        cell["source"] = source
        cell["outputs"] = outputs
        cell["execution_count"] = count
        count += 1
    return count


def _with_plot(nb, source: str, outputs, answer: str | None) -> nbformat.NotebookNode:
    nb.cells.append(new_code_cell(source, outputs=outputs, execution_count=10))
    if answer:
        nb.cells.append(new_markdown_cell(answer))
    return nb


def good_notebook() -> nbformat.NotebookNode:
    nb = _template()
    _fill(nb, GOOD)
    return _with_plot(nb, GOOD_PLOT, [figure()], GOOD_ANSWER)


def partial_notebook() -> nbformat.NotebookNode:
    """Real mistakes, and the full Yelp dump read in place of the extract."""
    nb = _template()
    cells = dict(GOOD)
    cells["1.1"] = (
        cells["1.1"][0]
        .replace('income = income.loc[income["B19013_001E"] > 0]\n', "")
        .replace("len(income)", "income.head()"),
        [],
    )
    cells["1.2"] = ('tracts = pygris.tracts(state="PA", county="101", year=2021)', [])
    cells["1.3"] = (
        'business = pd.read_json("yelp_dataset/yelp_academic_dataset_business.json", lines=True)\n'
        'restaurants = business.loc[business["city"] == "Philadelphia"]\n'
        "restaurants = gpd.GeoDataFrame(\n"
        "    restaurants,\n"
        '    geometry=gpd.points_from_xy(restaurants["latitude"], restaurants["longitude"]),\n'
        '    crs="EPSG:4326",\n'
        ")",
        [],
    )
    _fill(nb, cells)
    return _with_plot(
        nb, 'sns.lineplot(data=restaurants_income, x="stars", y="median_income")',
        [figure()], None,
    )


def broken_notebook() -> nbformat.NotebookNode:
    """The student's run dies at 1.3 (no lines=True); nothing after it ran."""
    nb = _template()
    cells = {key: GOOD[key] for key in ("1.1", "1.2")}
    count = _fill(nb, cells)
    cell = nb.cells[CELL["1.3"]]
    cell["source"] = 'restaurants = pd.read_json("data/restaurants_philly.json.gz")'
    cell["outputs"] = [error("ValueError", "Trailing data")]
    cell["execution_count"] = count
    return nb


NOTEBOOKS = {
    "hw5_good_submission.ipynb": good_notebook,
    "hw5_partial_submission.ipynb": partial_notebook,
    "hw5_broken_submission.ipynb": broken_notebook,
}

LAYOUT = {
    "student_complete": "hw5_good_submission.ipynb",
    "student_mistakes": "hw5_partial_submission.ipynb",
    "student_crashed": "hw5_broken_submission.ipynb",
    "student_template": "__template__",
}


def build_submissions(dest: Path) -> Path:
    """Lay out the demo submissions under ``dest``; returns ``dest``."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for student, source in LAYOUT.items():
        folder = dest / student
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "assignment-5.ipynb"
        if source == "__template__":
            shutil.copy2(TEMPLATE, target)
        else:
            nbformat.write(NOTEBOOKS[source](), str(target))
    return dest


def main() -> None:
    for filename, build in NOTEBOOKS.items():
        nbformat.write(build(), str(HERE / filename))
        print(f"wrote examples/{filename}")
    build_submissions(SUBMISSIONS)
    print(f"wrote {len(LAYOUT)} submissions to examples/hw5_submissions/ "
          "(not executed: grading them needs no network and no data)")


if __name__ == "__main__":
    main()
