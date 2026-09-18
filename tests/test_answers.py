"""Reading answers out of a notebook's own saved outputs.

The point of ``grader/answers.py`` is that a submission stays gradeable when the
grading run cannot reproduce it — which on Assignment 3 is the common case, not
the exotic one, because five data files read from five student-chosen paths is
the part that breaks. These tests cover the two things that make or break that:
what counts as an answer, and which notebook wins when both have something to
say about the same cell.
"""

from __future__ import annotations

import nbformat
from nbformat.v4 import new_code_cell, new_notebook, new_output

from grader.answers import (
    SOURCE_EXECUTED,
    SOURCE_SUBMITTED,
    collect_answers,
    read_answers,
)


def notebook(path, cells):
    nb = new_notebook(cells=cells)
    nbformat.write(nb, str(path))
    return path


def result(source, text, html=None, images=0):
    data = {"text/plain": text}
    if html:
        data["text/html"] = html
    outputs = [new_output("execute_result", data=data, execution_count=1)]
    for _ in range(images):
        outputs.append(new_output("display_data", data={"image/png": "iVBORw0KGgo="}))
    cell = new_code_cell(source)
    cell.outputs = outputs
    return cell


def printed(source, text):
    cell = new_code_cell(source)
    cell.outputs = [new_output("stream", name="stdout", text=text)]
    return cell


def failed(source, ename="NameError", evalue="name 'phl' is not defined", images=0):
    cell = new_code_cell(source)
    cell.outputs = [
        new_output("error", ename=ename, evalue=evalue, traceback=["..."]),
    ]
    for _ in range(images):
        cell.outputs.insert(0, new_output("display_data", data={"image/png": "iVBORw0KGgo="}))
    return cell


# ---------------------------------------------------------------------------
# What counts as an answer
# ---------------------------------------------------------------------------

def test_a_returned_number_is_an_answer(tmp_path):
    path = notebook(tmp_path / "nb.ipynb", [result("len(phl)", "384")])
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.shows(384)
    assert answers.shows(385) is None


def test_printed_numbers_are_answers(tmp_path):
    path = notebook(
        tmp_path / "nb.ipynb",
        [printed("print(city_median, suburb_median)",
                 "Median NDVI, city:    0.2025\nMedian NDVI, suburbs: 0.3748\n")],
    )
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.shows(0.2025, abs_tol=0.001)
    assert answers.shows(0.3748, abs_tol=0.001)


def test_cell_values_of_a_table_are_not_answers(tmp_path):
    """A `head()` repr is full of numbers, and none of them is a result."""
    plain = "      lat        lng\n0  40.050526 -75.126076\n1  384.000000  34108.0"
    html = "<table><tr><th>lat</th><th>lng</th></tr><tr><td>40.05</td></tr></table>"
    path = notebook(tmp_path / "nb.ipynb", [result("violations.head()", plain, html)])
    answers = read_answers(path, SOURCE_SUBMITTED)
    # The numbers inside the table must not answer anything...
    assert answers.shows(384) is None
    assert answers.shows(34108) is None
    # ...but its column names are still evidence of what the frame holds.
    assert answers.frames_with_columns(["lat", "lng"])


def test_a_repr_footer_gives_the_row_count(tmp_path):
    path = notebook(
        tmp_path / "nb.ipynb",
        [result("evictions", "[5376 rows x 4 columns]",
                "<table><tr><th>GEOID</th></tr></table><p>5376 rows × 4 columns</p>")],
    )
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.shows_rows(5376)


def test_info_gives_rows_and_columns(tmp_path):
    text = (
        "<class 'geopandas.geodataframe.GeoDataFrame'>\n"
        "RangeIndex: 5376 entries, 0 to 5375\n"
        "Data columns (total 4 columns):\n"
        " #   Column     Non-Null Count  Dtype   \n"
        " 0   GEOID      5376 non-null   str     \n"
        " 1   geometry   5376 non-null   geometry\n"
    )
    path = notebook(tmp_path / "nb.ipynb", [printed("tidy.info()", text)])
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.shows_rows(5376)
    assert answers.frames_with_columns(["GEOID", "geometry"])


def test_describe_gives_the_median(tmp_path):
    text = (
        "count    2480.000000\nmean        0.196022\nstd         0.123054\n"
        "min        -0.038027\n25%         0.089642\n50%         0.179381\n"
        "75%         0.274003\nmax         0.593024\nName: NDVI, dtype: float64"
    )
    path = notebook(tmp_path / "nb.ipynb", [result("trees['NDVI'].describe()", text)])
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.describes("50%", 0.178, 0.01)
    assert answers.describes("count", 2480, 1)


def test_numbers_must_be_shown_together_to_count_together(tmp_path):
    """"10" is in every notebook; "10 and 32618" is a ten-band UTM 18N scene."""
    path = notebook(
        tmp_path / "nb.ipynb",
        [result("x", "10"), result("landsat.count, landsat.crs", "(10, 'EPSG:32618')")],
    )
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.shows_together([10, 32618])
    lonely = notebook(tmp_path / "other.ipynb", [result("x", "10")])
    assert read_answers(lonely, SOURCE_SUBMITTED).shows_together([10, 32618]) is None


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def test_a_holomap_repr_carries_its_dimension_and_frames(tmp_path):
    html = '"title":"year","options":["e-03","e-04","e-05","e-06"]'
    path = notebook(
        tmp_path / "nb.ipynb",
        [result("evictions.hvplot.polygons(groupby='year', dynamic=False)",
                ":HoloMap   [year]\n   :Polygons   [x,y]   (evictions)", html)],
    )
    chart = read_answers(path, SOURCE_SUBMITTED).charts()[0]
    assert chart.kind == "HoloMap"
    assert chart.is_widget and not chart.is_lazy
    assert chart.kdims == ["year"]
    assert chart.children == ["Polygons"]
    assert chart.frame_keys == ["e-03", "e-04", "e-05", "e-06"]


def test_a_missing_dynamic_false_shows_up_as_a_dynamicmap(tmp_path):
    path = notebook(
        tmp_path / "nb.ipynb",
        [result("evictions.hvplot.polygons(groupby='year')",
                ":DynamicMap   [year]\n   :Polygons   [x,y]   (evictions)")],
    )
    chart = read_answers(path, SOURCE_SUBMITTED).charts()[0]
    assert chart.is_lazy and not chart.is_widget


def test_a_layout_names_its_panels(tmp_path):
    text = (
        ":Layout\n"
        "   .Polygons.I  :Polygons   [x,y]   (evictions)\n"
        "   .Polygons.II :Polygons   [x,y]   (N)"
    )
    path = notebook(tmp_path / "nb.ipynb", [result("(left + right).cols(2)", text)])
    chart = read_answers(path, SOURCE_SUBMITTED).charts()[0]
    assert chart.is_layout
    assert chart.children == ["Polygons", "Polygons"]


def test_the_plotted_values_survive_into_the_file(tmp_path):
    """Bokeh writes the chart's numbers into the notebook as a base64 buffer."""
    import base64
    import gzip
    import struct

    values = [10647.0, 10491.0, 11182.0]
    raw = gzip.compress(struct.pack("<3d", *values))
    html = (
        '"array":{"type":"bytes","data":"' + base64.b64encode(raw).decode() + '"}'
        ',"shape":[3],"dtype":"float64"'
    )
    path = notebook(
        tmp_path / "nb.ipynb",
        [result("yearly.hvplot.line()", ":Curve   [year]   (evictions)", html)],
    )
    chart = read_answers(path, SOURCE_SUBMITTED).charts()[0]
    assert chart.values["count"] == 3
    assert chart.values["sum"] == sum(values)
    assert chart.values["max"] == 11182.0


# ---------------------------------------------------------------------------
# Merging the two notebooks
# ---------------------------------------------------------------------------

def test_a_traceback_never_displaces_a_real_answer(tmp_path):
    """The whole point: our failed re-run must not hide the student's result."""
    executed = notebook(tmp_path / "executed.ipynb", [
        failed("tracts = gpd.read_file('data/PA-tracts.geojson')",
               "DataSourceError", "No such file or directory"),
        failed("len(phl)"),
    ])
    submitted = notebook(tmp_path / "submitted.ipynb", [
        result("tracts = gpd.read_file('data/PA-tracts.geojson')", "3217"),
        result("len(phl)", "384"),
    ])
    answers = collect_answers(executed, submitted)
    assert answers.shows(384)
    assert answers.shows(3217)
    assert answers.error_cells == []


def test_an_empty_figure_from_a_failed_cell_never_displaces_the_real_one(tmp_path):
    """The inline backend flushes a figure even when the cell then raised."""
    executed = notebook(tmp_path / "executed.ipynb",
                        [failed("ax.hist(trees['NDVI'])", images=1)])
    submitted = notebook(tmp_path / "submitted.ipynb",
                         [result("ax.hist(trees['NDVI'])",
                                 "<Figure size 800x450 with 1 Axes>", images=1)])
    answers = collect_answers(executed, submitted)
    assert answers.figures == 1
    assert answers.error_cells == []


def test_our_own_run_wins_when_both_answered(tmp_path):
    executed = notebook(tmp_path / "executed.ipynb", [result("len(phl)", "384")])
    submitted = notebook(tmp_path / "submitted.ipynb", [result("len(phl)", "999")])
    answers = collect_answers(executed, submitted)
    assert answers.shows(384)
    assert answers.shows(999) is None
    assert answers.cells[0].origin == SOURCE_EXECUTED


def test_the_grader_probe_cells_are_not_the_students_answers(tmp_path):
    probe = new_code_cell("_musa_probe_main(globals(), config)")
    probe.metadata["musa_probe"] = True
    probe.outputs = [new_output("stream", name="stdout", text="384 34108")]
    path = notebook(tmp_path / "nb.ipynb", [result("len(phl)", "1"), probe])
    answers = read_answers(path, SOURCE_EXECUTED)
    assert len(answers.cells) == 1
    assert answers.shows(384) is None


def test_a_notebook_that_was_never_run_says_nothing(tmp_path):
    path = notebook(tmp_path / "nb.ipynb", [new_code_cell("len(phl)")])
    answers = read_answers(path, SOURCE_SUBMITTED)
    assert answers.cells_with_answers == 0
    assert answers.shows(384) is None


def test_a_missing_file_is_not_an_error(tmp_path):
    assert read_answers(tmp_path / "nope.ipynb", SOURCE_SUBMITTED).cells == []
    assert read_answers(None, SOURCE_SUBMITTED).cells == []
