"""Assignment 3 rubric checks.

The theme of these tests mirrors the theme of the assignment. Everyone is handed
the same zip, so the right answers are known — 384 Philadelphia tracts, 34,108
maintenance violations, a median NDVI of 0.2025 inside the city limits — and the
checks are expected to recognise them exactly and to name the near-misses rather
than just marking them wrong.

Two things get their own attention here because they are the parts most likely to
go quietly wrong:

* the hvplot items are graded on holoviews objects rather than source text, so
  the tests assert that a missing ``dynamic=False`` is caught by the object being
  a DynamicMap that holds no frames, and that a Layout of two widgets is not
  mistaken for two static maps side by side;
* an Eviction Lab frame carries 399 numeric columns across 3,217 tracts, so some
  column in it sums to almost any total by coincidence. A decoy frame appears in
  the payload below for exactly that reason, and the checks that look for a
  frame by what its numbers add up to must not pick it.
"""

from __future__ import annotations

import pytest

from assignments.base import GradingContext, get_grader
from grader.models import (
    STATUS_MANUAL_REVIEW,
    STATUS_NOT_FOUND,
    STATUS_PARTIAL,
    STATUS_PASS,
    ExecutionRecord,
)
from grader.notebook import NotebookAnalysis
from grader.rubric import load_rubric

from conftest import ROOT

YEAR_LABELS = [f"e-{x:02d}" for x in range(3, 17)]
VIOLATION_TYPES = [
    "INT-PLMBG MAINT FIXTURES-RES", "INT S-CEILING REPAIR/MAINT SAN",
    "PLUMBING SYSTEMS-GENERAL", "CO DETECTOR NEEDED", "INTERIOR SURFACES",
    "EXT S-ROOF REPAIR", "ELEC-RECEPTABLE DEFECTIVE-RES", "INT S-FLOOR REPAIR",
    "DRAINAGE-MAIN DRAIN REPAIR-RES", "DRAINAGE-DOWNSPOUT REPR/REPLC",
    "LIGHT FIXTURE DEFECTIVE-RES", "LICENSE-RES SFD/2FD", "ELECTRICAL -HAZARD",
    "VACANT PROPERTIES-GENERAL", "INT-PLMBG FIXTURES-RES",
]
PHILLY_BOUNDS = [-75.274275, 39.875131, -74.959341, 40.137402]


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def frame(name, rows, columns, **extras):
    profile = {
        "name": name,
        "rows": rows,
        "n_columns": extras.pop("n_columns", len(columns)),
        "columns": list(columns),
        "dtypes": {},
        "head": [],
        "index_names": [],
        "is_geodataframe": extras.pop("geo", False),
        "numeric_summary": {},
        "value_samples": {},
        "id_columns": [],
        "boolean_columns": [],
        "boolean_group_values": {},
        "nunique": {},
        "truncated": False,
    }
    profile.update(extras)
    return profile


def geoid_counts(n, prefix="42101", strays=0):
    counts = {prefix: n}
    if strays:
        counts["42003"] = strays
    return {"GEOID": {"length": 5, "counts": counts, "n_distinct": len(counts)}}


def plot(name, kind, **extras):
    entry = {
        "name": name,
        "source": "output",
        "type": kind,
        "module": "holoviews.core.spaces",
        "kdims": [],
        "vdims": [],
        "label": "",
        "is_container": kind in ("HoloMap", "DynamicMap", "Layout", "NdLayout"),
        "element_types": [],
    }
    entry.update(extras)
    return entry


def array(name, pixels, median, minimum=-0.2, maximum=0.67):
    return {
        "name": name,
        "shape": [999, 923],
        "ndim": 2,
        "dtype": "float64",
        "size": 922077,
        "masked": False,
        "finite_count": pixels,
        "nan_count": 922077 - pixels,
        "min": minimum,
        "max": maximum,
        "mean": median + 0.03,
        "median": median,
    }


# The raw Eviction Lab file: 399 numeric columns over 3,217 tracts, one of which
# happens to sum to 34,108 and another to 10,264. Nothing may match against it.
DECOY_WIDE_FRAME = frame(
    "tracts", 3217, ["GEOID", "pl", "n"] + [f"pr-{y:02d}" for y in range(0, 17)],
    n_columns=399, geo=True, crs_epsg=4326, geom_types=["MultiPolygon"],
    prefix_counts={"GEOID": {"length": 5,
                             "counts": {"42101": 384, "42003": 402, "42091": 211},
                             "n_distinct": 67}},
    numeric_summary={
        "pr-00": {"min": 0.0, "max": 99.0, "mean": 10.6, "median": 9.0,
                  "sum": 34108.0, "count": 3217},
        "pr-01": {"min": 0.0, "max": 99.0, "mean": 3.2, "median": 3.0,
                  "sum": 10264.0, "count": 3217},
    },
    nunique={"GEOID": 3217},
)


def correct_payload(**overrides):
    """A probe payload from a submission that did everything right."""
    payload = {
        "ok": True,
        "errors": [],
        "series": [],
        "collections": [],
        "scalars": [
            {"name": "city_median", "type": "float64", "value": 0.20246571},
            {"name": "suburb_median", "type": "float64", "value": 0.37484933},
        ],
        "functions": [],
        "modules": ["geopandas", "rasterio", "hvplot"],
        "figures": 2,
        "hidden_tests": [],
        "dataframes": [
            DECOY_WIDE_FRAME,
            frame("phl", 384, ["GEOID", "pl", "geometry"], n_columns=399, geo=True,
                  crs_epsg=4326, geom_types=["MultiPolygon"],
                  prefix_counts=geoid_counts(384), nunique={"GEOID": 384}),
            frame("evictions", 5376, ["GEOID", "geometry", "year", "evictions"],
                  geo=True, crs_epsg=4326, geom_types=["MultiPolygon"],
                  prefix_counts=geoid_counts(5376),
                  value_samples={"year": YEAR_LABELS},
                  nunique={"GEOID": 384, "year": 14},
                  numeric_summary={"evictions": {"min": 0.0, "max": 164.0, "mean": 27.8,
                                                 "median": 18.0, "sum": 149472.0,
                                                 "count": 5376}}),
            frame("evictions_2016", 384, ["GEOID", "geometry", "year", "evictions"],
                  geo=True, crs_epsg=4326, geom_types=["MultiPolygon"],
                  prefix_counts=geoid_counts(384),
                  value_samples={"year": ["e-16"]}, nunique={"GEOID": 384, "year": 1},
                  numeric_summary={"evictions": {"min": 0.0, "max": 146.0, "mean": 26.7,
                                                 "median": 17.0, "sum": 10264.0,
                                                 "count": 384}}),
            frame("violations", 434052, ["lat", "lng", "violationdescription", "geometry"],
                  geo=True, crs_epsg=4326, geom_types=["Point"],
                  total_bounds=list(PHILLY_BOUNDS), nunique={"violationdescription": 1342}),
            frame("maintenance", 34108, ["lat", "lng", "violationdescription", "geometry"],
                  geo=True, crs_epsg=4326, geom_types=["Point"],
                  total_bounds=list(PHILLY_BOUNDS),
                  value_samples={"violationdescription": VIOLATION_TYPES},
                  nunique={"violationdescription": 15}),
            frame("maintenance_3857", 34108,
                  ["lat", "lng", "violationdescription", "geometry"],
                  geo=True, crs_epsg=3857, crs_is_projected=True, geom_types=["Point"],
                  value_samples={"violationdescription": VIOLATION_TYPES},
                  nunique={"violationdescription": 15}),
            frame("joined", 34108,
                  ["lat", "lng", "violationdescription", "geometry", "index_right", "GEOID"],
                  geo=True, crs_epsg=4326, geom_types=["Point"],
                  prefix_counts=geoid_counts(34108),
                  value_samples={"violationdescription": VIOLATION_TYPES},
                  nunique={"violationdescription": 15, "GEOID": 369}),
            frame("N", 5535, ["violationdescription", "GEOID", "N"],
                  prefix_counts=geoid_counts(5535),
                  value_samples={"violationdescription": VIOLATION_TYPES},
                  nunique={"violationdescription": 15, "GEOID": 369},
                  numeric_summary={"N": {"min": 0, "max": 134, "mean": 6.16,
                                         "median": 3.0, "sum": 34108, "count": 5535}}),
            frame("violation_counts", 5535,
                  ["GEOID", "geometry", "violationdescription", "N"],
                  geo=True, crs_epsg=4326, geom_types=["MultiPolygon"],
                  prefix_counts=geoid_counts(5535),
                  value_samples={"violationdescription": VIOLATION_TYPES},
                  nunique={"violationdescription": 15, "GEOID": 369},
                  numeric_summary={"N": {"min": 0, "max": 134, "mean": 6.16,
                                         "median": 3.0, "sum": 34108, "count": 5535}}),
            frame("city_limits", 1, ["OBJECTID", "geometry"], geo=True, crs_epsg=32618,
                  crs_is_projected=True, geom_types=["Polygon"],
                  geometry_area=368606317.0),
            frame("trees", 2480, ["objectid", "fcode", "geometry", "NDVI"], geo=True,
                  crs_epsg=32618, crs_is_projected=True, geom_types=["Point"],
                  numeric_summary={"NDVI": {"min": -0.038, "max": 0.593, "mean": 0.196,
                                            "median": 0.1794, "sum": 486.0,
                                            "count": 2480}}),
        ],
        "arrays": [
            array("city_ndvi", 409576, 0.20246571),
            array("suburb_ndvi", 512501, 0.37484933),
        ],
        "geometries": [
            {"name": "city", "type": "Polygon", "geom_type": "Polygon",
             "area": 368606317.08, "n_geoms": 1, "is_valid": True},
            {"name": "suburbs", "type": "MultiPolygon", "geom_type": "MultiPolygon",
             "area": 462551418.69, "n_geoms": 4, "is_valid": True},
        ],
        "rasters": [
            {"name": "landsat", "type": "DatasetReader", "count": 10, "width": 923,
             "height": 999, "crs": "EPSG:32618", "path": "data/landsat8_philly.tif"},
        ],
        "plots": [
            plot("Out[5]", "Curve", kdims=["year"], vdims=["evictions"],
                 is_container=False, element_types=["Curve"], n_points=14,
                 values={"dimension": "evictions", "count": 14, "min": 9821.0,
                         "max": 11182.0, "sum": 149472.0}),
            plot("Out[6]", "HoloMap", kdims=["year"], n_frames=14,
                 keys=YEAR_LABELS, element_types=["Polygons"],
                 child_types=["Polygons"] * 14),
            plot("Out[14]", "HoloMap", kdims=["violationdescription"], n_frames=15,
                 keys=VIOLATION_TYPES, element_types=["Polygons"],
                 child_types=["Polygons"] * 15),
            plot("Out[15]", "Layout", n_frames=2, shape=[1, 2],
                 element_types=["Polygons"], child_types=["Polygons", "Polygons"]),
        ],
    }
    payload.update(overrides)
    return payload


HEXBIN_SOURCE = (
    "maintenance_3857 = maintenance.to_crs(epsg=3857)\n"
    "fig, ax = plt.subplots(figsize=(9, 9))\n"
    "ax.hexbin(maintenance_3857.geometry.x, maintenance_3857.geometry.y, "
    "gridsize=40, cmap='magma')\n"
    "tracts_3857.boundary.plot(ax=ax, color='white')\n"
    "ax.set_title('Violations')\n"
)
HISTOGRAM_SOURCE = (
    "fig, ax = plt.subplots(figsize=(8, 4.5))\n"
    "ax.hist(trees['NDVI'].dropna(), bins=40, color='#2b7a4b')\n"
    "ax.axvline(0, color='crimson', label='NDVI = 0')\n"
    "ax.set_xlabel('NDVI')\nax.set_ylabel('Trees')\nax.set_title('NDVI')\n"
    "ax.legend()\n"
)
TREE_MAP_SOURCE = (
    "fig, ax = plt.subplots(figsize=(8, 8))\n"
    "city_limits.boundary.plot(ax=ax, color='black')\n"
    "trees.plot(ax=ax, column='NDVI', cmap='YlGn', legend=True)\n"
    "ax.set_title('Street trees by NDVI')\n"
)
FULL_SOURCE = "\n".join(
    [
        "import geopandas as gpd",
        "tracts = gpd.read_file('data/PA-tracts.geojson')",
        "import rasterio.mask",
        "masked, transform = rasterio.mask.mask(landsat, [city], filled=False)",
        "city_median = np.nanmedian(city_ndvi)",
        "print(city_median)",
        "tree_ndvi = rasterstats.point_query(trees.geometry, ndvi, affine=transform)",
        "joined = gpd.sjoin(maintenance, phl, predicate='within')",
        HEXBIN_SOURCE,
        HISTOGRAM_SOURCE,
        TREE_MAP_SOURCE,
    ]
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def hw3_rubric():
    return load_rubric(ROOT / "rubrics" / "hw3.yaml")


@pytest.fixture
def hw3(hw3_rubric):
    return get_grader(hw3_rubric)


def analysis(**overrides) -> NotebookAnalysis:
    record = NotebookAnalysis(
        path="assignment-3.ipynb",
        n_code_cells=22,
        imports={"pandas", "geopandas", "numpy", "matplotlib", "hvplot",
                 "holoviews", "rasterio", "rasterstats"},
        read_calls=["read_file", "read_csv"],
        referenced_files=["data/PA-tracts.geojson", "data/li_violations.csv"],
        data_path_literals=["data/PA-tracts.geojson"],
        code_source=FULL_SOURCE,
        markdown_cells=[],
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


DEFAULT = object()


def context(hw3_rubric, probe=DEFAULT, execution=None, **analysis_overrides):
    return GradingContext(
        student_id="student_301",
        rubric=hw3_rubric,
        analysis=analysis(**analysis_overrides),
        execution=execution or ExecutionRecord(
            success=True, attempted=True, execution_time_seconds=120.0, mode="docker"
        ),
        probe=correct_payload() if probe is DEFAULT else probe,
    )


def run(hw3, ctx, rubric_id):
    item = hw3.rubric.item(rubric_id)
    return getattr(hw3, f"check_{rubric_id}")(ctx, item)


def charts_from(ctx, *records):
    """Pre-load the chart cache so no notebook has to exist on disk."""
    from grader.charts import ChartEvidence, SOURCE_EXECUTED

    ctx.cache["chart_evidence"] = ChartEvidence(
        charts=list(records), source=SOURCE_EXECUTED
    )


def matplotlib_chart(source, code_cell=1, rendered=True):
    from grader.charts import MATPLOTLIB, SOURCE_EXECUTED, ChartRecord, aesthetic_signals

    return ChartRecord(
        library=MATPLOTLIB,
        code_cell=code_cell,
        cell_index=code_cell,
        source=source,
        rendered=rendered,
        errored=False,
        aesthetics=aesthetic_signals(source),
        output_source=SOURCE_EXECUTED,
    )


# ---------------------------------------------------------------------------
# The rubric itself
# ---------------------------------------------------------------------------

def test_rubric_is_worth_one_hundred_points(hw3_rubric):
    assert hw3_rubric.total_points == 100
    assert hw3_rubric.declared_points == 100


def test_every_rubric_item_has_a_check(hw3, hw3_rubric):
    missing = [
        item.id for item in hw3_rubric.items
        if not hasattr(hw3, f"check_{item.id}")
    ]
    assert missing == []


def test_extra_credit_carries_no_points(hw3_rubric):
    item = hw3_rubric.item("common_violations_extra_credit")
    assert item.points == 0
    assert item.config["suggested_points"] > 0


def test_only_the_styling_item_is_qualitative(hw3_rubric):
    qualitative = [item.id for item in hw3_rubric.items if item.is_qualitative]
    assert qualitative == ["tree_plot_styling"]


# ---------------------------------------------------------------------------
# A correct submission
# ---------------------------------------------------------------------------

def test_correct_submission_scores_every_automatic_item(hw3, hw3_rubric):
    ctx = context(hw3_rubric)
    charts_from(
        ctx,
        matplotlib_chart(HEXBIN_SOURCE, 10),
        matplotlib_chart(HISTOGRAM_SOURCE, 23),
        matplotlib_chart(TREE_MAP_SOURCE, 24),
    )
    results = {result.rubric_id: result for result in hw3.grade(ctx)}

    automatic = [
        item for item in hw3_rubric.items
        if not item.is_qualitative and item.points > 0
        and item.id != "notebook_execution"
    ]
    for item in automatic:
        result = results[item.id]
        assert result.automatic_score == item.points, (item.id, result.feedback)
        assert result.status == STATUS_PASS
        # A matched expected value is a fact about the shipped data, so these
        # never arrive with the hedged confidence of a guessed candidate.
        assert result.confidence == 1.0


def test_styling_always_reaches_a_person(hw3, hw3_rubric):
    ctx = context(hw3_rubric)
    charts_from(ctx, matplotlib_chart(HISTOGRAM_SOURCE, 23),
                matplotlib_chart(TREE_MAP_SOURCE, 24))
    result = run(hw3, ctx, "tree_plot_styling")
    assert result.status == STATUS_MANUAL_REVIEW
    # Signals cannot prove a figure reads well, so it cannot reach full marks
    # without a human.
    ceiling = hw3_rubric.item("tree_plot_styling").config["provisional_ceiling_ratio"]
    assert result.automatic_score <= ceiling * result.points_possible + 0.25


# ---------------------------------------------------------------------------
# 1.1.2 — the Philadelphia subset
# ---------------------------------------------------------------------------

def test_subset_with_other_counties_is_named_as_impure(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("phl", 500, ["GEOID", "pl"], geo=True,
              prefix_counts=geoid_counts(384, strays=116), nunique={"GEOID": 500}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "philadelphia_tracts")
    assert result.status == STATUS_PARTIAL
    assert "outside Philadelphia County" in result.feedback


def test_subset_missing_tracts_is_a_different_mistake(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("phl", 350, ["GEOID", "pl"], geo=True,
              prefix_counts=geoid_counts(350), nunique={"GEOID": 350}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "philadelphia_tracts")
    assert result.status == STATUS_PARTIAL
    assert "350 tracts rather than 384" in result.feedback
    # Pure but incomplete is worth more than impure.
    assert result.automatic_score > result.points_possible * 0.5


def test_a_tidy_frame_alone_proves_the_subset(hw3, hw3_rubric):
    """Melting in one chain keeps no intermediate frame, and that is not a fault."""
    payload = correct_payload()
    payload["dataframes"] = [
        DECOY_WIDE_FRAME,
        frame("evictions", 5376, ["GEOID", "geometry", "year", "evictions"], geo=True,
              prefix_counts=geoid_counts(5376), nunique={"GEOID": 384, "year": 14}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "philadelphia_tracts")
    assert result.status == STATUS_PASS


# ---------------------------------------------------------------------------
# 1.1.3 — the melt
# ---------------------------------------------------------------------------

def test_melting_the_wrong_year_span_is_partial_credit(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("evictions", 6528, ["GEOID", "geometry", "year", "evictions"], geo=True,
              value_samples={"year": [f"e-{x:02d}" for x in range(0, 17)]},
              nunique={"year": 17},
              numeric_summary={"evictions": {"min": 0.0, "max": 164.0, "mean": 23.9,
                                             "median": 15.0, "sum": 155957.0,
                                             "count": 6528}}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "tidy_evictions")
    assert result.status == STATUS_PARTIAL
    assert "not exactly e-03 to e-16" in result.feedback


def test_dropping_geometry_from_id_vars_costs_credit(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("evictions", 5376, ["GEOID", "year", "evictions"],
              value_samples={"year": YEAR_LABELS}, nunique={"year": 14},
              numeric_summary={"evictions": {"min": 0.0, "max": 164.0, "mean": 27.8,
                                             "median": 18.0, "sum": 149472.0,
                                             "count": 5376}}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "tidy_evictions")
    assert result.status == STATUS_PARTIAL
    assert "geometry column was not kept" in result.feedback


# ---------------------------------------------------------------------------
# 1.1.4 / 1.1.5 / 1.2.7 — the hvplot items
# ---------------------------------------------------------------------------

def test_trend_plot_is_graded_on_the_numbers_plotted(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[5]", "Curve", kdims=["year"], vdims=["evictions"],
             is_container=False, element_types=["Curve"], n_points=14,
             values={"dimension": "evictions", "count": 14, "min": 700.0,
                     "max": 800.0, "sum": 10676.0}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "evictions_by_year_plot")
    assert result.status == STATUS_PARTIAL
    assert "10,676" in result.feedback


def test_missing_dynamic_false_is_caught_as_an_empty_dynamicmap(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[6]", "DynamicMap", kdims=["year"], n_frames=0, element_types=[]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "evictions_choropleth")
    assert result.status == STATUS_PARTIAL
    assert "dynamic=False" in result.feedback
    assert result.automatic_score > 0


def test_a_static_map_without_a_widget_is_half_the_item(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[6]", "Polygons", is_container=False, element_types=["Polygons"]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "evictions_choropleth")
    assert result.status == STATUS_PARTIAL
    assert "static charts" in result.feedback


def test_a_widget_on_the_wrong_dimension_is_named(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[6]", "HoloMap", kdims=["GEOID"], n_frames=384, keys=["42101000100"],
             element_types=["Polygons"], child_types=["Polygons"]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "evictions_choropleth")
    assert result.status == STATUS_PARTIAL
    assert "GEOID" in result.feedback


def test_violation_choropleth_needs_fifteen_frames(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[14]", "HoloMap", kdims=["violationdescription"], n_frames=4,
             keys=VIOLATION_TYPES[:4], element_types=["Polygons"],
             child_types=["Polygons"] * 4),
    ]
    result = run(hw3, context(hw3_rubric, payload), "violations_choropleth")
    assert result.status == STATUS_PARTIAL
    assert "4 frames rather than 15" in result.feedback


# ---------------------------------------------------------------------------
# 1.2.1 / 1.2.4 — the points and the join
# ---------------------------------------------------------------------------

def test_swapped_latitude_and_longitude_is_identified(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("violations", 434052, ["lat", "lng", "violationdescription", "geometry"],
              geo=True, crs_epsg=4326, geom_types=["Point"],
              total_bounds=[39.875131, -75.274275, 40.137402, -74.959341]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "violations_loading")
    assert result.status == STATUS_PARTIAL
    assert "wrong way round" in result.feedback
    assert result.automatic_score < result.points_possible * 0.5


def test_points_without_a_crs_lose_a_little(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("violations", 434052, ["lat", "lng", "violationdescription", "geometry"],
              geo=True, crs=None, crs_epsg=None, geom_types=["Point"],
              total_bounds=list(PHILLY_BOUNDS)),
    ]
    result = run(hw3, context(hw3_rubric, payload), "violations_loading")
    assert result.status == STATUS_PARTIAL
    assert "no CRS" in result.feedback
    assert result.automatic_score >= result.points_possible * 0.7


def test_a_lossy_join_points_at_the_crs(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("joined", 12, ["violationdescription", "geometry", "GEOID"], geo=True,
              geom_types=["Point"], prefix_counts=geoid_counts(12)),
    ]
    result = run(hw3, context(hw3_rubric, payload), "spatial_join")
    assert result.status == STATUS_PARTIAL
    assert "different CRSs" in result.feedback


def test_joining_before_trimming_is_the_right_step_in_the_wrong_order(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        frame("joined", 434052, ["violationdescription", "geometry", "GEOID"], geo=True,
              geom_types=["Point"], prefix_counts=geoid_counts(434052)),
    ]
    result = run(hw3, context(hw3_rubric, payload), "spatial_join")
    assert result.status == STATUS_PARTIAL
    assert "wrong order" in result.feedback
    assert result.automatic_score >= result.points_possible * 0.6


# ---------------------------------------------------------------------------
# 1.2.5 — the counts, and the 399-column decoy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rows", [4000, 5535])
def test_both_defensible_group_counts_score_full_marks(hw3, hw3_rubric, rows):
    """The unstack/stack fill is optional in the instructions, so both are right."""
    payload = correct_payload()
    payload["dataframes"] = [
        DECOY_WIDE_FRAME,
        frame("N", rows, ["violationdescription", "GEOID", "N"],
              prefix_counts=geoid_counts(rows),
              value_samples={"violationdescription": VIOLATION_TYPES},
              nunique={"violationdescription": 15, "GEOID": 369},
              numeric_summary={"N": {"min": 0, "max": 134, "mean": 6.2, "median": 3.0,
                                     "sum": 34108, "count": rows}}),
    ]
    result = run(hw3, context(hw3_rubric, payload), "violations_by_tract")
    assert result.status == STATUS_PASS
    assert result.automatic_score == result.points_possible


def test_the_wide_source_file_is_never_mistaken_for_the_counts(hw3, hw3_rubric):
    """One of 399 columns sums to 34,108 by chance; width is what rules it out."""
    payload = correct_payload()
    payload["dataframes"] = [DECOY_WIDE_FRAME]
    result = run(hw3, context(hw3_rubric, payload), "violations_by_tract")
    assert result.status == STATUS_NOT_FOUND
    assert result.automatic_score == 0


def test_the_wide_source_file_is_never_mistaken_for_a_single_year(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [DECOY_WIDE_FRAME]
    payload["plots"] = [
        plot("Out[15]", "Layout", n_frames=2, shape=[1, 2], element_types=["Polygons"],
             child_types=["Polygons", "Polygons"]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "side_by_side")
    assert result.status == STATUS_PARTIAL
    assert "single year of evictions" in result.feedback


# ---------------------------------------------------------------------------
# 1.3 — side by side
# ---------------------------------------------------------------------------

def test_a_layout_of_widgets_is_not_two_static_maps(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[15]", "Layout", n_frames=2, shape=[1, 2], element_types=["Polygons"],
             child_types=["HoloMap", "HoloMap"]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "side_by_side")
    assert result.status == STATUS_PARTIAL
    assert "widget" in result.feedback


def test_other_widgets_in_the_notebook_do_not_spoil_the_layout(hw3, hw3_rubric):
    """1.1.5 and 1.2.7 leave HoloMaps behind; only this layout's panels matter."""
    result = run(hw3, context(hw3_rubric), "side_by_side")
    assert result.status == STATUS_PASS


def test_two_maps_that_were_never_composed(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = [
        plot("Out[15]", "Polygons", is_container=False, element_types=["Polygons"]),
        plot("Out[16]", "Polygons", is_container=False, element_types=["Polygons"]),
    ]
    result = run(hw3, context(hw3_rubric, payload), "side_by_side")
    assert result.status == STATUS_PARTIAL
    assert "never composed" in result.feedback


# ---------------------------------------------------------------------------
# Part 2 — the raster
# ---------------------------------------------------------------------------

def test_a_closed_dataset_still_counts_as_loading_the_scene(hw3, hw3_rubric):
    """`with rasterio.open(...) as src:` leaves nothing in the namespace."""
    payload = correct_payload()
    payload["rasters"] = []
    payload["arrays"] = payload["arrays"] + [
        {"name": "bands", "shape": [10, 999, 923], "ndim": 3, "dtype": "uint16",
         "size": 9220770, "masked": True, "finite_count": 9220770, "nan_count": 0,
         "min": 4955.0, "max": 60723.0, "mean": 14805.0, "median": 12045.0},
    ]
    result = run(hw3, context(hw3_rubric, payload), "landsat_loading")
    assert result.status == STATUS_PASS


def test_suburbs_taken_as_the_whole_envelope(hw3, hw3_rubric):
    payload = correct_payload()
    payload["geometries"] = [
        {"name": "city", "geom_type": "Polygon", "area": 368606317.08, "n_geoms": 1},
        {"name": "suburbs", "geom_type": "Polygon", "area": 368606317.08 + 462551418.69,
         "n_geoms": 1},
    ]
    payload["dataframes"] = [f for f in payload["dataframes"] if f["name"] != "city_limits"]
    result = run(hw3, context(hw3_rubric, payload), "city_suburb_polygons")
    assert result.status == STATUS_PARTIAL
    assert "difference" in result.feedback


def test_polygons_left_in_degrees_are_named(hw3, hw3_rubric):
    payload = correct_payload()
    payload["geometries"] = [
        {"name": "city", "geom_type": "Polygon", "area": 0.0374, "n_geoms": 1},
        {"name": "suburbs", "geom_type": "MultiPolygon", "area": 0.047, "n_geoms": 4},
    ]
    payload["dataframes"] = [f for f in payload["dataframes"] if f["name"] != "city_limits"]
    result = run(hw3, context(hw3_rubric, payload), "city_suburb_polygons")
    assert result.status == STATUS_PARTIAL
    assert "degrees" in result.feedback


def test_a_polygon_held_only_as_a_one_row_frame_still_counts(hw3, hw3_rubric):
    payload = correct_payload()
    payload["geometries"] = []
    payload["dataframes"] = payload["dataframes"] + [
        frame("suburb_frame", 1, ["geometry"], geo=True, crs_epsg=32618,
              geom_types=["MultiPolygon"], geometry_area=462551418.69),
    ]
    result = run(hw3, context(hw3_rubric, payload), "city_suburb_polygons")
    assert result.status == STATUS_PASS


def test_off_by_one_band_indexing_is_named(hw3, hw3_rubric):
    """Bands 3 and 4 instead of 4 and 5 give -0.02, which is not a vegetation index."""
    payload = correct_payload()
    payload["arrays"] = [
        array("city_ndvi", 409576, -0.0200, minimum=-0.4, maximum=0.3),
        array("suburb_ndvi", 512501, -0.0150, minimum=-0.4, maximum=0.3),
    ]
    result = run(hw3, context(hw3_rubric, payload), "ndvi_masking")
    assert result.status == STATUS_PARTIAL
    assert "band 4 is red" in result.feedback


def test_median_instead_of_nanmedian_is_named(hw3, hw3_rubric):
    payload = correct_payload()
    payload["arrays"] = []
    payload["scalars"] = [
        {"name": "city_median", "type": "float64", "value": None},
        {"name": "suburb_median", "type": "float64", "value": None},
    ]
    source = FULL_SOURCE.replace("np.nanmedian", "np.median")
    ctx = context(hw3_rubric, payload, code_source=source)
    result = run(hw3, ctx, "ndvi_medians")
    assert result.status == STATUS_PARTIAL
    assert "nanmedian" in result.feedback


def test_medians_survive_never_being_assigned(hw3, hw3_rubric):
    """`print(np.nanmedian(city_ndvi))` computes the answer without binding it."""
    payload = correct_payload()
    payload["scalars"] = []
    result = run(hw3, context(hw3_rubric, payload), "ndvi_medians")
    assert result.status == STATUS_PASS


# ---------------------------------------------------------------------------
# 2.2 — the street trees
# ---------------------------------------------------------------------------

def test_tree_ndvi_held_as_a_bare_list_is_found(hw3, hw3_rubric):
    """rasterstats returns a list, and 2,480 values are past the sampling cap."""
    payload = correct_payload()
    payload["dataframes"] = [
        f for f in payload["dataframes"] if f["name"] != "trees"
    ] + [frame("trees", 2480, ["objectid", "geometry"], geo=True, crs_epsg=32618,
               geom_types=["Point"])]
    payload["collections"] = [
        {"name": "tree_ndvi", "type": "list", "length": 2480,
         "numeric_summary": {"count": 2480, "nan_count": 0, "min": -0.038,
                             "max": 0.593, "mean": 0.196, "median": 0.1794,
                             "sum": 486.0}},
    ]
    result = run(hw3, context(hw3_rubric, payload), "tree_ndvi")
    assert result.status == STATUS_PASS


def test_sampling_a_raw_band_instead_of_the_ndvi(hw3, hw3_rubric):
    payload = correct_payload()
    payload["dataframes"] = [
        f for f in payload["dataframes"] if f["name"] != "trees"
    ] + [frame("trees", 2480, ["objectid", "geometry", "band4"], geo=True,
               crs_epsg=32618, geom_types=["Point"],
               numeric_summary={"band4": {"min": 0.0, "max": 0.99, "mean": 0.51,
                                          "median": 0.52, "sum": 1290.0,
                                          "count": 2480}})]
    result = run(hw3, context(hw3_rubric, payload), "tree_ndvi")
    assert result.status == STATUS_PARTIAL
    assert "not the NDVI" in result.feedback


def test_a_histogram_without_the_zero_line_loses_part_of_the_item(hw3, hw3_rubric):
    ctx = context(hw3_rubric)
    charts_from(
        ctx,
        matplotlib_chart(HISTOGRAM_SOURCE.replace("ax.axvline(0, color='crimson', "
                                                  "label='NDVI = 0')\n", ""), 23),
        matplotlib_chart(TREE_MAP_SOURCE, 24),
    )
    result = run(hw3, ctx, "tree_plots")
    assert result.status == STATUS_PARTIAL
    assert 0 < result.automatic_score < result.points_possible


# ---------------------------------------------------------------------------
# Extra credit and failure modes
# ---------------------------------------------------------------------------

def test_extra_credit_is_flagged_and_never_scored_silently(hw3, hw3_rubric):
    payload = correct_payload()
    payload["plots"] = payload["plots"] + [
        plot("Out[20]", "HoloMap", kdims=["violationdescription"], n_frames=20,
             element_types=["Polygons"], child_types=["Polygons"] * 20),
    ]
    ctx = context(hw3_rubric, payload,
                  markdown_cells=["Three types with little overlap with evictions are "
                                  "fire alarm certification, new use permits and smoke "
                                  "detector requirements, which all track commercial "
                                  "permitting rather than rented housing conditions."])
    result = run(hw3, ctx, "common_violations_extra_credit")
    assert result.status == STATUS_MANUAL_REVIEW
    assert result.automatic_score == 0
    assert "Suggested bonus: 5 points" in result.feedback


def test_a_failed_notebook_is_never_an_automatic_zero(hw3, hw3_rubric):
    """An execution failure explains an absence; it does not make it a wrong answer."""
    execution = ExecutionRecord(
        success=False, attempted=True, error_cell=8,
        error_message="ValueError: attempt to get argmax of an empty sequence",
    )
    ctx = context(hw3_rubric, correct_payload(), execution=execution)
    charts_from(ctx)
    for result in hw3.grade(ctx):
        assert result.status != "fail", result.rubric_id


def test_missing_steps_report_the_failure_that_explains_them(hw3, hw3_rubric):
    execution = ExecutionRecord(
        success=False, attempted=True, error_cell=8,
        error_message="ValueError: attempt to get argmax of an empty sequence",
    )
    payload = correct_payload()
    payload["rasters"] = []
    payload["arrays"] = []
    ctx = context(hw3_rubric, payload, execution=execution)
    result = run(hw3, ctx, "landsat_loading")
    assert result.status == STATUS_NOT_FOUND
    assert "stopped at code cell 8" in result.feedback


def test_no_probe_at_all_goes_to_review_rather_than_zero(hw3, hw3_rubric):
    execution = ExecutionRecord(success=False, attempted=True, error_cell=1,
                                error_message="ModuleNotFoundError: geopandas")
    ctx = context(hw3_rubric, probe=None, execution=execution)
    result = run(hw3, ctx, "philadelphia_tracts")
    assert result.automatic_score == 0
    assert result.status in ("execution_error", STATUS_MANUAL_REVIEW)
    assert "manual review" in result.feedback.lower()


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------

def test_missing_data_files_are_named_before_the_run(tmp_path, hw3_rubric):
    """Four of the five files fails the class on the step that reads the fifth."""
    from grader.service import GraderSettings, GradingService

    supplied = []
    for name in ["PA-tracts.geojson", "li_violations.csv", "landsat8_philly.tif"]:
        path = tmp_path / name
        path.write_text("x")
        supplied.append(str(path))

    problems = GradingService(
        hw3_rubric, GraderSettings(shared_data_paths=supplied)
    ).preflight()
    joined = " ".join(problems)
    assert "City_Limits.geojson" in joined
    assert "ppr_tree_canopy_points_2015.geojson" in joined
    assert "PA-tracts.geojson" not in joined


def test_all_five_files_clear_the_preflight(tmp_path, hw3_rubric):
    from grader.service import GraderSettings, GradingService

    supplied = []
    for name in hw3_rubric.data["expected_files"]:
        path = tmp_path / name
        path.write_text("x")
        supplied.append(str(path))
    assert GradingService(
        hw3_rubric, GraderSettings(shared_data_paths=supplied)
    ).preflight() == []


def test_the_rubric_raises_the_timeout_but_never_lowers_it(hw3_rubric):
    """A slow assignment is assignment knowledge; a longer TA setting is a choice."""
    from grader.service import GraderSettings

    declared = int(hw3_rubric.settings["execution_timeout_seconds"])
    assert GraderSettings(timeout_seconds=600).execution_config(
        hw3_rubric
    ).timeout_seconds == declared
    assert GraderSettings(timeout_seconds=3600).execution_config(
        hw3_rubric
    ).timeout_seconds == 3600


def test_all_five_data_files_can_be_placed_at_once(tmp_path, hw3_rubric):
    """The default placement cap is a one-file cap; this assignment supplies five."""
    from grader.discovery import place_shared_data

    sources = []
    for name in hw3_rubric.data["expected_files"]:
        path = tmp_path / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        sources.append(str(path))

    workdir = tmp_path / "work"
    workdir.mkdir()
    report = place_shared_data(
        workdir, sources,
        referenced_paths=[f"data/{name}" for name in hw3_rubric.data["expected_files"]],
        fallback_dirs=hw3_rubric.data["fallback_locations"],
        max_placements=int(hw3_rubric.data["max_placements"]),
    )
    placed = {entry["source"] for entry in report["placed"]}
    assert placed == set(hw3_rubric.data["expected_files"])
    for name in hw3_rubric.data["expected_files"]:
        assert (workdir / "data" / name).exists()


# ---------------------------------------------------------------------------
# Grading from the notebook's own saved output
# ---------------------------------------------------------------------------
#
# The case these cover is the ordinary one for this assignment: the grading run
# could not reproduce the notebook — five data files, five student-chosen paths
# — so the answers have to come out of the file the student handed in.

import nbformat  # noqa: E402
from nbformat.v4 import new_code_cell, new_notebook, new_output  # noqa: E402


def _saved_notebook(tmp_path, entries) -> str:
    """Write a notebook whose cells carry the outputs a student's run produced."""
    cells = []
    for source, text in entries:
        cell = new_code_cell(source)
        if text is not None:
            cell.outputs = [
                new_output("execute_result", data={"text/plain": text},
                           execution_count=1)
            ]
        cells.append(cell)
    path = tmp_path / "submitted.ipynb"
    nbformat.write(new_notebook(cells=cells), str(path))
    return str(path)


def _no_run(hw3_rubric, path, **overrides):
    """A context where this grading run produced nothing at all."""
    execution = ExecutionRecord(
        success=False, attempted=True, error_cell=1,
        error_message="DataSourceError: data/PA-tracts.geojson: No such file",
        executed_notebook_path=None,
    )
    return context(hw3_rubric, probe=None, execution=execution, path=path, **overrides)


def test_the_saved_output_carries_an_item_the_run_could_not(hw3, hw3_rubric, tmp_path):
    path = _saved_notebook(tmp_path, [
        ("tracts = gpd.read_file('data/PA-tracts.geojson')", None),
        ("phl = tracts[tracts['pl'] == 'Philadelphia County, Pennsylvania']\nlen(phl)",
         "384"),
    ])
    ctx = _no_run(hw3_rubric, path)
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["philadelphia_tracts"]

    assert result.automatic_score == result.points_possible
    assert result.status == STATUS_PASS
    # Below the 1.0 of a result this grading run produced: a saved output is the
    # student's claim about their own run.
    assert result.confidence == hw3.SUBMITTED_CONFIDENCE
    assert result.evidence["graded_from"] == "the notebook's own saved output"
    assert result.evidence["executed_run_said"]["score"] == 0


def test_the_executed_run_still_wins_when_it_saw_more(hw3, hw3_rubric, tmp_path):
    path = _saved_notebook(tmp_path, [("len(phl)", "384")])
    ctx = context(hw3_rubric, path=path)
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["philadelphia_tracts"]
    assert result.confidence == 1.0
    assert result.evidence["agreement"] == "confirmed by the submitted notebook"


def test_saved_output_never_invents_credit_for_a_step_it_cannot_see(
    hw3, hw3_rubric, tmp_path
):
    path = _saved_notebook(tmp_path, [("len(phl)", "384")])
    ctx = _no_run(hw3_rubric, path, code_source="")
    charts_from(ctx)
    results = {r.rubric_id: r for r in hw3.grade(ctx)}
    # The tree NDVI is nowhere in this notebook, and nothing may invent it.
    assert results["tree_ndvi"].automatic_score == 0
    assert results["philadelphia_tracts"].automatic_score == 5


def test_a_clean_saved_run_carries_the_execution_item(hw3, hw3_rubric, tmp_path):
    """Their notebook ran; ours could not place the data. That is not their fault."""
    path = _saved_notebook(tmp_path, [
        ("len(phl)", "384"), ("len(maintenance)", "34108"), ("len(trees)", "2480"),
    ])
    ctx = _no_run(hw3_rubric, path)
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["notebook_execution"]
    assert result.automatic_score == result.points_possible
    assert "complete run" in result.feedback


def test_a_notebook_submitted_without_being_run_gets_nothing_for_execution(
    hw3, hw3_rubric, tmp_path
):
    path = _saved_notebook(tmp_path, [("len(phl)", None), ("len(trees)", None)])
    ctx = _no_run(hw3_rubric, path)
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["notebook_execution"]
    assert result.automatic_score == 0
    # Both readings agree on nothing, so the executed run keeps the feedback —
    # it names the actual failure — and the saved reading is recorded beside it.
    assert "no evidence it was ever run" in result.evidence["saved_output"]["note"]


def test_source_alone_is_partial_credit_not_full(hw3, hw3_rubric, tmp_path):
    """Writing `sjoin(...)` is not evidence that it returned the right thing."""
    path = _saved_notebook(tmp_path, [("joined = gpd.sjoin(maintenance, phl)", None)])
    ctx = _no_run(
        hw3_rubric, path,
        code_source="joined = gpd.sjoin(maintenance, phl, predicate='within')",
    )
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["spatial_join"]
    assert 0 < result.automatic_score < result.points_possible
    assert result.status == STATUS_PARTIAL


def test_a_displayed_row_count_upgrades_source_evidence_to_full(hw3, hw3_rubric, tmp_path):
    path = _saved_notebook(tmp_path, [
        ("joined = gpd.sjoin(maintenance, phl)\nlen(joined)", "34108"),
    ])
    ctx = _no_run(
        hw3_rubric, path,
        code_source="joined = gpd.sjoin(maintenance, phl, predicate='within')",
    )
    charts_from(ctx)
    result = {r.rubric_id: r for r in hw3.grade(ctx)}["spatial_join"]
    assert result.automatic_score == result.points_possible
