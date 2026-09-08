"""Shared fixtures. Tests import the project from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader.rubric import load_rubric  # noqa: E402

CENTER_CITY = ["19102", "19103", "19106", "19107", "19109", "19123", "19130", "19146", "19147"]
PHILLY_ZIPS = sorted({f"191{n:02d}" for n in range(2, 54)} | set(CENTER_CITY))[:46]
OUTSIDE = sorted(set(PHILLY_ZIPS) - set(CENTER_CITY))
OTHER_CITIES = ["15201", "15203", "08102", "19801", "18101", "17101"]
N_DATES = 102


@pytest.fixture(scope="session")
def rubric():
    return load_rubric(ROOT / "rubrics" / "hw1.yaml")


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return ROOT / "examples"


def _wide_frame(name, zips, cities, states):
    """A ZHVI-shaped frame: identifier columns plus one column per month."""
    date_columns = [f"20{15 + i // 12}-{i % 12 + 1:02d}-28" for i in range(N_DATES)]
    return {
        "name": name,
        "rows": len(zips),
        "n_columns": 9 + N_DATES,
        "columns": ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
                    "State", "City", "Metro", "CountyName"] + date_columns,
        "dtypes": {"RegionName": "int64", "City": "object"},
        "head": [],
        "index_names": [],
        "numeric_summary": {"RegionID": {"min": 61000, "max": 61057}},
        "value_samples": {
            "RegionName": [int(z) for z in zips],
            "City": cities,
            "State": states,
        },
        "nunique": {"RegionName": len(zips), "City": len(cities)},
        "id_columns": ["RegionName"],
        "boolean_columns": [],
        "boolean_group_values": {},
    }


def _tidy_frame(name, zips, value_column="ZHVI", rows=None):
    rows = rows if rows is not None else len(zips) * N_DATES
    return {
        "name": name,
        "rows": rows,
        "n_columns": 3,
        "columns": ["RegionName", "Date", value_column],
        "dtypes": {"Date": "datetime64[ns]", value_column: "float64"},
        "head": [],
        "index_names": [],
        "numeric_summary": {value_column: {"min": 90000, "max": 620000}},
        "value_samples": {"RegionName": zips},
        "nunique": {"RegionName": len(zips), "Date": N_DATES, value_column: rows},
        "id_columns": ["RegionName"],
        "boolean_columns": [],
        "boolean_group_values": {},
    }


@pytest.fixture
def probe_payload():
    """Builder for a probe payload that looks like a correct HW1 submission."""

    def build(**overrides):
        payload = {
            "ok": True,
            "errors": [],
            "dataframes": [
                _wide_frame(
                    "zhvi", PHILLY_ZIPS + OTHER_CITIES,
                    ["Philadelphia", "Pittsburgh", "Camden", "Wilmington", "Allentown"],
                    ["PA", "NJ", "DE"],
                ),
                _wide_frame("philly", PHILLY_ZIPS, ["Philadelphia"], ["PA"]),
                _tidy_frame("philly_tidy", PHILLY_ZIPS),
                _tidy_frame("center_city", CENTER_CITY),
                _tidy_frame("outside_center_city", OUTSIDE),
            ],
            "series": [
                {
                    "name": "center_city_change", "length": 9, "dtype": "float64",
                    "series_name": None, "index_names": ["RegionName"],
                    "index_sample": CENTER_CITY, "head": [], "unique_sample": None,
                    "numeric_summary": {"min": 5.0, "max": 11.0, "mean": 8.2, "count": 9},
                },
                {
                    "name": "outside_change", "length": 37, "dtype": "float64",
                    "series_name": None, "index_names": ["RegionName"],
                    "index_sample": OUTSIDE, "head": [], "unique_sample": None,
                    "numeric_summary": {"min": 20.0, "max": 33.0, "mean": 26.8, "count": 37},
                },
            ],
            "collections": [
                {"name": "greater_center_city_zip_codes", "type": "list",
                 "length": 9, "values": [int(z) for z in CENTER_CITY]}
            ],
            "scalars": [
                {"name": "center_city_avg", "type": "float", "value": 8.2},
                {"name": "outside_avg", "type": "float", "value": 26.8},
            ],
            "functions": [
                {"name": "calculate_percent_increase", "params": ["group_df"], "arity": 1,
                 "source": FUNCTION_SOURCE, "doc": "Calculate the percent increase."}
            ],
            "modules": ["pandas"],
            "figures": 0,
            "hidden_tests": [
                {
                    "id": "percent_increase_function",
                    "type": "group_frame",
                    "function_name": "calculate_percent_increase",
                    "found": True,
                    "ambiguous": False,
                    "candidates": [{"name": "calculate_percent_increase", "score": 9.0}],
                    "source": FUNCTION_SOURCE,
                    "schema_source": "philly_tidy",
                    "calls": [
                        {"label": "100 → 150 (Mar 2020 → Mar 2022)", "ok": True,
                         "value": 50.0, "schema_used": "student_schema"},
                        {"label": "200 → 100 (a decrease)", "ok": True,
                         "value": -50.0, "schema_used": "student_schema"},
                        {"label": "300 → 300 (no change)", "ok": True,
                         "value": 0.0, "schema_used": "student_schema"},
                    ],
                }
            ],
        }
        payload.update(overrides)
        return payload

    return build


FUNCTION_SOURCE = '''def calculate_percent_increase(group_df):
    """Calculate the percent increase from 2020-03-31 to 2022-03-31."""
    start = group_df.loc[group_df["Date"] == "2020-03-31", "ZHVI"].squeeze()
    end = group_df.loc[group_df["Date"] == "2022-03-31", "ZHVI"].squeeze()
    return (end - start) / start * 100
'''

TEMPLATE_STUB_SOURCE = '''def calculate_percent_increase(group_df):
    """
    Calculate the percent increase from 2020-03-31 to 2022-03-31.

    Note that `group_df` is the DataFrame for each group.
    """

    ##
    ## Fill in this part!
    ##
'''
