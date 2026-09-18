"""Build demo notebooks and a submissions folder that exercise the HW3 grader.

Four cases a TA meets: a submission that does everything including the extra
credit, one that misses in the ways students really miss on this assignment, one
that crashes partway through Part 1, and the untouched template.

Submissions contain notebooks only. The data is the zip that ships with the
assignment (``assignment_template/assignment3-data.zip``), and the grader can
place its five files into every submission before it runs — which is the whole
reason this assignment has an answer key at all.

The important detail is that these notebooks are **executed here against that zip
and saved with their outputs**. That is how the class submits: a student runs the
notebook with their data in the right place and hands in the file, outputs and
all. Those outputs are the primary evidence the HW3 grader reads, because
re-running five data files from whatever path each student used is the part that
breaks — so shipping demo notebooks with empty outputs would exercise the one
path that is not the normal one.

The notebooks below deliberately read from different paths (``data/x.geojson``
and a bare ``x.geojson``) to exercise the placement when data *is* supplied.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATE = ROOT / "assignment_template" / "assignment-3.ipynb"
DATA_ZIP = ROOT / "assignment_template" / "assignment3-data.zip"
SUBMISSIONS = HERE / "hw3_submissions"
# Set by --no-run, or automatically when the geospatial stack is not importable.
EXECUTE = True

VIOLATION_TYPES = (
    "violation_types = [\n"
    '    "INT-PLMBG MAINT FIXTURES-RES",\n'
    '    "INT S-CEILING REPAIR/MAINT SAN",\n'
    '    "PLUMBING SYSTEMS-GENERAL",\n'
    '    "CO DETECTOR NEEDED",\n'
    '    "INTERIOR SURFACES",\n'
    '    "EXT S-ROOF REPAIR",\n'
    '    "ELEC-RECEPTABLE DEFECTIVE-RES",\n'
    '    "INT S-FLOOR REPAIR",\n'
    '    "DRAINAGE-MAIN DRAIN REPAIR-RES",\n'
    '    "DRAINAGE-DOWNSPOUT REPR/REPLC",\n'
    '    "LIGHT FIXTURE DEFECTIVE-RES",\n'
    '    "LICENSE-RES SFD/2FD",\n'
    '    "ELECTRICAL -HAZARD",\n'
    '    "VACANT PROPERTIES-GENERAL",\n'
    '    "INT-PLMBG FIXTURES-RES",\n'
    "]"
)

SETUP = (
    "import pandas as pd\n"
    "import geopandas as gpd\n"
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "import hvplot.pandas\n"
    "import holoviews as hv\n"
    "\n"
    "pd.options.display.max_columns = 999\n"
    'np.seterr(invalid="ignore");'
)


# ---------------------------------------------------------------------------
# A submission that does everything the assignment asks
# ---------------------------------------------------------------------------

def good_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell("# Assignment 3"),
        new_code_cell(SETUP),
        new_markdown_cell("## 1.1.1 Read data using geopandas"),
        new_code_cell(
            'tracts = gpd.read_file("data/PA-tracts.geojson")\n'
            "tracts.head()"
        ),
        new_markdown_cell("## 1.1.2 Explore and trim the data"),
        new_code_cell(
            'phl = tracts[tracts["pl"] == "Philadelphia County, Pennsylvania"].copy()\n'
            "len(phl)"
        ),
        new_markdown_cell("## 1.1.3 Transform from wide to tidy format"),
        new_code_cell(
            'value_vars = [f"e-{x:02d}" for x in range(3, 17)]\n'
            "evictions = pd.melt(\n"
            '    phl, id_vars=["GEOID", "geometry"], value_vars=value_vars,\n'
            '    var_name="year", value_name="evictions",\n'
            ")\n"
            'evictions = gpd.GeoDataFrame(evictions, geometry="geometry", crs=phl.crs)\n'
            "evictions.head()"
        ),
        new_markdown_cell("## 1.1.4 Total evictions per year"),
        new_code_cell(
            'yearly = evictions.groupby("year")["evictions"].sum()\n'
            'yearly.hvplot.line(title="Total evictions in Philadelphia, 2003-2016",\n'
            '                   xlabel="Year", ylabel="Evictions", width=700, height=400)'
        ),
        new_markdown_cell("## 1.1.5 Evictions across Philadelphia"),
        new_code_cell(
            "evictions.hvplot.polygons(\n"
            '    c="evictions", groupby="year", dynamic=False,\n'
            '    width=500, height=500, cmap="viridis", hover_cols=["GEOID"],\n'
            ")"
        ),
        new_markdown_cell("## 1.2.1 Load the L+I violations"),
        new_code_cell(
            'violations = pd.read_csv("data/li_violations.csv")\n'
            "violations = gpd.GeoDataFrame(\n"
            "    violations,\n"
            "    geometry=gpd.points_from_xy(violations.lng, violations.lat),\n"
            '    crs="EPSG:4326",\n'
            ")\n"
            "violations.head()"
        ),
        new_markdown_cell("## 1.2.2 Trim to specific violation types"),
        new_code_cell(VIOLATION_TYPES),
        new_code_cell(
            "maintenance = violations[\n"
            '    violations["violationdescription"].isin(violation_types)\n'
            "].copy()\n"
            "len(maintenance)"
        ),
        new_markdown_cell("## 1.2.3 Hex bin map"),
        new_code_cell(
            "maintenance_3857 = maintenance.to_crs(epsg=3857)\n"
            "tracts_3857 = phl.to_crs(epsg=3857)\n"
            "\n"
            "fig, ax = plt.subplots(figsize=(9, 9))\n"
            "ax.hexbin(\n"
            "    maintenance_3857.geometry.x, maintenance_3857.geometry.y,\n"
            '    gridsize=40, cmap="magma", mincnt=1,\n'
            ")\n"
            'tracts_3857.boundary.plot(ax=ax, color="white", linewidth=0.4)\n'
            'ax.set_title("Property maintenance code violations, 2012-2016")\n'
            "ax.set_axis_off()\n"
            "plt.show()"
        ),
        new_markdown_cell("## 1.2.4 Spatially join the data sets"),
        new_code_cell(
            "joined = gpd.sjoin(\n"
            "    maintenance,\n"
            '    phl[["geometry", "GEOID"]].to_crs(maintenance.crs),\n'
            '    predicate="within", how="inner",\n'
            ")\n"
            "joined.head()"
        ),
        new_markdown_cell("## 1.2.5 Violations by type per census tract"),
        new_code_cell(
            'N = joined.groupby(["violationdescription", "GEOID"]).size()\n'
            'N = N.unstack(fill_value=0).stack().reset_index(name="N")\n'
            "N.head()"
        ),
        new_markdown_cell("## 1.2.6 Merge with the census tract geometries"),
        new_code_cell(
            'violation_counts = pd.merge(phl[["GEOID", "geometry"]], N, on="GEOID")\n'
            "violation_counts.head()"
        ),
        new_markdown_cell("## 1.2.7 Interactive choropleths per violation type"),
        new_code_cell(
            "violation_counts.hvplot.polygons(\n"
            '    c="N", groupby="violationdescription", dynamic=False,\n'
            '    width=500, height=500, cmap="viridis",\n'
            ")"
        ),
        new_markdown_cell("## 1.3 A side-by-side comparison"),
        new_code_cell(
            'evictions_2016 = evictions[evictions["year"] == "e-16"]\n'
            "roof = violation_counts[\n"
            '    violation_counts["violationdescription"] == "EXT S-ROOF REPAIR"\n'
            "]\n"
            "\n"
            "left = evictions_2016.hvplot.polygons(\n"
            '    c="evictions", width=450, height=450, cmap="viridis",\n'
            '    title="Evictions, 2016",\n'
            ")\n"
            "right = roof.hvplot.polygons(\n"
            '    c="N", width=450, height=450, cmap="viridis",\n'
            '    title="Roof repair violations",\n'
            ")\n"
            "(left + right).cols(2)"
        ),
        new_markdown_cell("## 1.4 Extra credit"),
        new_code_cell(
            'top_20 = violations["violationdescription"].value_counts().head(20).index\n'
            'top = violations[violations["violationdescription"].isin(top_20)]\n'
            "top_joined = gpd.sjoin(\n"
            '    top, phl[["geometry", "GEOID"]].to_crs(top.crs),\n'
            '    predicate="within", how="inner",\n'
            ")\n"
            'top_counts = top_joined.groupby(["violationdescription", "GEOID"]).size()\n'
            'top_counts = top_counts.reset_index(name="N")\n'
            "top_maps = pd.merge(\n"
            '    phl[["GEOID", "geometry"]], top_counts, on="GEOID"\n'
            ")\n"
            "top_maps.hvplot.polygons(\n"
            '    c="N", groupby="violationdescription", dynamic=False,\n'
            '    width=450, height=450, cmap="viridis",\n'
            ")"
        ),
        new_markdown_cell(
            "Three types with little spatial overlap with evictions: "
            "`ANNUAL CERT FIRE ALARM`, `PERM Z- NEW USE` and `SD-REQD EXIST GROUP R`. "
            "All three track commercial and new-construction permitting rather than "
            "the condition of occupied rented housing, so they cluster in Center City "
            "and along the commercial corridors instead of in the North and West "
            "Philadelphia tracts where evictions concentrate."
        ),
        new_markdown_cell("## 2.1.1 Load the Landsat data"),
        new_code_cell(
            "import rasterio\n"
            "\n"
            'landsat = rasterio.open("data/landsat8_philly.tif")\n'
            "landsat.count, landsat.crs"
        ),
        new_markdown_cell("## 2.1.2 Separating the city from the suburbs"),
        new_code_cell(
            'city_limits = gpd.read_file("data/City_Limits.geojson").to_crs(landsat.crs)\n'
            "city = city_limits.geometry.iloc[0]\n"
            "suburbs = city_limits.geometry.envelope.iloc[0].difference(city)\n"
            "city.area, suburbs.area"
        ),
        new_markdown_cell("## 2.1.3 Mask and calculate the NDVI"),
        new_code_cell(
            "import rasterio.mask\n"
            "\n"
            "def ndvi_for(geometry):\n"
            "    masked, transform = rasterio.mask.mask(\n"
            "        landsat, [geometry], crop=False, filled=False\n"
            "    )\n"
            "    red = masked[3].astype(float)\n"
            "    nir = masked[4].astype(float)\n"
            "    return np.ma.filled((nir - red) / (nir + red), np.nan)\n"
            "\n"
            "city_ndvi = ndvi_for(city)\n"
            "suburb_ndvi = ndvi_for(suburbs)\n"
            "city_ndvi.shape, suburb_ndvi.shape"
        ),
        new_markdown_cell("## 2.1.4 Median NDVI in the city and the suburbs"),
        new_code_cell(
            "city_median = np.nanmedian(city_ndvi)\n"
            "suburb_median = np.nanmedian(suburb_ndvi)\n"
            'print(f"Median NDVI, city:    {city_median:.4f}")\n'
            'print(f"Median NDVI, suburbs: {suburb_median:.4f}")'
        ),
        new_markdown_cell(
            "The suburbs are greener: a median NDVI of about 0.37 against about 0.20 "
            "inside the city limits."
        ),
        new_markdown_cell("## 2.2.1 Load the street tree data"),
        new_code_cell(
            "trees = gpd.read_file(\n"
            '    "data/ppr_tree_canopy_points_2015.geojson"\n'
            ").to_crs(landsat.crs)\n"
            "len(trees)"
        ),
        new_markdown_cell("## 2.2.2 NDVI at the street tree locations"),
        new_code_cell(
            "import rasterstats\n"
            "\n"
            "masked, transform = rasterio.mask.mask(\n"
            "    landsat, [city], crop=False, filled=False\n"
            ")\n"
            "red = masked[3].astype(float)\n"
            "nir = masked[4].astype(float)\n"
            "ndvi = np.ma.filled((nir - red) / (nir + red), np.nan)\n"
            "\n"
            "tree_ndvi = rasterstats.point_query(\n"
            "    trees.geometry, ndvi, affine=transform, nodata=np.nan,\n"
            '    interpolate="nearest",\n'
            ")\n"
            'trees["NDVI"] = tree_ndvi\n'
            'trees["NDVI"].describe()'
        ),
        new_markdown_cell("## 2.2.3 Plotting the results"),
        new_code_cell(
            "fig, ax = plt.subplots(figsize=(8, 4.5))\n"
            'ax.hist(trees["NDVI"].dropna(), bins=40, color="#2b7a4b", edgecolor="white")\n'
            'ax.axvline(0, color="crimson", linestyle="--", linewidth=2, label="NDVI = 0")\n'
            'ax.set_xlabel("NDVI")\n'
            'ax.set_ylabel("Number of street trees")\n'
            'ax.set_title("NDVI at Philadelphia street tree locations")\n'
            "ax.legend()\n"
            "plt.show()"
        ),
        new_code_cell(
            "fig, ax = plt.subplots(figsize=(8, 8))\n"
            'city_limits.boundary.plot(ax=ax, color="black", linewidth=1)\n'
            "trees.plot(\n"
            '    ax=ax, column="NDVI", cmap="YlGn", markersize=8, legend=True,\n'
            '    legend_kwds={"label": "NDVI", "shrink": 0.6},\n'
            ")\n"
            'ax.set_title("Street trees coloured by NDVI")\n'
            "ax.set_axis_off()\n"
            "plt.show()"
        ),
    ]
    return new_notebook(cells=cells)


# ---------------------------------------------------------------------------
# The near-misses students actually make
# ---------------------------------------------------------------------------

def partial_notebook() -> nbformat.NotebookNode:
    """Everything runs; six things are wrong, each in a way students really get wrong.

    * the melt covers e-00 to e-16 rather than e-03 to e-16,
    * `dynamic=False` is missing, so both choropleths are empty DynamicMaps,
    * the hex bin map has no tract outlines and is drawn in EPSG:4326,
    * the suburbs polygon is the envelope, never differenced,
    * the NDVI is computed from bands 3 and 4 instead of 4 and 5,
    * the two comparison maps are never composed into one layout.
    """
    cells = [
        new_markdown_cell("# Assignment 3"),
        new_code_cell(SETUP),
        new_code_cell(
            'tracts = gpd.read_file("data/PA-tracts.geojson")\n'
            'phl = tracts[tracts["pl"] == "Philadelphia County, Pennsylvania"].copy()\n'
            "len(phl)"
        ),
        new_code_cell(
            'value_vars = [f"e-{x:02d}" for x in range(0, 17)]\n'
            "evictions = pd.melt(\n"
            '    phl, id_vars=["GEOID", "geometry"], value_vars=value_vars,\n'
            '    var_name="year", value_name="evictions",\n'
            ")\n"
            'evictions = gpd.GeoDataFrame(evictions, geometry="geometry", crs=phl.crs)\n'
            "len(evictions)"
        ),
        new_code_cell(
            'yearly = evictions.groupby("year")["evictions"].sum()\n'
            'yearly.hvplot.bar(width=700, height=400)'
        ),
        new_code_cell(
            'evictions.hvplot.polygons(c="evictions", groupby="year", width=500, height=500)'
        ),
        new_code_cell(
            'violations = pd.read_csv("data/li_violations.csv")\n'
            "violations = gpd.GeoDataFrame(\n"
            "    violations,\n"
            "    geometry=gpd.points_from_xy(violations.lng, violations.lat),\n"
            '    crs="EPSG:4326",\n'
            ")\n"
            "len(violations)"
        ),
        new_code_cell(VIOLATION_TYPES),
        new_code_cell(
            "maintenance = violations[\n"
            '    violations["violationdescription"].isin(violation_types)\n'
            "].copy()\n"
            "len(maintenance)"
        ),
        new_code_cell(
            "fig, ax = plt.subplots(figsize=(8, 8))\n"
            "ax.hexbin(maintenance.geometry.x, maintenance.geometry.y, gridsize=40)\n"
            "plt.show()"
        ),
        new_code_cell(
            "joined = gpd.sjoin(\n"
            '    maintenance, phl[["geometry", "GEOID"]], predicate="within", how="inner"\n'
            ")\n"
            "len(joined)"
        ),
        new_code_cell(
            'N = joined.groupby(["violationdescription", "GEOID"]).size().reset_index(name="N")\n'
            "len(N)"
        ),
        new_code_cell(
            'violation_counts = pd.merge(phl[["GEOID", "geometry"]], N, on="GEOID")\n'
            "len(violation_counts)"
        ),
        new_code_cell(
            'violation_counts.hvplot.polygons(\n'
            '    c="N", groupby="violationdescription", width=500, height=500\n'
            ")"
        ),
        new_code_cell(
            'evictions_2016 = evictions[evictions["year"] == "e-16"]\n'
            "roof = violation_counts[\n"
            '    violation_counts["violationdescription"] == "EXT S-ROOF REPAIR"\n'
            "]\n"
            'evictions_2016.hvplot.polygons(c="evictions", width=450, height=450)'
        ),
        new_code_cell('roof.hvplot.polygons(c="N", width=450, height=450)'),
        new_code_cell(
            "import rasterio\n"
            "import rasterio.mask\n"
            "\n"
            'landsat = rasterio.open("data/landsat8_philly.tif")\n'
            'city_limits = gpd.read_file("data/City_Limits.geojson").to_crs(landsat.crs)\n'
            "city = city_limits.geometry.iloc[0]\n"
            "suburbs = city_limits.geometry.envelope.iloc[0]\n"
            "city.area, suburbs.area"
        ),
        new_code_cell(
            "def ndvi_for(geometry):\n"
            "    masked, transform = rasterio.mask.mask(\n"
            "        landsat, [geometry], crop=False, filled=False\n"
            "    )\n"
            "    red = masked[2].astype(float)\n"
            "    nir = masked[3].astype(float)\n"
            "    return np.ma.filled((nir - red) / (nir + red), np.nan)\n"
            "\n"
            "city_ndvi = ndvi_for(city)\n"
            "suburb_ndvi = ndvi_for(suburbs)\n"
            "city_median = np.nanmedian(city_ndvi)\n"
            "suburb_median = np.nanmedian(suburb_ndvi)\n"
            "print(city_median, suburb_median)"
        ),
        new_code_cell(
            "import rasterstats\n"
            "\n"
            "trees = gpd.read_file(\n"
            '    "data/ppr_tree_canopy_points_2015.geojson"\n'
            ").to_crs(landsat.crs)\n"
            "masked, transform = rasterio.mask.mask(\n"
            "    landsat, [city], crop=False, filled=False\n"
            ")\n"
            "red = masked[3].astype(float)\n"
            "nir = masked[4].astype(float)\n"
            "ndvi = np.ma.filled((nir - red) / (nir + red), np.nan)\n"
            'trees["NDVI"] = rasterstats.point_query(\n'
            "    trees.geometry, ndvi, affine=transform, nodata=np.nan\n"
            ")\n"
            'trees["NDVI"].median()'
        ),
        new_code_cell(
            "fig, ax = plt.subplots()\n"
            'ax.hist(trees["NDVI"].dropna(), bins=30)\n'
            "plt.show()"
        ),
        new_code_cell(
            "fig, ax = plt.subplots(figsize=(7, 7))\n"
            'trees.plot(ax=ax, column="NDVI", markersize=5)\n'
            "plt.show()"
        ),
    ]
    return new_notebook(cells=cells)


# ---------------------------------------------------------------------------
# A submission that crashes partway
# ---------------------------------------------------------------------------

def broken_notebook() -> nbformat.NotebookNode:
    """Latitude and longitude the wrong way round, and it goes downhill from there.

    The points land in the Indian Ocean, so the spatial join returns nothing and
    the groupby on the empty result raises. Everything before that still counts,
    which is the point of `allow_errors` — a failed notebook is never an
    automatic zero.
    """
    cells = [
        new_markdown_cell("# Assignment 3"),
        new_code_cell(SETUP),
        new_code_cell(
            'tracts = gpd.read_file("PA-tracts.geojson")\n'
            'phl = tracts[tracts["pl"] == "Philadelphia County, Pennsylvania"].copy()\n'
            "len(phl)"
        ),
        new_code_cell(
            'value_vars = [f"e-{x:02d}" for x in range(3, 17)]\n'
            "evictions = pd.melt(\n"
            '    phl, id_vars=["GEOID", "geometry"], value_vars=value_vars,\n'
            '    var_name="year", value_name="evictions",\n'
            ")\n"
            "len(evictions)"
        ),
        new_code_cell(
            'yearly = evictions.groupby("year")["evictions"].sum()\n'
            "yearly.hvplot.line()"
        ),
        new_code_cell(
            'violations = pd.read_csv("li_violations.csv")\n'
            "violations = gpd.GeoDataFrame(\n"
            "    violations,\n"
            "    geometry=gpd.points_from_xy(violations.lat, violations.lng),\n"
            '    crs="EPSG:4326",\n'
            ")\n"
            "len(violations)"
        ),
        new_code_cell(VIOLATION_TYPES),
        new_code_cell(
            "maintenance = violations[\n"
            '    violations["violationdescription"].isin(violation_types)\n'
            "].copy()\n"
            "len(maintenance)"
        ),
        new_code_cell(
            "joined = gpd.sjoin(\n"
            '    maintenance, phl[["geometry", "GEOID"]], predicate="within", how="inner"\n'
            ")\n"
            'N = joined.groupby(["violationdescription", "GEOID"]).size().reset_index(name="N")\n'
            'N["N"].idxmax()'
        ),
        new_code_cell(
            'violation_counts = pd.merge(phl[["GEOID", "geometry"]], N, on="GEOID")\n'
            'violation_counts.hvplot.polygons(c="N", groupby="violationdescription")'
        ),
    ]
    return new_notebook(cells=cells)


NOTEBOOKS = {
    "hw3_good_submission.ipynb": good_notebook,
    "hw3_partial_submission.ipynb": partial_notebook,
    "hw3_broken_submission.ipynb": broken_notebook,
}

LAYOUT: dict[str, list[tuple[str, str]]] = {
    "student_301": [("hw3_good_submission.ipynb", "assignment-3.ipynb")],
    "student_302": [("hw3_partial_submission.ipynb", "assignment3_final.ipynb")],
    "student_303": [("hw3_broken_submission.ipynb", "hw3.ipynb")],
    "student_304": [("__template__", "assignment-3.ipynb")],  # untouched template
}


def _unpack(workdir: Path) -> Path:
    """Put the assignment zip where a student would have put it."""
    target = workdir / "data"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DATA_ZIP) as archive:
        for entry in archive.namelist():
            name = Path(entry).name
            if not name or entry.startswith("__MACOSX") or name.startswith("."):
                continue
            with archive.open(entry) as handle, open(target / name, "wb") as out:
                shutil.copyfileobj(handle, out)
    # One notebook reads from the working directory rather than from `data/`.
    for path in target.iterdir():
        link = workdir / path.name
        if not link.exists():
            shutil.copy2(path, link)
    return workdir


def execute(nb: nbformat.NotebookNode, timeout: int = 1800) -> nbformat.NotebookNode:
    """Run a demo notebook next to the data, the way a student would.

    Errors are allowed through on purpose: one of these notebooks is meant to be
    handed in with a traceback still in it.
    """
    from nbclient import NotebookClient

    with tempfile.TemporaryDirectory() as workdir:
        _unpack(Path(workdir))
        NotebookClient(
            nb, timeout=timeout, kernel_name="python3", allow_errors=True,
            resources={"metadata": {"path": workdir}},
        ).execute()
    return nb


def _can_execute() -> bool:
    try:
        import geopandas, hvplot, rasterio, rasterstats  # noqa: F401
    except Exception:
        return False
    return DATA_ZIP.is_file()


def write_notebooks() -> None:
    """Build the demo notebooks, and run them so their outputs are saved."""
    run = EXECUTE and _can_execute()
    if not run:
        print(
            "note: writing notebooks without outputs — the geospatial stack "
            "(geopandas, rasterio, rasterstats, hvplot) is not importable here, "
            "or the data zip is missing. The HW3 grader reads saved outputs, so "
            "run this where those packages are installed to build the real demo.",
            file=sys.stderr,
        )
    for filename, builder in NOTEBOOKS.items():
        nb = builder()
        if run:
            nb = execute(nb)
        nbformat.write(nb, str(HERE / filename))


def build_submissions(dest: Path) -> Path:
    """Lay out the demo submissions under ``dest``."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for student, notebooks in LAYOUT.items():
        folder = dest / student
        folder.mkdir(parents=True, exist_ok=True)
        for source, target in notebooks:
            origin = TEMPLATE if source == "__template__" else HERE / source
            if not origin.exists():
                raise SystemExit(f"missing source notebook: {origin}")
            shutil.copy2(origin, folder / target)
    return dest


def _parse_args(argv: list[str]) -> None:
    global EXECUTE
    if "--no-run" in argv:
        EXECUTE = False


def main() -> None:
    _parse_args(sys.argv[1:])
    write_notebooks()
    for filename in NOTEBOOKS:
        print(f"wrote examples/{filename}")
    build_submissions(SUBMISSIONS)
    print(f"wrote {len(LAYOUT)} submissions to examples/hw3_submissions/")
    print(f"the data for these is {DATA_ZIP.relative_to(ROOT)}. Grading them "
          "needs no data at all — the answers are in the saved outputs — but "
          "supplying it lets the grader confirm them by re-running.")


if __name__ == "__main__":
    main()
