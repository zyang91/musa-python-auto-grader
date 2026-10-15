"""Build demo submissions that exercise the HW4 grader.

Four cases a TA meets: a submission that does everything, one that misses in the
ways students really miss on this assignment (latitude passed as x, an inner
merge with no fillna, a format_price that chokes on "$1,500", and Craigslist
results loaded from a CSV instead of scraped), one that crashes partway through
Part 1, and the untouched template.

Unlike the other demo builders, these notebooks are **not executed** — and that
is the point of the assignment's design. Running them would download a street
network from OpenStreetMap and scrape Craigslist. The saved outputs a student's
own run would leave behind (the scraping log, the results table, the rendered
plots, the Folium map, the Altair spec) are written in directly, in the shapes
Jupyter saves them in, because those outputs are what the HW4 grader reads.

    python examples/make_hw4_submissions.py
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_output

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATE = ROOT / "assignment_template" / "assignment-4.ipynb"
SUBMISSIONS = HERE / "hw4_submissions"

# A 1x1 PNG: enough for "a figure was rendered" without bloating the repo.
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)

# Template cell index -> the step it answers.
CELL = {
    "1.1": 3, "1.2": 5, "1.3": 7, "1.4": 9, "1.5": 11, "1.6": 13, "1.7": 15,
    "1.8": 17, "1.9": 19, "1.10": 21, "1.11": 23, "1.12": 25, "1.13": 27,
    "2.1": 32, "2.2": 34, "2.3": 36, "2.4": 38, "bedrooms": 40, "size": 41,
    "price": 42, "loop": 46, "results": 47, "2.8": 51,
}
# The template has no code cell for 2.7; students add one after its markdown.
HISTOGRAM_AT = 50


# ---------------------------------------------------------------------------
# Saved-output builders, in the shapes Jupyter writes
# ---------------------------------------------------------------------------

def stream(text: str):
    return new_output("stream", name="stdout", text=text)


def result(text: str, html: str | None = None, count: int = 1):
    data = {"text/plain": text}
    if html:
        data["text/html"] = html
    return new_output("execute_result", data=data, execution_count=count)


def figure(axes: int = 1):
    return new_output(
        "display_data",
        data={"image/png": PNG, "text/plain": f"<Figure size 640x480 with {axes} Axes>"},
    )


def error(ename: str, evalue: str):
    return new_output("error", ename=ename, evalue=evalue,
                      traceback=[f"{ename}: {evalue}"])


def frame_html(columns: list[str], rows: int, n_columns: int | None = None) -> str:
    header = "".join(f"<th>{c}</th>" for c in columns)
    return (
        '<div><table border="1" class="dataframe"><thead><tr><th></th>'
        f"{header}</tr></thead><tbody><tr><th>0</th>"
        + "".join("<td>1</td>" for _ in columns)
        + f"</tr></tbody></table><p>{rows} rows × {n_columns or len(columns)} columns</p></div>"
    )


def folium_html() -> str:
    return (
        '<div style="width:100%;"><div style="position:relative;width:100%;height:0;'
        'padding-bottom:60%;"><span style="color:#565656">Make this Notebook Trusted '
        'to load map: File -> Trust Notebook</span><iframe srcdoc="&lt;script '
        'src=&quot;https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js&quot;'
        '&gt;&lt;/script&gt;"></iframe></div></div>'
    )


LISTINGS = [
    {"price": 1500.0 + 25 * i, "size": 800.0 + 10 * i, "bedrooms": 1 + i % 3,
     "title": f"Sunny apartment #{i}"}
    for i in range(600)
]


def altair_output(interactive: bool = True, color: str = "bedrooms"):
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.20.1.json",
        "config": {"view": {"continuousWidth": 300, "continuousHeight": 300}},
        "data": {"name": "data-scraped"},
        "mark": {"type": "point"},
        "encoding": {
            "x": {"field": "price", "type": "quantitative"},
            "y": {"field": "size", "type": "quantitative"},
            "color": {"field": color, "type": "nominal"},
            "tooltip": [
                {"field": "price", "type": "quantitative"},
                {"field": "size", "type": "quantitative"},
                {"field": "bedrooms", "type": "quantitative"},
                {"field": "title", "type": "nominal"},
            ],
        },
        "datasets": {"data-scraped": LISTINGS},
    }
    if interactive:
        spec["params"] = [{"name": "param_1", "select": {"type": "interval",
                                                         "encodings": ["x", "y"]},
                           "bind": "scales"}]
    return new_output(
        "display_data",
        data={"application/vnd.vegalite.v5+json": spec, "text/plain": "alt.Chart(...)"},
    )


# ---------------------------------------------------------------------------
# The cells
# ---------------------------------------------------------------------------

GOOD_PART1 = {
    "1.1": (
        "import geopandas as gpd\n"
        "import pandas as pd\n"
        "import numpy as np\n"
        "import osmnx as ox\n\n"
        'url = "http://data.phl.opendata.arcgis.com/datasets/0960ea0f38f44146bb562f2b212075aa_0.geojson"\n'
        "districts = gpd.read_file(url)\n"
        'central = districts.loc[districts["DIST_NAME"] == "Central"]\n'
        "polygon = central.geometry.squeeze()\n"
        "type(polygon)",
        [result("shapely.geometry.polygon.Polygon")],
    ),
    "1.2": ('G = ox.graph_from_polygon(polygon, network_type="drive")', []),
    "1.3": (
        "edges = ox.graph_to_gdfs(G, nodes=False)\nedges.head()",
        [result("...", frame_html(["osmid", "name", "length", "geometry"], 5))],
    ),
    "1.4": (
        "files = [f\"./data/CRASH_PHILADELPHIA_{year}.csv\" for year in [2020, 2021, 2022]]\n"
        "crashes = pd.concat([pd.read_csv(f) for f in files])\n"
        "len(crashes)",
        [result("31211")],
    ),
    "1.5": (
        "crashes = gpd.GeoDataFrame(\n"
        "    crashes,\n"
        '    geometry=gpd.points_from_xy(crashes["DEC_LONG"], crashes["DEC_LAT"]),\n'
        '    crs="EPSG:4326",\n'
        ")",
        [],
    ),
    "1.6": (
        "boundary = edges.geometry.unary_union.convex_hull\n"
        "crashes_cc = crashes.loc[crashes.within(boundary)]\n"
        "len(crashes_cc)",
        [result("3748")],
    ),
    "1.7": (
        "G_proj = ox.project_graph(G, to_crs=2272)\n"
        "crashes_cc = crashes_cc.to_crs(epsg=2272)",
        [],
    ),
    "1.8": (
        "nearest = ox.distance.nearest_edges(\n"
        "    G_proj, crashes_cc.geometry.x, crashes_cc.geometry.y\n"
        ")",
        [],
    ),
    "1.9": (
        'nearest_df = pd.DataFrame(nearest, columns=["u", "v", "key"])\n'
        'crash_counts = nearest_df.groupby(["u", "v"]).size().reset_index(name="crash_count")\n'
        "crash_counts.head()",
        [result("...", frame_html(["u", "v", "crash_count"], 1104))],
    ),
    "1.10": (
        'merged = edges.merge(crash_counts, on=["u", "v"], how="left")\n'
        'merged["crash_count"] = merged["crash_count"].fillna(0)',
        [],
    ),
    "1.11": (
        'merged = merged.loc[merged["crash_count"] > 0].copy()\n'
        'merged["per_length"] = merged["crash_count"] / merged["length"]\n'
        'merged["log_index"] = np.log10(merged["per_length"])\n'
        'low, high = merged["log_index"].min(), merged["log_index"].max()\n'
        'merged["crash_index"] = (merged["log_index"] - low) / (high - low)',
        [],
    ),
    "1.12": (
        "import matplotlib.pyplot as plt\n\n"
        "fig, ax = plt.subplots()\n"
        'ax.hist(merged["crash_index"], bins=30)\n'
        'ax.set_xlabel("Crash index")\n'
        'ax.set_ylabel("Streets")',
        [figure()],
    ),
    "1.13": (
        'merged.explore(column="crash_index", cmap="viridis", tiles="CartoDB dark_matter")',
        [result("<folium.folium.Map at 0x10f>", folium_html())],
    ),
}

GOOD_PART2 = {
    "2.1": (
        "from selenium import webdriver\n\n"
        "driver = webdriver.Chrome()\n"
        'url = "https://philadelphia.craigslist.org/search/apa?min_price=1&min_bedrooms=1&minSqft=1#search=1~gallery~0~0"\n'
        "driver.get(url)",
        [],
    ),
    "2.2": (
        "from bs4 import BeautifulSoup\n\n"
        'soup = BeautifulSoup(driver.page_source, "html.parser")',
        [],
    ),
    "2.3": (
        'apts = soup.select("li.cl-search-result")\nlen(apts)',
        [result("120")],
    ),
    "2.4": (
        "first = apts[0]\n"
        "print(first.prettify()[:400])\n"
        'print(first.select_one(".priceinfo").text)\n'
        'print(first.select_one(".meta .housing").text)\n'
        'print(first.select_one(".meta .sqft").text)\n'
        'print(first.select_one(".posting-title .label").text)',
        [stream('<li class="cl-search-result">...</li>\n$1,650\n2br\n900ft2\n'
                "Bright 2BR near Rittenhouse\n")],
    ),
    "bedrooms": (
        "def format_bedrooms(bedrooms_string):\n"
        '    return int(bedrooms_string.replace("br", "").strip())',
        [],
    ),
    "size": (
        "def format_size(size_string):\n"
        '    return float(size_string.replace("ft2", "").strip())',
        [],
    ),
    "price": (
        "def format_price(price_string):\n"
        '    return float(price_string.strip().replace("$", "").replace(",", ""))',
        [],
    ),
}

HISTOGRAMS = (
        "fig, axs = plt.subplots(ncols=2, figsize=(10, 4))\n"
        'axs[0].hist(results["price"], bins=40)\n'
        'axs[0].set_xlabel("Price ($)")\n'
        'axs[0].set_ylabel("Listings")\n'
        'axs[0].set_title("Apartment prices")\n'
        'axs[1].hist(results["price"] / results["size"], bins=40)\n'
        'axs[1].set_xlabel("Price per sq. ft.")\n'
        'axs[1].set_ylabel("Listings")\n'
        'axs[1].set_title("Price per square foot")'
)

GOOD_ALTAIR = {
    "2.8": (
        "import altair as alt\n\n"
        "alt.Chart(results).mark_point().encode(\n"
        '    x="price:Q", y="size:Q", color="bedrooms:N",\n'
        '    tooltip=["price", "size", "bedrooms", "title"],\n'
        ").interactive()",
        [altair_output()],
    ),
}

# The blanks the template leaves in the scraping loop, filled in.
FILLED_LOOP_LINES = {
    "soup =": '    soup = BeautifulSoup(driver.page_source, "html.parser")',
    "apts =": '    apts = soup.select("li.cl-search-result")',
    "bedrooms =": '        bedrooms = apt.select_one(".meta .housing").text',
    "size =": '        size = apt.select_one(".meta .sqft").text',
    "title =": '        title = apt.select_one(".posting-title .label").text',
    "price =": '        price = apt.select_one(".priceinfo").text',
}
LOOP_LOG = "".join(
    f"Processing page {page}...\nNumber of apartments =  120\n"
    "sleeping for 10 seconds between calls\n"
    for page in range(1, 6)
)


def _template() -> nbformat.NotebookNode:
    return nbformat.read(str(TEMPLATE), as_version=4)


def _set(nb, key: str, source: str, outputs: list, count: int) -> None:
    cell = nb.cells[CELL[key]]
    cell["source"] = source
    cell["outputs"] = outputs
    cell["execution_count"] = count


def _fill(nb, cells: dict, start: int = 1) -> int:
    count = start
    for key, (source, outputs) in cells.items():
        _set(nb, key, source, outputs, count)
        count += 1
    return count


def _filled_loop(nb) -> str:
    lines = "".join(nb.cells[CELL["loop"]]["source"]).splitlines()
    return "\n".join(FILLED_LOOP_LINES.get(line.strip(), line) for line in lines)


def _good_base() -> nbformat.NotebookNode:
    nb = _template()
    count = _fill(nb, GOOD_PART1)
    count = _fill(nb, GOOD_PART2, count)
    _set(nb, "loop", _filled_loop(nb), [stream(LOOP_LOG)], count + 1)
    _set(nb, "results", "results",
         [result("...", frame_html(["price", "size", "bedrooms", "title"], 600))], count + 2)
    _fill(nb, GOOD_ALTAIR, count + 4)
    nb.cells[CELL["loop"] - 1]["execution_count"] = count  # `from time import sleep`
    return nb


def _with_histograms(nb, source: str = HISTOGRAMS, outputs=None) -> nbformat.NotebookNode:
    """Add the 2.7 cell the student writes; call last, it shifts the cells after it."""
    nb.cells.insert(HISTOGRAM_AT, new_code_cell(
        source, outputs=[figure(axes=2)] if outputs is None else outputs,
        execution_count=90,
    ))
    return nb


def good_notebook() -> nbformat.NotebookNode:
    return _with_histograms(_good_base())


def partial_notebook() -> nbformat.NotebookNode:
    """Real mistakes: swapped coordinates, an inner merge, results from a CSV."""
    nb = _good_base()
    part1 = copy.deepcopy(GOOD_PART1)
    part1["1.5"] = (
        part1["1.5"][0].replace(
            'points_from_xy(crashes["DEC_LONG"], crashes["DEC_LAT"])',
            'points_from_xy(crashes["DEC_LAT"], crashes["DEC_LONG"])',
        ),
        [],
    )
    part1["1.6"] = (part1["1.6"][0], [result("0")])
    part1["1.10"] = ('merged = edges.merge(crash_counts, on=["u", "v"])', [])
    _fill(nb, part1)
    _set(nb, "price", "def format_price(price_string):\n"
         '    return float(price_string.replace("$", ""))', [], 40)
    # The scraping loop left as the template had it, and the results read back
    # from a file the student saved on another day.
    nb.cells[CELL["loop"]] = copy.deepcopy(_template().cells[CELL["loop"]])
    _set(nb, "results", 'results = pd.read_csv("craigslist_results.csv")\nresults',
         [result("...", frame_html(["price", "size", "bedrooms", "title"], 600))], 50)
    _set(nb, "2.8", GOOD_ALTAIR["2.8"][0].replace(".interactive()", ""),
         [altair_output(interactive=False)], 60)
    # One histogram, no title.
    return _with_histograms(
        nb, 'plt.hist(results["price"])\nplt.xlabel("Price")\nplt.ylabel("Count")',
        [figure()],
    )


def broken_notebook() -> nbformat.NotebookNode:
    """Part 1 dies at 1.6 in the student's own run; nothing after it ran."""
    nb = _template()
    part1 = {key: GOOD_PART1[key] for key in ("1.1", "1.2", "1.3", "1.4", "1.5")}
    count = _fill(nb, part1)
    _set(nb, "1.6",
         "crashes_cc = crashes.loc[crashes.within(boundary)]\nlen(crashes_cc)",
         [error("NameError", "name 'boundary' is not defined")], count)
    return nb


NOTEBOOKS = {
    "hw4_good_submission.ipynb": good_notebook,
    "hw4_partial_submission.ipynb": partial_notebook,
    "hw4_broken_submission.ipynb": broken_notebook,
}

LAYOUT = {
    "student_complete": "hw4_good_submission.ipynb",
    "student_csv_results": "hw4_partial_submission.ipynb",
    "student_crashed": "hw4_broken_submission.ipynb",
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
        target = folder / "assignment-4.ipynb"
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
    print(f"wrote {len(LAYOUT)} submissions to examples/hw4_submissions/ "
          "(not executed: grading them needs no network and no data)")


if __name__ == "__main__":
    main()
