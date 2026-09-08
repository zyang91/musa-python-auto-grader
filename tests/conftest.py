"""Shared fixtures. Tests import the project from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader.rubric import load_rubric  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def rubric():
    return load_rubric(ROOT / "rubrics" / "hw1.yaml")


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return ROOT / "examples"


@pytest.fixture
def probe_payload():
    """Builder for a probe payload that looks like a correct submission."""

    def build(**overrides):
        payload = {
            "ok": True,
            "errors": [],
            "dataframes": [
                {
                    "name": "home_values",
                    "rows": 58,
                    "n_columns": 127,
                    "columns": ["RegionID", "RegionName", "City", "State"] + [
                        f"2010-{month:02d}-01" for month in range(1, 13)
                    ],
                    "dtypes": {"RegionName": "int64", "City": "object"},
                    "head": [],
                    "index_names": [],
                    "numeric_summary": {"RegionID": {"min": 1, "max": 58}},
                    "value_samples": {
                        # The raw file holds every ZIP in the region, Philadelphia
                        # and otherwise — as the real probe would report it.
                        "RegionName": [19102 + n for n in range(46)]
                        + [15201, 15203, 15206, 8102, 8103, 19801, 19802, 18101,
                           18102, 17101, 17102, 8608],
                        "City": ["Philadelphia", "Pittsburgh", "Camden"],
                    },
                    "id_columns": ["RegionName"],
                    "boolean_columns": [],
                    "boolean_group_values": {},
                },
                {
                    "name": "philly_tidy",
                    "rows": 5566,
                    "n_columns": 6,
                    "columns": ["zipcode", "City", "State", "date", "home_value", "center_city"],
                    "dtypes": {"date": "datetime64[ns]", "home_value": "float64"},
                    "head": [],
                    "index_names": [],
                    "numeric_summary": {"home_value": {"min": 100, "max": 500000}},
                    "value_samples": {
                        "zipcode": [f"191{n:02d}" for n in range(2, 48)],
                        "center_city": [True, False],
                    },
                    "id_columns": ["zipcode"],
                    "boolean_columns": ["center_city"],
                    "boolean_group_values": {
                        "center_city": {"zipcode": ["19102", "19103", "19106", "19107"]}
                    },
                },
            ],
            "series": [],
            "collections": [
                {
                    "name": "center_city_zips",
                    "type": "list",
                    "length": 4,
                    "values": ["19102", "19103", "19106", "19107"],
                }
            ],
            "scalars": [{"name": "center_city_change", "type": "float", "value": 31.42}],
            "functions": [
                {"name": "percent_increase", "params": ["start", "end"], "arity": 2,
                 "source": "def percent_increase(start, end):\n    return (end - start) / start * 100",
                 "doc": ""}
            ],
            "modules": ["pandas"],
            "figures": 1,
            "hidden_tests": [
                {
                    "id": "percent_change_function",
                    "function_name": "percent_increase",
                    "found": True,
                    "ambiguous": False,
                    "candidates": [{"name": "percent_increase", "score": 7.0}],
                    "source": "def percent_increase(start, end): ...",
                    "calls": [
                        {"label": "100 → 120", "ok": True, "value": 20.0},
                        {"label": "50 → 75", "ok": True, "value": 50.0},
                        {"label": "200 → 100", "ok": True, "value": -50.0},
                        {"label": "40 → 40", "ok": True, "value": 0.0},
                        {"label": "332217.5 → 436600.25", "ok": True, "value": 31.42},
                    ],
                }
            ],
        }
        payload.update(overrides)
        return payload

    return build
