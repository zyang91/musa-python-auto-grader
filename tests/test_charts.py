"""Chart evidence extraction (grader/charts.py).

The point of these tests is that a chart's *specification* is a fact and its
appearance is not. Everything here checks the fact half: which library drew a
cell, whether it rendered, and what the compiled Vega-Lite spec says the chart
does — including the two distinctions students trip over, a pan/zoom
`.interactive()` that is not a brush and a data filter that is not a cross-filter.
"""

from __future__ import annotations

import json

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from grader import charts


# ---------------------------------------------------------------------------
# Library attribution
# ---------------------------------------------------------------------------

def test_seaborn_shadows_matplotlib_in_the_same_cell():
    """`sns.boxplot(...)` plus `plt.title(...)` is one seaborn chart, not two."""
    found = charts.libraries_in_source(
        'sns.boxplot(data=df, x="a", y="b")\nplt.title("t")\nplt.show()'
    )
    assert found == [charts.SEABORN]


def test_matplotlib_is_recognised_through_axes_and_pandas():
    assert charts.libraries_in_source("ax.scatter(x, y)") == [charts.MATPLOTLIB]
    assert charts.libraries_in_source('df.plot(kind="bar")') == [charts.MATPLOTLIB]
    assert charts.libraries_in_source("axes[1].hist(v)") == [charts.MATPLOTLIB]


def test_seaborn_styling_alone_is_not_a_chart():
    assert charts.libraries_in_source('sns.set_theme(style="whitegrid")') == []
    assert charts.libraries_in_source("sns.color_palette('crest')") == []


def test_altair_is_recognised_and_does_not_shadow_others():
    assert charts.libraries_in_source('alt.Chart(df).mark_bar()') == [charts.ALTAIR]
    assert charts.libraries_in_source("plt.subplots()") == []  # a canvas, not a chart


# ---------------------------------------------------------------------------
# Spec analysis
# ---------------------------------------------------------------------------

BRUSH_SPEC = {
    "mark": {"type": "bar"},
    "encoding": {"x": {"field": "cat", "type": "nominal"},
                 "y": {"aggregate": "mean", "field": "y", "type": "quantitative"}},
    "params": [{"name": "brush", "select": {"type": "interval", "encodings": ["x"]}}],
}

INTERACTIVE_SPEC = {
    "mark": {"type": "point"},
    "encoding": {"x": {"field": "x", "type": "quantitative"}},
    "params": [{"name": "p", "select": {"type": "interval", "encodings": ["x", "y"]},
                "bind": "scales"}],
}

DASHBOARD_SPEC = {
    "hconcat": [
        {"mark": {"type": "point"},
         "encoding": {"x": {"field": "x", "type": "quantitative"}},
         "name": "view_0"},
        {"mark": {"type": "bar"},
         "encoding": {"y": {"aggregate": "count", "type": "quantitative"}},
         "transform": [{"filter": {"param": "sel"}}]},
    ],
    "params": [{"name": "sel", "select": {"type": "interval"}, "views": ["view_0"]}],
}


def test_encoding_aggregate_counts_as_a_transformation():
    facts = charts.analyze_spec(BRUSH_SPEC)
    assert facts.has_transformation
    assert facts.encoding_transforms == ["y.aggregate=mean"]


def test_transform_block_operations_are_read():
    facts = charts.analyze_spec(
        {"mark": "bar", "transform": [{"aggregate": [{"op": "mean", "field": "y", "as": "m"}],
                                       "groupby": ["c"]}]}
    )
    assert facts.transform_ops == ["aggregate"]
    assert facts.has_transformation


def test_a_bare_filter_is_not_a_transformation():
    """"A transformation (mean, count, binning, etc)" — a subset is not one."""
    facts = charts.analyze_spec(
        {"mark": "bar", "transform": [{"filter": "datum.year > 2020"}]}
    )
    assert facts.has_transformation is False


def test_interval_selection_is_a_brush():
    facts = charts.analyze_spec(BRUSH_SPEC)
    assert facts.has_brush
    assert facts.brushes[0]["encodings"] == ["x"]


def test_interactive_pan_zoom_is_not_a_brush():
    """`.interactive()` compiles to an interval selection bound to the scales."""
    facts = charts.analyze_spec(INTERACTIVE_SPEC)
    assert facts.selections and facts.selections[0]["type"] == "interval"
    assert facts.has_brush is False


def test_point_selection_is_not_a_brush():
    facts = charts.analyze_spec(
        {"mark": "point", "params": [{"name": "p", "select": {"type": "point"}}]}
    )
    assert facts.has_brush is False
    assert facts.selections[0]["type"] == "point"


def test_cross_filter_needs_a_selection_and_more_than_one_view():
    facts = charts.analyze_spec(DASHBOARD_SPEC)
    assert facts.is_multi_view
    assert facts.cross_filter_params == ["sel"]
    assert facts.has_cross_filter


def test_a_filter_on_an_undeclared_param_is_not_a_cross_filter():
    spec = json.loads(json.dumps(DASHBOARD_SPEC))
    spec["params"] = []
    assert charts.analyze_spec(spec).has_cross_filter is False


def test_vega_lite_4_selection_block_is_understood():
    """Altair 4 emits `selection`, not `params`; students on old versions exist."""
    facts = charts.analyze_spec(
        {"mark": "point", "selection": {"selector001": {"type": "interval"}},
         "transform": [{"filter": {"selection": "selector001"}}],
         "hconcat": []}
    )
    assert facts.has_brush
    assert facts.filter_params == ["selector001"]


# ---------------------------------------------------------------------------
# Output extraction
# ---------------------------------------------------------------------------

def test_spec_is_read_from_a_vegalite_mime_bundle():
    output = {"output_type": "execute_result",
              "data": {"application/vnd.vegalite.v5+json": BRUSH_SPEC}}
    assert charts.extract_specs(output) == [BRUSH_SPEC]


def test_spec_is_read_from_altairs_html_renderer():
    """Altair 6 renders to HTML; the spec is the first argument of the embed."""
    html = (
        "<div id='x'></div><script>(function(spec, embedOpt){})("
        + json.dumps(BRUSH_SPEC)
        + ', {"mode": "vega-lite"});</script>'
    )
    output = {"output_type": "execute_result", "data": {"text/html": html}}
    assert charts.extract_specs(output) == [BRUSH_SPEC]


def test_inline_data_is_stripped_from_stored_specs():
    """A student's whole dataset must not land in every results file."""
    spec = {"mark": "bar", "data": {"values": [{"a": i} for i in range(5000)]},
            "datasets": {"data-1": [{"a": 1}, {"a": 2}]}}
    stripped = charts.strip_spec_data(spec)
    assert stripped["data"]["values"] == "<5000 rows>"
    assert stripped["datasets"]["data-1"] == "<2 rows>"


# ---------------------------------------------------------------------------
# Notebook walk
# ---------------------------------------------------------------------------

def _notebook(cells):
    return new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    })


def _altair_output(spec):
    return nbformat.from_dict(
        {"output_type": "execute_result", "execution_count": 1, "metadata": {},
         "data": {"application/vnd.vegalite.v5+json": spec}}
    )


def _image_output():
    return nbformat.from_dict(
        {"output_type": "display_data", "metadata": {},
         "data": {"image/png": "iVBORw0KGgo=", "text/plain": "<Figure>"}}
    )


def test_charts_are_found_with_their_discussion_and_preamble(tmp_path):
    chart_cell = new_code_cell('alt.Chart(df).mark_bar().encode(x="a", y="count()")')
    chart_cell.outputs = [_altair_output(BRUSH_SPEC)]
    nb = _notebook([
        new_markdown_cell("## Requests by ZIP\n\nI chose a bar chart to compare counts."),
        chart_cell,
        new_markdown_cell("Requests concentrate in a few ZIP codes rather than spreading out."),
        new_code_cell("df.head()"),
    ])
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, str(path))

    evidence = charts.collect_charts(path)
    assert evidence.source == charts.SOURCE_EXECUTED
    record = evidence.by_library(charts.ALTAIR)[0]
    assert record.rendered
    assert record.facts.has_brush
    assert "concentrate" in record.discussion
    assert "bar chart to compare" in record.preamble
    assert record.discussion_words >= 10


def test_a_chart_with_no_output_is_found_but_not_rendered(tmp_path):
    nb = _notebook([new_code_cell("sns.boxplot(data=df, x='a', y='b')")])
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, str(path))

    record = charts.collect_charts(path).by_library(charts.SEABORN)[0]
    assert record.rendered is False
    assert record.aesthetics["explicit_colors"] is False


def test_the_executed_notebook_is_preferred_over_the_submitted_one(tmp_path):
    executed = tmp_path / "executed.ipynb"
    submitted = tmp_path / "submitted.ipynb"
    rendered = new_code_cell("plt.plot(x, y)")
    rendered.outputs = [_image_output()]
    nbformat.write(_notebook([rendered]), str(executed))
    nbformat.write(_notebook([new_code_cell("plt.plot(x, y)")]), str(submitted))

    evidence = charts.collect_charts(executed, submitted)
    assert evidence.from_execution
    assert evidence.by_library(charts.MATPLOTLIB)[0].rendered


def test_the_submitted_notebook_is_the_fallback(tmp_path):
    submitted = tmp_path / "submitted.ipynb"
    cell = new_code_cell("plt.plot(x, y)")
    cell.outputs = [_image_output()]
    nbformat.write(_notebook([cell]), str(submitted))

    evidence = charts.collect_charts(tmp_path / "missing.ipynb", submitted)
    assert evidence.source == charts.SOURCE_SUBMITTED
    assert evidence.from_execution is False


def test_probe_cells_are_never_counted_as_student_charts(tmp_path):
    probe = new_code_cell("plt.plot([1], [2])")
    probe.metadata["musa_probe"] = True
    nb = _notebook([probe])
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, str(path))
    assert charts.collect_charts(path).charts == []


def test_an_errored_chart_cell_records_the_error(tmp_path):
    cell = new_code_cell("plt.plot(df['missing'])")
    cell.outputs = [nbformat.from_dict(
        {"output_type": "error", "ename": "KeyError", "evalue": "'missing'", "traceback": []}
    )]
    nb = _notebook([cell])
    path = tmp_path / "nb.ipynb"
    nbformat.write(nb, str(path))

    record = charts.collect_charts(path).by_library(charts.MATPLOTLIB)[0]
    assert record.errored and "KeyError" in record.error
    assert record.rendered is False


# ---------------------------------------------------------------------------
# Prose counting
# ---------------------------------------------------------------------------

def test_headings_and_placeholders_do_not_count_as_discussion():
    assert charts.prose_word_count("## My chart\n\n*Your answer here*") == 0
    assert charts.prose_word_count("## My chart\n\nRequests fell every winter.") == 4
