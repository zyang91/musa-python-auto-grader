"""Build demo notebooks and a submissions folder that exercise the HW1 grader.

Four cases a TA actually meets: a correct submission, one with plausible
mistakes, one that crashes partway, and the untouched template.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data" / "zillow_zhvi.csv"
TEMPLATE = ROOT / "assignment_template" / "assignment-1.ipynb"
SUBMISSIONS = HERE / "submissions"

CENTER_CITY_LIST = (
    "greater_center_city_zip_codes = [\n"
    "    19123,\n    19102,\n    19103,\n    19106,\n    19107,\n"
    "    19109,\n    19130,\n    19146,\n    19147,\n]"
)

HEADINGS = [
    "# Assignment #1: The Donut Effect for Philadelphia ZIP Codes",
    "## 1. Load the data",
    "## 2. Trim the data to just Philadelphia",
    "## 3. Melt the data into tidy format",
    "## 4. Split the data for ZIP codes in/outside Center City",
    "## 5. Compare home value appreciation in Philadelphia",
]


def good_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(HEADINGS[0]),
        new_markdown_cell(HEADINGS[1]),
        new_code_cell(
            "import pandas as pd\n\n"
            'zhvi = pd.read_csv("data/zillow_zhvi.csv")\n'
            "zhvi.head()"
        ),
        new_markdown_cell(HEADINGS[2]),
        new_code_cell(
            'philly = zhvi.loc[(zhvi["City"] == "Philadelphia") & (zhvi["State"] == "PA")].copy()\n'
            "philly.shape"
        ),
        new_markdown_cell(HEADINGS[3]),
        new_code_cell(
            'id_columns = ["RegionID", "SizeRank", "RegionName", "RegionType",\n'
            '              "StateName", "State", "City", "Metro", "CountyName"]\n'
            "date_columns = [c for c in philly.columns if c not in id_columns]\n\n"
            "philly_tidy = philly.melt(\n"
            '    id_vars=["RegionName"],\n'
            "    value_vars=date_columns,\n"
            '    var_name="Date",\n'
            '    value_name="ZHVI",\n'
            ")\n"
            'philly_tidy["Date"] = pd.to_datetime(philly_tidy["Date"])\n'
            "philly_tidy.head()"
        ),
        new_markdown_cell(HEADINGS[4]),
        new_code_cell(CENTER_CITY_LIST),
        new_code_cell(
            'in_center_city = philly_tidy["RegionName"].isin(greater_center_city_zip_codes)\n'
            "center_city = philly_tidy.loc[in_center_city].copy()\n"
            "outside_center_city = philly_tidy.loc[~in_center_city].copy()\n\n"
            "print(center_city['RegionName'].nunique(), outside_center_city['RegionName'].nunique())"
        ),
        new_markdown_cell(HEADINGS[5]),
        new_code_cell(
            "def calculate_percent_increase(group_df):\n"
            '    """\n'
            "    Calculate the percent increase from 2020-03-31 to 2022-03-31.\n\n"
            "    Note that `group_df` is the DataFrame for each group.\n"
            '    """\n'
            '    start = group_df.loc[group_df["Date"] == "2020-03-31", "ZHVI"].squeeze()\n'
            '    end = group_df.loc[group_df["Date"] == "2022-03-31", "ZHVI"].squeeze()\n\n'
            "    return (end - start) / start * 100"
        ),
        new_code_cell(
            'center_city_change = center_city.groupby("RegionName").apply(calculate_percent_increase)\n'
            'outside_change = outside_center_city.groupby("RegionName").apply(calculate_percent_increase)\n\n'
            "center_city_avg = center_city_change.mean()\n"
            "outside_avg = outside_change.mean()\n\n"
            'print(f"Center City: {center_city_avg:.1f}%")\n'
            'print(f"Outside Center City: {outside_avg:.1f}%")'
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def partial_notebook() -> nbformat.NotebookNode:
    """Realistic mistakes: absolute path, wrong value column name, an incomplete
    Center City list, and a function that uses the first and last rows."""
    cells = [
        new_markdown_cell(HEADINGS[0]),
        new_markdown_cell(HEADINGS[1]),
        new_code_cell(
            "import os\n\n"
            "import pandas as pd\n\n"
            '# Falls back to where the file lives on my laptop\n'
            'path = "data/zillow_zhvi.csv"\n'
            "if not os.path.exists(path):\n"
            '    path = "/Users/student/Desktop/musa/zillow_zhvi.csv"\n'
            "df = pd.read_csv(path)\n"
            "df.shape"
        ),
        new_markdown_cell(HEADINGS[2]),
        new_code_cell(
            'philly = df[df["City"] == "Philadelphia"]\n'
            "philly.shape"
        ),
        new_markdown_cell(HEADINGS[3]),
        new_code_cell(
            "dates = [c for c in philly.columns if c[:2] in ('20', '19')]\n"
            "tidy = philly.melt(\n"
            "    id_vars=['RegionName'],\n"
            "    value_vars=dates,\n"
            "    var_name='date',\n"
            "    value_name='value',\n"
            ")\n"
            "tidy.shape"
        ),
        new_markdown_cell(HEADINGS[4]),
        new_code_cell(
            "# I only used the four main Center City ZIP codes\n"
            "greater_center_city_zip_codes = [19102, 19103, 19106, 19107]\n"
            "cc = tidy[tidy['RegionName'].isin(greater_center_city_zip_codes)]\n"
            "non_cc = tidy[~tidy['RegionName'].isin(greater_center_city_zip_codes)]\n"
            "cc['RegionName'].unique()"
        ),
        new_markdown_cell(HEADINGS[5]),
        new_code_cell(
            "def calculate_percent_increase(group_df):\n"
            '    """Percent increase over the period."""\n'
            "    first = group_df['value'].iloc[0]\n"
            "    last = group_df['value'].iloc[-1]\n"
            "    return (last - first) / first * 100"
        ),
        new_code_cell(
            "cc_change = cc.groupby('RegionName').apply(calculate_percent_increase)\n"
            "non_cc_change = non_cc.groupby('RegionName').apply(calculate_percent_increase)\n"
            "cc_avg = cc_change.mean()\n"
            "non_cc_avg = non_cc_change.mean()\n"
            "print(cc_avg, non_cc_avg)"
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def broken_notebook() -> nbformat.NotebookNode:
    cells = [
        new_markdown_cell(HEADINGS[0]),
        new_markdown_cell(HEADINGS[1]),
        new_code_cell(
            "import pandas as pd\n\n"
            'zhvi = pd.read_csv("data/zillow_zhvi.csv")\n'
            "zhvi.shape"
        ),
        new_markdown_cell(HEADINGS[2]),
        new_code_cell(
            'philly = zhvi[zhvi["City"] == "Philadelphia"].copy()\n'
            "philly.shape"
        ),
        new_markdown_cell(HEADINGS[3]),
        # "Zipcode" does not exist in a ZHVI file -> KeyError partway through.
        new_code_cell(
            'tidy = philly.melt(id_vars=["Zipcode"], var_name="Date", value_name="ZHVI")\n'
            "tidy.head()"
        ),
        new_markdown_cell(HEADINGS[4]),
        new_code_cell(CENTER_CITY_LIST),
        new_markdown_cell(HEADINGS[5]),
        new_code_cell(
            "def calculate_percent_increase(group_df):\n"
            '    start = group_df.loc[group_df["Date"] == "2020-03-31", "ZHVI"].squeeze()\n'
            '    end = group_df.loc[group_df["Date"] == "2022-03-31", "ZHVI"].squeeze()\n'
            "    return (end - start) / start * 100"
        ),
        new_code_cell(
            "center_city_avg = tidy.groupby('Zipcode').apply(calculate_percent_increase).mean()\n"
            "center_city_avg"
        ),
    ]
    return new_notebook(cells=cells, metadata=_metadata())


def _metadata() -> dict:
    return {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    }


NOTEBOOKS = {
    "good_submission.ipynb": good_notebook,
    "partial_submission.ipynb": partial_notebook,
    "broken_submission.ipynb": broken_notebook,
}

# student folder -> [(source notebook, filename in the submission)]
LAYOUT = {
    "student_001": [("good_submission.ipynb", "assignment-1.ipynb")],
    "student_002": [("good_submission.ipynb", "musa5500_hw1.ipynb")],
    "student_003": [("partial_submission.ipynb", "assignment1.ipynb")],
    "student_004": [
        ("good_submission.ipynb", "assignment-1.ipynb"),
        ("partial_submission.ipynb", "assignment-1-final.ipynb"),
    ],
    "student_005": [("broken_submission.ipynb", "submission.ipynb")],
    "student_006": [],  # submitted no notebook at all
    "student_007": [("__template__", "assignment-1.ipynb")],  # untouched template
}


def main() -> None:
    if not DATA.exists():
        raise SystemExit("run examples/make_example_data.py first")

    for filename, builder in NOTEBOOKS.items():
        nbformat.write(builder(), str(HERE / filename))
        print(f"wrote examples/{filename}")

    if SUBMISSIONS.exists():
        shutil.rmtree(SUBMISSIONS)
    for student, notebooks in LAYOUT.items():
        folder = SUBMISSIONS / student
        (folder / "data").mkdir(parents=True, exist_ok=True)
        shutil.copy2(DATA, folder / "data" / DATA.name)
        for source, target in notebooks:
            origin = TEMPLATE if source == "__template__" else HERE / source
            if not origin.exists():
                raise SystemExit(f"missing source notebook: {origin}")
            shutil.copy2(origin, folder / target)
        if not notebooks:
            (folder / "README.txt").write_text("I could not upload my notebook in time.\n")
    print(f"wrote {len(LAYOUT)} submissions to examples/submissions/")


if __name__ == "__main__":
    main()
