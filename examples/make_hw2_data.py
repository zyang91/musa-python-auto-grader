"""Generate a stand-in Philadelphia 311 extract for Assignment 2.

Assignment 2 lets students pick their own dataset, so there is no canonical
file to ship. This produces something with the shape of an OpenDataPhilly 311
export — timestamps, a category, a ZIP code, a status — so the example
submissions have something real to plot. It is a fixture, never an answer key:
the HW2 checks never compare against anything in here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "philly_311_sample.csv"

SERVICES = [
    "Illegal Dumping", "Abandoned Vehicle", "Pothole Repair", "Street Light Outage",
    "Graffiti Removal", "Rubbish Collection", "Maintenance Residential or Commercial",
    "Traffic Signal Emergency",
]
AGENCIES = ["Streets Department", "License & Inspections", "Police Department",
            "Parks & Recreation"]
ZIPS = [19102, 19104, 19106, 19107, 19119, 19121, 19123, 19125, 19130, 19132,
        19134, 19139, 19143, 19145, 19146, 19147, 19148, 19149]
STATUSES = ["Closed", "Open", "In Progress"]


# Small on purpose: Altair inlines the whole dataframe into every chart spec,
# and the demo notebooks are committed with their outputs. A larger fixture
# would put megabytes of duplicated rows in the repository without making any
# of the example charts more illustrative.
def build(n_rows: int = 400, seed: int = 5500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.to_datetime("2023-01-01") + pd.to_timedelta(
        rng.integers(0, 730, n_rows), unit="D"
    ) + pd.to_timedelta(rng.integers(0, 24 * 60, n_rows), unit="m")
    zips = rng.choice(ZIPS, n_rows)
    # A little structure so the example charts have something to conclude about.
    days_to_close = np.clip(
        rng.gamma(shape=2.0, scale=6.0, size=n_rows) + (zips % 10) * 0.4, 0.2, 120
    )
    return pd.DataFrame(
        {
            "service_request_id": np.arange(1_000_000, 1_000_000 + n_rows),
            "requested_datetime": dates,
            "service_name": rng.choice(SERVICES, n_rows),
            "agency_responsible": rng.choice(AGENCIES, n_rows),
            "zipcode": zips,
            "status": rng.choice(STATUSES, n_rows, p=[0.72, 0.18, 0.10]),
            "days_to_close": days_to_close.round(2),
            "lat": (39.95 + rng.normal(0, 0.05, n_rows)).round(5),
            "lon": (-75.16 + rng.normal(0, 0.05, n_rows)).round(5),
        }
    ).sort_values("requested_datetime", ignore_index=True)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame = build()
    frame.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(frame)} rows)")


if __name__ == "__main__":
    main()
