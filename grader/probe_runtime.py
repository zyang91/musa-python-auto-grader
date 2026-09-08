"""Code injected into the student's kernel after their notebook runs.

This module never runs on the grading host. Its source is appended to the
notebook as extra cells (see ``executor.py``), so it must:

* depend only on the standard library plus whatever the student imported,
* never raise into the student's namespace,
* describe objects rather than name them, because students do not use the
  solution's variable names (design.md §21),
* run the hidden test calls in-kernel so the tests never appear in the notebook
  the student receives (design.md §22).

Everything it produces is a JSON summary — no pickles leave the container.
"""

from __future__ import annotations

MUSA_PROBE_MARKER = "===MUSA_PROBE_JSON==="


def _musa_safe(value, depth=0):
    """Convert an arbitrary object into something json.dumps can handle."""
    if depth > 3:
        return repr(value)[:200]
    if value is None or isinstance(value, (bool, int, str)):
        return value if not isinstance(value, str) else value[:500]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [_musa_safe(v, depth + 1) for v in list(value)[:200]]
    if isinstance(value, dict):
        return {str(k)[:100]: _musa_safe(v, depth + 1) for k, v in list(value.items())[:100]}
    for attr in ("item", "isoformat"):
        if hasattr(value, attr):
            try:
                return _musa_safe(getattr(value, attr)(), depth + 1)
            except Exception:
                pass
    if hasattr(value, "tolist"):
        try:
            return _musa_safe(value.tolist(), depth + 1)
        except Exception:
            pass
    return repr(value)[:200]


def _musa_is_number(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return hasattr(value, "item") and hasattr(value, "dtype") and not hasattr(value, "columns")


def _musa_looks_boolean(series, pd):
    try:
        if str(series.dtype) == "bool":
            return True
        uniques = set(str(v).lower() for v in series.dropna().unique()[:5])
        return uniques and uniques.issubset({"true", "false", "0", "1", "yes", "no"})
    except Exception:
        return False


def _musa_profile_dataframe(name, df, config, pd):
    """Describe a DataFrame richly enough to grade it without knowing its name."""
    profile = {
        "name": name,
        "rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "columns": [str(c) for c in list(df.columns)[:300]],
        "dtypes": {},
        "head": [],
        "index_names": [str(n) for n in getattr(df.index, "names", []) if n is not None],
        "is_geodataframe": type(df).__name__ == "GeoDataFrame",
        "numeric_summary": {},
        "value_samples": {},
        "id_columns": [],
        "boolean_columns": [],
        "boolean_group_values": {},
        # Distinct-value counts for every column, capped value samples or not.
        # Grading a melt against the student's own ZIP x date grid needs these.
        "nunique": {},
        "truncated": len(df.columns) > 300,
    }
    max_head = int(config.get("max_head_rows", 5))
    max_unique = int(config.get("max_unique_values", 80))
    id_hints = [h.lower() for h in config.get("id_column_hints", [])]

    try:
        profile["dtypes"] = {str(c): str(t) for c, t in list(df.dtypes.items())[:300]}
    except Exception:
        pass
    try:
        head = df.head(max_head)
        profile["head"] = [
            {str(c): _musa_safe(v) for c, v in row.items()}
            for row in head.to_dict(orient="records")
        ]
    except Exception:
        pass

    columns = list(df.columns)[:300]
    for column in columns:
        label = str(column)
        if label.lower() in id_hints or any(h in label.lower() for h in id_hints):
            profile["id_columns"].append(label)
        try:
            series = df[column]
        except Exception:
            continue
        if getattr(series, "ndim", 1) != 1:
            continue
        try:
            if pd is not None and pd.api.types.is_numeric_dtype(series) and str(series.dtype) != "bool":
                described = series.dropna()
                if len(described):
                    profile["numeric_summary"][label] = {
                        "min": _musa_safe(described.min()),
                        "max": _musa_safe(described.max()),
                        "mean": _musa_safe(described.mean()),
                        "sum": _musa_safe(described.sum()),
                        "count": int(len(described)),
                    }
        except Exception:
            pass
        try:
            nunique = int(series.nunique(dropna=True))
            profile["nunique"][label] = nunique
            if nunique <= max_unique:
                values = [_musa_safe(v) for v in list(series.dropna().unique())[:max_unique]]
                profile["value_samples"][label] = values
            if _musa_looks_boolean(series, pd):
                profile["boolean_columns"].append(label)
        except Exception:
            pass

    # For each boolean flag column, record which ids it marks — this is how a
    # "center_city" style classification is graded without knowing its name.
    for flag in profile["boolean_columns"][:10]:
        try:
            mask = df[flag].astype("bool")
        except Exception:
            continue
        marked = {}
        for id_col in profile["id_columns"][:5]:
            try:
                values = df.loc[mask, id_col].dropna().unique()
                marked[id_col] = [_musa_safe(v) for v in list(values)[:200]]
            except Exception:
                continue
        if marked:
            profile["boolean_group_values"][flag] = marked
    return profile


def _musa_profile_functions(namespace):
    import inspect

    functions = []
    for name, obj in list(namespace.items()):
        if name.startswith("_musa") or name.startswith("__"):
            continue
        if not callable(obj) or inspect.isclass(obj) or inspect.ismodule(obj):
            continue
        module = getattr(obj, "__module__", None)
        if module not in (None, "__main__", "builtins") and not inspect.isfunction(obj):
            continue
        if module not in (None, "__main__"):
            continue
        entry = {"name": name, "params": [], "arity": 0, "source": "", "doc": ""}
        try:
            signature = inspect.signature(obj)
            params = [
                p.name
                for p in signature.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
            entry["params"] = params
            entry["arity"] = len(
                [
                    p
                    for p in signature.parameters.values()
                    if p.default is p.empty
                    and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
            )
        except Exception:
            pass
        try:
            entry["source"] = inspect.getsource(obj)[:4000]
        except Exception:
            pass
        try:
            entry["doc"] = (inspect.getdoc(obj) or "")[:500]
        except Exception:
            pass
        functions.append(entry)
    return functions


def _musa_select_function(namespace, functions, selector):
    """Rank student functions against name hints and arity (design.md §21)."""
    hints = [h.lower() for h in selector.get("name_hints", [])]
    want_arity = selector.get("arity")
    scored = []
    for entry in functions:
        lowered = entry["name"].lower()
        score = sum(2.0 for hint in hints if hint in lowered)
        if want_arity is not None:
            if entry["arity"] == want_arity:
                score += 3.0
            elif len(entry["params"]) == want_arity:
                score += 1.5
            else:
                score -= 2.0
        if entry.get("doc"):
            score += 0.1
        scored.append((score, entry["name"]))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    positive = [pair for pair in scored if pair[0] > 0]
    if not positive:
        return None, scored[:5], False
    best = positive[0]
    ambiguous = len(positive) > 1 and abs(positive[1][0] - best[0]) < 0.5
    return namespace.get(best[1]), scored[:5], ambiguous


def _musa_find_frame_schema(namespace, config, pd):
    """Find the student's tidy frame so a test input can copy its column names.

    The synthetic input has to look like what their function actually receives,
    which means using their column names and their date dtype, not ours.
    """
    if pd is None:
        return None
    date_hints = [h.lower() for h in config.get("date_column_hints", ["date"])]
    value_hints = [h.lower() for h in config.get("value_column_hints", ["zhvi", "value"])]
    min_rows = int(config.get("min_rows_for_schema", 50))

    best = None
    for name, obj in list(namespace.items()):
        if name.startswith("_") or not isinstance(obj, pd.DataFrame):
            continue
        if len(obj) < min_rows or len(obj.columns) > 40:
            continue
        date_col = value_col = None
        for column in obj.columns:
            label = str(column).lower()
            if date_col is None and (
                any(h in label for h in date_hints)
                or "datetime" in str(obj[column].dtype)
            ):
                date_col = column
            if value_col is None and any(h in label for h in value_hints):
                value_col = column
        if value_col is None:
            for column in obj.columns:
                try:
                    if pd.api.types.is_numeric_dtype(obj[column]) and column != date_col:
                        value_col = column
                        break
                except Exception:
                    continue
        if date_col is None or value_col is None:
            continue
        if best is None or len(obj) > best["rows"]:
            best = {
                "source": name,
                "rows": int(len(obj)),
                "columns": [str(c) for c in obj.columns],
                "date_column": str(date_col),
                "value_column": str(value_col),
                "date_is_datetime": "datetime" in str(obj[date_col].dtype),
                "fill": {
                    str(c): obj[c].iloc[0]
                    for c in obj.columns
                    if c not in (date_col, value_col)
                },
            }
    return best


def _musa_build_group_frame(anchors, schema, pd):
    """Monthly frame interpolated between (date, value) anchor points."""
    periods = pd.period_range(anchors[0][0], anchors[-1][0], freq="M")
    dates = periods.to_timestamp(how="end").normalize()

    series = pd.Series(index=dates, dtype="float64")
    for date_text, value in anchors:
        series.loc[pd.Timestamp(date_text)] = float(value)
    series = series.interpolate(method="index").ffill().bfill()

    date_values = dates if schema["date_is_datetime"] else dates.strftime("%Y-%m-%d")
    date_aliases = set(schema.get("date_aliases") or [])
    value_aliases = set(schema.get("value_aliases") or [])

    data = {}
    for column in schema["columns"]:
        if column == schema["date_column"] or column in date_aliases:
            data[column] = list(date_values)
        elif column == schema["value_column"] or column in value_aliases:
            data[column] = list(series.values)
        else:
            data[column] = [schema["fill"].get(column)] * len(dates)
    return pd.DataFrame(data, columns=schema["columns"])


def _musa_default_schema(config):
    """Fallback frame used when the student's tidy frame cannot be found.

    It carries every common spelling of the date and value columns at once, all
    holding the same data, so a function written against "Date"/"ZHVI" and one
    written against "date"/"value" both work on it. Without this, a notebook that
    crashed before creating its tidy frame could never have its function tested.
    """
    id_column = config.get("default_id_column", "RegionName")
    date_column = config.get("default_date_column", "date")
    value_column = config.get("default_value_column", "ZHVI")
    date_aliases = [c for c in ["date", "Date", "DATE", "variable", date_column]]
    value_aliases = [c for c in ["ZHVI", "zhvi", "value", "Value", value_column]]

    columns = [id_column]
    seen = {id_column}
    for column in date_aliases + value_aliases:
        if column not in seen:
            columns.append(column)
            seen.add(column)
    return {
        "source": None,
        "rows": 0,
        "columns": columns,
        "date_column": date_column,
        "value_column": value_column,
        "date_is_datetime": True,
        "fill": {id_column: "19102"},
        "date_aliases": [c for c in date_aliases if c != date_column],
        "value_aliases": [c for c in value_aliases if c != value_column],
    }


def _musa_run_group_frame_test(func, spec, namespace, pd):
    """Call a function that takes a per-group DataFrame (design.md §22)."""
    config = spec.get("frame", {})
    discovered = _musa_find_frame_schema(namespace, config, pd)
    schemas = []
    if discovered:
        schemas.append(("student_schema", discovered))
    schemas.append(("default_schema", _musa_default_schema(config)))

    calls = []
    for case in spec.get("cases", []):
        anchors = case.get("anchors", [])
        call = {"label": case.get("label"), "anchors": anchors}
        for schema_name, schema in schemas:
            try:
                frame = _musa_build_group_frame(anchors, schema, pd)
            except Exception as exc:
                call["build_error"] = "{}: {}".format(type(exc).__name__, exc)[:300]
                continue
            try:
                value = func(frame)
                call["ok"] = True
                call["value"] = _musa_safe(value)
                call["value_type"] = type(value).__name__
                call["schema_used"] = schema_name
                call["columns"] = schema["columns"]
                break
            except Exception as exc:
                call["ok"] = False
                call["error"] = "{}: {}".format(type(exc).__name__, exc)[:400]
                call["schema_used"] = schema_name
                call["columns"] = schema["columns"]
        calls.append(call)
    return calls, (discovered or {}).get("source")


def _musa_run_hidden_tests(namespace, functions, tests, pd=None):
    """Execute hidden calls in-kernel and report raw results only.

    Expected values stay on the grading host, so nothing in the container
    reveals the answer key. Two call styles are supported: plain scalar
    arguments, and a per-group DataFrame built to match the student's own
    tidy frame.
    """
    results = []
    for spec in tests:
        selector = spec.get("selector", {})
        func, ranking, ambiguous = _musa_select_function(namespace, functions, selector)
        entry = {
            "id": spec.get("id"),
            "type": spec.get("type", "scalar_args"),
            "function_name": getattr(func, "__name__", None),
            "found": func is not None,
            "ambiguous": ambiguous,
            "candidates": [{"name": n, "score": s} for s, n in ranking],
            "calls": [],
        }
        if func is None:
            results.append(entry)
            continue

        try:
            import inspect

            entry["source"] = inspect.getsource(func)[:4000]
        except Exception:
            entry["source"] = ""

        if entry["type"] == "group_frame":
            if pd is None:
                entry["error"] = "pandas is unavailable, so the function could not be tested"
            else:
                entry["calls"], entry["schema_source"] = _musa_run_group_frame_test(
                    func, spec, namespace, pd
                )
        else:
            for case in spec.get("cases", []):
                call = {"label": case.get("label"), "args": _musa_safe(case.get("args", []))}
                try:
                    value = func(*case.get("args", []), **case.get("kwargs", {}))
                    call["ok"] = True
                    call["value"] = _musa_safe(value)
                    call["value_type"] = type(value).__name__
                except Exception as exc:
                    call["ok"] = False
                    call["error"] = "{}: {}".format(type(exc).__name__, exc)[:400]
                entry["calls"].append(call)
        results.append(entry)
    return results


def _musa_probe_main(namespace, config):
    import json
    import os

    payload = {
        "ok": True,
        "errors": [],
        "dataframes": [],
        "series": [],
        "collections": [],
        "scalars": [],
        "functions": [],
        "modules": [],
        "figures": 0,
        "hidden_tests": [],
    }
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}

    try:
        import pandas as pd
    except Exception:
        pd = None
        payload["errors"].append("pandas is not importable in the student kernel")

    max_unique = int(config.get("max_unique_values", 80))
    for name, obj in list(namespace.items()):
        if name.startswith("_") or name in ("In", "Out", "exit", "quit", "get_ipython"):
            continue
        try:
            type_name = type(obj).__name__
            if pd is not None and isinstance(obj, pd.DataFrame):
                payload["dataframes"].append(_musa_profile_dataframe(name, obj, config, pd))
            elif pd is not None and isinstance(obj, pd.Series):
                entry = {
                    "name": name,
                    "length": int(len(obj)),
                    "dtype": str(obj.dtype),
                    "series_name": _musa_safe(obj.name),
                    "index_names": [str(n) for n in getattr(obj.index, "names", []) if n],
                    "index_sample": [_musa_safe(v) for v in list(obj.index[:max_unique])],
                    "head": [_musa_safe(v) for v in list(obj.head(5))],
                    "numeric_summary": None,
                    "unique_sample": [
                        _musa_safe(v) for v in list(obj.dropna().unique())[:max_unique]
                    ]
                    if int(obj.nunique(dropna=True)) <= max_unique
                    else None,
                }
                try:
                    if pd.api.types.is_numeric_dtype(obj) and str(obj.dtype) != "bool":
                        clean = obj.dropna()
                        if len(clean):
                            entry["numeric_summary"] = {
                                "min": _musa_safe(clean.min()),
                                "max": _musa_safe(clean.max()),
                                "mean": _musa_safe(clean.mean()),
                                "count": int(len(clean)),
                            }
                except Exception:
                    pass
                payload["series"].append(entry)
            elif isinstance(obj, (list, tuple, set, frozenset)):
                items = list(obj)
                if len(items) <= 500:
                    payload["collections"].append(
                        {
                            "name": name,
                            "type": type_name,
                            "length": len(items),
                            "values": [_musa_safe(v) for v in items[:200]],
                        }
                    )
            elif _musa_is_number(obj) or isinstance(obj, str):
                payload["scalars"].append(
                    {"name": name, "type": type_name, "value": _musa_safe(obj)}
                )
            elif type(obj).__module__ == "builtins" and isinstance(obj, dict):
                if len(obj) <= 100:
                    payload["collections"].append(
                        {
                            "name": name,
                            "type": "dict",
                            "length": len(obj),
                            "values": [_musa_safe(k) for k in list(obj.keys())[:200]],
                            "mapping": _musa_safe(obj),
                        }
                    )
            elif type_name == "module":
                payload["modules"].append(getattr(obj, "__name__", name))
        except Exception as exc:
            payload["errors"].append("profiling {}: {}".format(name, exc)[:300])

    try:
        payload["functions"] = _musa_profile_functions(namespace)
    except Exception as exc:
        payload["errors"].append("functions: {}".format(exc)[:300])

    try:
        import matplotlib.pyplot as _musa_plt

        payload["figures"] = len(_musa_plt.get_fignums())
    except Exception:
        pass

    try:
        payload["hidden_tests"] = _musa_run_hidden_tests(
            namespace, payload["functions"], config.get("hidden_tests", []), pd
        )
    except Exception as exc:
        payload["errors"].append("hidden tests: {}".format(exc)[:300])

    text = json.dumps(payload, default=lambda o: repr(o)[:200])
    out_dir = config.get("out_dir")
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "probe_results.json"), "w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as exc:
            payload["errors"].append("write: {}".format(exc)[:300])
    # Printed as a fallback so results survive even without a shared filesystem.
    print(MUSA_PROBE_MARKER)
    print(text)
    return payload
