"""Generate a stand-in Zillow ZHVI extract for Assignment 1.

The real class downloads its own file from Zillow, and that file changes every
month. This script produces something with the same *shape* so the grader can be
exercised end to end — it is not, and must not become, an answer key: the HW1
checks never compare against the numbers printed here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "zillow_zhvi.csv"

# The list handed to students in assignment-1.ipynb.
GREATER_CENTER_CITY = [19123, 19102, 19103, 19106, 19107, 19109, 19130, 19146, 19147]

PHILLY_ZIPS = sorted(
    {
        19102, 19103, 19104, 19106, 19107, 19109, 19111, 19114, 19115, 19116,
        19118, 19119, 19120, 19121, 19122, 19123, 19124, 19125, 19126, 19127,
        19128, 19129, 19130, 19131, 19132, 19133, 19134, 19135, 19136, 19137,
        19138, 19139, 19140, 19141, 19142, 19143, 19144, 19145, 19146, 19147,
        19148, 19149, 19150, 19151, 19152, 19153,
    }
)

OTHER_PLACES = [
    (15201, "Pittsburgh", "PA"), (15203, "Pittsburgh", "PA"),
    (15206, "Pittsburgh", "PA"), (8102, "Camden", "NJ"),
    (8103, "Camden", "NJ"), (19801, "Wilmington", "DE"),
    (19802, "Wilmington", "DE"), (18101, "Allentown", "PA"),
    (18102, "Allentown", "PA"), (17101, "Harrisburg", "PA"),
    (17102, "Harrisburg", "PA"), (8608, "Trenton", "NJ"),
]

START, END = "2015-01-31", "2023-06-30"
COMPARE_START, COMPARE_END = "2020-03-31", "2022-03-31"

# The Donut Effect: the suburbs and outer neighbourhoods outpace the core.
CENTER_CITY_GROWTH = 0.08
ELSEWHERE_GROWTH = 0.27

ID_COLUMNS = [
    "RegionID", "SizeRank", "RegionName", "RegionType",
    "StateName", "State", "City", "Metro", "CountyName",
]


def build() -> pd.DataFrame:
    rng = np.random.default_rng(5500)
    # period_range keeps this working across pandas 2.x, where the monthly
    # frequency alias was renamed from "M" to "ME".
    dates = pd.period_range(START, END, freq="M").to_timestamp(how="end").normalize()

    rows = []
    region_id, size_rank = 61000, 1
    for zipcode in PHILLY_ZIPS:
        rows.append((region_id, size_rank, zipcode, "zip", "Pennsylvania", "PA",
                     "Philadelphia", "Philadelphia-Camden-Wilmington", "Philadelphia County"))
        region_id += 1
        size_rank += 1
    for zipcode, city, state in OTHER_PLACES:
        rows.append((region_id, size_rank, zipcode, "zip",
                     {"PA": "Pennsylvania", "NJ": "New Jersey", "DE": "Delaware"}[state],
                     state, city, f"{city} Metro", f"{city} County"))
        region_id += 1
        size_rank += 1

    meta = pd.DataFrame(rows, columns=ID_COLUMNS)

    start_index = list(dates).index(pd.Timestamp(COMPARE_START))
    end_index = list(dates).index(pd.Timestamp(COMPARE_END))

    series = {}
    for _, row in meta.iterrows():
        is_center_city = row["RegionName"] in GREATER_CENTER_CITY
        growth = CENTER_CITY_GROWTH if is_center_city else ELSEWHERE_GROWTH
        growth *= 1 + rng.uniform(-0.15, 0.15)  # per-ZIP variation

        # A growth path pinned to known values at the two comparison dates.
        anchors = pd.Series(index=dates, dtype="float64")
        anchors.iloc[0] = 0.86
        anchors.iloc[start_index] = 1.0
        anchors.iloc[end_index] = 1.0 + growth
        anchors.iloc[-1] = 1.0 + growth + 0.04
        path = anchors.interpolate(method="index")

        base = (420_000 if is_center_city else 190_000) * (1 + rng.uniform(-0.15, 0.15))
        series[row["RegionID"]] = np.round(base * path.to_numpy(), 0)

    wide = pd.DataFrame(
        {
            date.strftime("%Y-%m-%d"): [series[rid][i] for rid in meta["RegionID"]]
            for i, date in enumerate(dates)
        }
    )
    return pd.concat([meta, wide], axis=1)


def describe(df: pd.DataFrame) -> dict:
    """What a correct solution would produce from *this* file, for reference only."""
    date_columns = [c for c in df.columns if c not in ID_COLUMNS]
    philly = df[(df["City"] == "Philadelphia") & (df["State"] == "PA")]
    center = philly[philly["RegionName"].isin(GREATER_CENTER_CITY)]
    outside = philly[~philly["RegionName"].isin(GREATER_CENTER_CITY)]

    def mean_growth(frame: pd.DataFrame) -> float:
        change = (frame[COMPARE_END] - frame[COMPARE_START]) / frame[COMPARE_START] * 100
        return round(float(change.mean()), 2)

    return {
        "rows": int(len(df)),
        "date_columns": len(date_columns),
        "philadelphia_zip_codes": int(philly["RegionName"].nunique()),
        "tidy_rows": int(len(philly) * len(date_columns)),
        "center_city_zip_codes": int(center["RegionName"].nunique()),
        "outside_zip_codes": int(outside["RegionName"].nunique()),
        "mean_percent_increase_center_city": mean_growth(center),
        "mean_percent_increase_outside": mean_growth(outside),
    }


if __name__ == "__main__":
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    facts = describe(df)
    (HERE / "data" / "example_data_facts.json").write_text(json.dumps(facts, indent=2))
    print(f"wrote {OUT} ({len(df)} rows x {len(df.columns)} columns)")
    print(json.dumps(facts, indent=2))
