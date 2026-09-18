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
    # A numpy scalar is a number; a numpy *array* is not, and must never reach
    # _musa_safe(), which would serialise thousands of its elements. ``ndim`` is
    # read defensively: the numpy *module* has an ``ndim`` attribute too, and it
    # is a function.
    ndim = getattr(value, "ndim", 0)
    if isinstance(ndim, int) and ndim != 0:
        return False
    if not isinstance(ndim, int):
        return False
    return hasattr(value, "item") and hasattr(value, "dtype") and not hasattr(value, "columns")


def _musa_module_of(obj):
    try:
        return str(type(obj).__module__ or "")
    except Exception:
        return ""


def _musa_from(obj, package):
    """True when ``obj``'s class comes from ``package`` — no import required.

    Assignment 3 produces geopandas, numpy, shapely, rasterio and holoviews
    objects. The probe must describe them without importing anything the student
    did not, so libraries are recognised by where their classes live.
    """
    module = _musa_module_of(obj)
    return module == package or module.startswith(package + ".")


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
    max_columns = max(10, int(config.get("max_columns", 300)))
    profile = {
        "name": name,
        "rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "columns": [str(c) for c in list(df.columns)[:max_columns]],
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
        "truncated": len(df.columns) > max_columns,
    }
    max_head = int(config.get("max_head_rows", 5))
    max_unique = int(config.get("max_unique_values", 80))
    id_hints = [h.lower() for h in config.get("id_column_hints", [])]

    try:
        profile["dtypes"] = {str(c): str(t) for c, t in list(df.dtypes.items())[:max_columns]}
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

    columns = list(df.columns)[:max_columns]
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
                        # A median identifies a column of NDVI samples where a
                        # mean does not: both tails are bounded, so the mean
                        # barely moves when the wrong raster is sampled.
                        "median": _musa_safe(described.median()),
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

    if profile["is_geodataframe"]:
        try:
            _musa_geo_details(df, profile)
        except Exception:
            pass
    try:
        _musa_prefix_counts(df, profile, config)
    except Exception:
        pass
    return profile


# ---------------------------------------------------------------------------
# Geo, raster, array and plot profiling (Assignment 3)
# ---------------------------------------------------------------------------

def _musa_geo_details(df, profile):
    """Extra facts about a GeoDataFrame: CRS, geometry column, geometry types.

    Assignment 3 grades several steps on CRS alone — a spatial join between two
    frames in different CRSs, a hex bin map that has to leave EPSG:4326 — so the
    CRS has to travel with the profile rather than be guessed from the source.
    """
    try:
        geometry_column = str(getattr(df, "geometry", None).name)
    except Exception:
        geometry_column = "geometry"
    profile["geometry_column"] = geometry_column
    try:
        crs = df.crs
        # A CRS without an authority code stringifies to a full WKT block; the
        # EPSG code below is the usable form, so only a readable head is kept.
        profile["crs"] = str(crs)[:200] if crs is not None else None
        try:
            profile["crs_epsg"] = crs.to_epsg() if crs is not None else None
        except Exception:
            profile["crs_epsg"] = None
        try:
            profile["crs_is_projected"] = bool(crs.is_projected) if crs is not None else None
        except Exception:
            profile["crs_is_projected"] = None
    except Exception:
        pass
    try:
        geometry = df[geometry_column]
        types = geometry.geom_type.dropna().unique()
        profile["geom_types"] = sorted(str(t) for t in list(types)[:10])
        profile["n_valid_geometries"] = int(geometry.notna().sum())
    except Exception:
        pass
    try:
        bounds = df.total_bounds
        profile["total_bounds"] = [_musa_safe(float(b)) for b in list(bounds)[:4]]
    except Exception:
        pass
    try:
        # Students hold the city limits either as a bare shapely polygon or as
        # the one-row frame they read it from; this makes both gradeable the
        # same way. Meaningless in degrees, which is itself the signal that the
        # frame was never reprojected.
        profile["geometry_area"] = _musa_safe(float(df[geometry_column].area.sum()))
    except Exception:
        pass
    return profile


def _musa_prefix_counts(df, profile, config):
    """Value-prefix histograms for code columns named in the rubric.

    A GEOID is a county FIPS plus a tract number, so "every row is in
    Philadelphia County" is the statement that every GEOID starts with 42101.
    There are 384 of them, far past the value-sample cap, and a five-row head
    cannot prove it — but a histogram of the first five characters can, in a
    handful of bytes.
    """
    specs = config.get("prefix_profiles") or []
    if not specs:
        return profile
    out = {}
    columns = [str(c) for c in list(df.columns)[:300]]
    for spec in specs[:6]:
        hints = [str(h).lower() for h in (spec.get("hints") or [])]
        length = int(spec.get("length", 5))
        max_keys = int(spec.get("max_keys", 25))
        for column in columns:
            lowered = column.lower()
            if not any(h == lowered or h in lowered for h in hints):
                continue
            try:
                series = df[column]
                if getattr(series, "ndim", 1) != 1:
                    continue
                counts = series.dropna().astype(str).str[:length].value_counts()
                out[column] = {
                    "length": length,
                    "counts": {
                        str(k): int(v) for k, v in list(counts.items())[:max_keys]
                    },
                    "n_distinct": int(len(counts)),
                }
            except Exception:
                continue
    if out:
        profile["prefix_counts"] = out
    return profile


def _musa_array_summary(array):
    """NaN-aware description of a numpy array, masked or not.

    A masked array is what ``rasterio.mask.mask()`` returns, and an NDVI array is
    mostly NaN outside the polygon that produced it, so every statistic here has
    to ignore both.
    """
    import math

    entry = {}
    try:
        import numpy as _np
    except Exception:
        return entry
    try:
        entry["shape"] = [int(d) for d in list(getattr(array, "shape", ()))[:6]]
        entry["ndim"] = int(getattr(array, "ndim", 0))
        entry["dtype"] = str(getattr(array, "dtype", ""))
        entry["size"] = int(getattr(array, "size", 0))
    except Exception:
        return entry
    entry["masked"] = bool(_np.ma.isMaskedArray(array))
    try:
        values = array
        if entry["masked"]:
            entry["masked_fraction"] = float(_np.ma.getmaskarray(array).mean())
            values = _np.ma.filled(array.astype("float64"), _np.nan)
        else:
            values = _np.asarray(array)
            if values.dtype.kind not in "fiub":
                return entry
            values = values.astype("float64")
        finite = int(_np.isfinite(values).sum())
        entry["finite_count"] = finite
        entry["nan_count"] = int(entry["size"] - finite)
        if finite:
            with _np.errstate(invalid="ignore"):
                entry["min"] = _musa_safe(float(_np.nanmin(values)))
                entry["max"] = _musa_safe(float(_np.nanmax(values)))
                entry["mean"] = _musa_safe(float(_np.nanmean(values)))
                entry["median"] = _musa_safe(float(_np.nanmedian(values)))
    except Exception:
        pass
    return entry


def _musa_sequence_summary(items):
    """Numeric description of a long list, for sequences too big to carry."""
    numeric = []
    for value in items:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            if value != value:  # NaN
                continue
            numeric.append(float(value))
        elif hasattr(value, "item") and hasattr(value, "dtype"):
            try:
                converted = float(value.item())
            except Exception:
                continue
            if converted == converted:
                numeric.append(converted)
    if len(numeric) < max(1, len(items) // 2):
        return {}
    numeric.sort()
    middle = len(numeric) // 2
    median = (
        numeric[middle]
        if len(numeric) % 2
        else (numeric[middle - 1] + numeric[middle]) / 2.0
    )
    return {
        "count": len(numeric),
        "nan_count": len(items) - len(numeric),
        "min": _musa_safe(numeric[0]),
        "max": _musa_safe(numeric[-1]),
        "mean": _musa_safe(sum(numeric) / len(numeric)),
        "median": _musa_safe(median),
        "sum": _musa_safe(sum(numeric)),
    }


def _musa_profile_array(name, array):
    entry = {"name": name}
    entry.update(_musa_array_summary(array))
    return entry


def _musa_profile_geometry(name, geom):
    """A shapely geometry: enough to tell a city polygon from its suburbs ring."""
    entry = {"name": name, "type": type(geom).__name__}
    for attribute in ("geom_type", "area", "length"):
        try:
            entry[attribute] = _musa_safe(getattr(geom, attribute))
        except Exception:
            pass
    try:
        entry["bounds"] = [_musa_safe(float(b)) for b in list(geom.bounds)[:4]]
    except Exception:
        pass
    try:
        entry["n_geoms"] = int(getattr(geom, "geoms", []) and len(geom.geoms) or 1)
    except Exception:
        pass
    try:
        entry["is_valid"] = bool(geom.is_valid)
    except Exception:
        pass
    return entry


def _musa_profile_raster(name, dataset):
    entry = {"name": name, "type": type(dataset).__name__}
    for attribute in ("count", "width", "height", "mode", "closed"):
        try:
            entry[attribute] = _musa_safe(getattr(dataset, attribute))
        except Exception:
            pass
    try:  # the dataset's own name is the file it was opened from
        entry["path"] = str(getattr(dataset, "name", ""))[:300]
    except Exception:
        pass
    try:
        entry["crs"] = str(dataset.crs) if dataset.crs is not None else None
    except Exception:
        pass
    try:
        entry["bounds"] = [_musa_safe(float(b)) for b in list(dataset.bounds)[:4]]
    except Exception:
        pass
    try:
        entry["dtypes"] = [str(d) for d in list(dataset.dtypes)[:12]]
    except Exception:
        pass
    return entry


_MUSA_HV_CONTAINERS = (
    "HoloMap", "DynamicMap", "Layout", "NdLayout", "Overlay", "NdOverlay",
    "GridSpace", "GridMatrix",
)


def _musa_hv_dims(obj, attribute):
    try:
        return [str(d.name) for d in list(getattr(obj, attribute, []) or [])[:8]]
    except Exception:
        return []


def _musa_hv_children(obj, depth=0, found=None):
    """Element type names anywhere inside a holoviews container."""
    if found is None:
        found = []
    if depth > 3 or len(found) > 40:
        return found
    name = type(obj).__name__
    if name not in _MUSA_HV_CONTAINERS:
        found.append(name)
        return found
    try:
        children = list(obj.values())[:20]
    except Exception:
        try:
            children = list(obj)[:20]
        except Exception:
            children = []
    for child in children:
        _musa_hv_children(child, depth + 1, found)
    return found


def _musa_hv_values(obj):
    """Summary of the last value dimension of a holoviews element.

    This is how "plot the total number of evictions per year" is graded on the
    numbers actually plotted rather than on the code that produced them.
    """
    summary = {}
    try:
        dims = list(getattr(obj, "vdims", []) or [])
        if not dims:
            return summary
        values = obj.dimension_values(dims[-1])
        if len(values) > 20000:
            return summary
        numeric = [float(v) for v in values if isinstance(v, (int, float)) and v == v]
        if not numeric:
            return summary
        summary = {
            "dimension": str(dims[-1].name),
            "count": len(numeric),
            "min": _musa_safe(min(numeric)),
            "max": _musa_safe(max(numeric)),
            "sum": _musa_safe(float(sum(numeric))),
        }
    except Exception:
        return {}
    return summary


def _musa_profile_plot(name, obj, source):
    """Describe one holoviews/hvplot object.

    An hvplot call returns a holoviews object, and that object knows what it is:
    a HoloMap carries the dimension its widget selects and one frame per value,
    a Layout carries its row/column shape. Those are facts about the chart the
    student produced — far better evidence than searching the source for
    ``groupby=`` and ``dynamic=False``.
    """
    entry = {
        "name": name,
        "source": source,
        "type": type(obj).__name__,
        "module": _musa_module_of(obj),
        "kdims": _musa_hv_dims(obj, "kdims"),
        "vdims": _musa_hv_dims(obj, "vdims"),
    }
    try:
        entry["label"] = str(getattr(obj, "label", ""))[:80]
    except Exception:
        pass
    is_container = entry["type"] in _MUSA_HV_CONTAINERS
    entry["is_container"] = is_container
    if is_container:
        try:
            entry["n_frames"] = int(len(obj))
        except Exception:
            entry["n_frames"] = None
        try:
            shape = getattr(obj, "shape", None)
            if shape is not None:
                entry["shape"] = [int(v) for v in list(shape)[:2]]
        except Exception:
            pass
        try:
            keys = list(obj.keys())[:40]
            entry["keys"] = [_musa_safe(k) for k in keys]
        except Exception:
            pass
        try:
            # Direct children, separately from the elements found by descending:
            # a Layout of two Polygons and a Layout of two HoloMaps both draw
            # polygons, but only one of them is two static maps side by side.
            entry["child_types"] = [
                type(child).__name__ for child in list(obj.values())[:12]
            ]
        except Exception:
            entry["child_types"] = []
        entry["element_types"] = sorted(set(_musa_hv_children(obj)))
    else:
        entry["element_types"] = [entry["type"]]
        try:
            entry["n_points"] = int(len(obj))
        except Exception:
            pass
        values = _musa_hv_values(obj)
        if values:
            entry["values"] = values
    return entry


def _musa_displayed_objects(namespace):
    """Cell results, newest first — an hvplot chart is usually never named.

    ``df.hvplot.line(...)`` on the last line of a cell draws a chart and binds it
    to nothing, so the namespace has no record of it. IPython keeps every cell
    result in ``Out``, which is where those charts are found.
    """
    out = namespace.get("Out")
    if not isinstance(out, dict):
        return []
    items = []
    for key in sorted(out, reverse=True)[:80]:
        try:
            items.append(("Out[{}]".format(key), out[key]))
        except Exception:
            continue
    return items


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
    """Rank student functions against name hints and arity (design.md §21).

    A function must match at least one name hint. Arity alone is not evidence:
    a notebook with no percent-increase function but a one-argument helper such
    as ``looks_like_a_date`` used to have that helper graded as the answer.
    """
    hints = [h.lower() for h in selector.get("name_hints", [])]
    want_arity = selector.get("arity")
    scored = []
    for entry in functions:
        lowered = entry["name"].lower()
        hits = sum(1 for hint in hints if hint in lowered)
        score = 2.0 * hits
        if want_arity is not None:
            if entry["arity"] == want_arity:
                score += 3.0
            elif len(entry["params"]) == want_arity:
                score += 1.5
            else:
                score -= 2.0
        if entry.get("doc"):
            score += 0.1
        scored.append((score, entry["name"], hits))
    scored.sort(key=lambda triple: (-triple[0], triple[1]))
    ranking = [(score, name) for score, name, _ in scored[:5]]
    eligible = [t for t in scored if t[0] > 0 and (t[2] > 0 or not hints)]
    if not eligible:
        return None, ranking, False
    best = eligible[0]
    ambiguous = len(eligible) > 1 and abs(eligible[1][0] - best[0]) < 0.5
    return namespace.get(best[1]), ranking, ambiguous


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
        date_col = value_col = id_col = None
        id_hints = [h.lower() for h in config.get("id_column_hints", ["regionname", "zip"])]
        for column in obj.columns:
            label = str(column).lower()
            if id_col is None and any(h in label for h in id_hints):
                id_col = column
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
                "id_column": str(id_col) if id_col is not None else None,
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
        "id_column": id_column,
        "date_is_datetime": True,
        "fill": {id_column: "19102"},
        "date_aliases": [c for c in date_aliases if c != date_column],
        "value_aliases": [c for c in value_aliases if c != value_column],
    }


def _musa_table_numbers(value, pd):
    """Numbers inside a returned DataFrame/Series, so a table answer can be read."""
    if pd is None or not isinstance(value, (pd.DataFrame, pd.Series)):
        return None
    try:
        frame = value.to_frame() if isinstance(value, pd.Series) else value
        if frame.size > 400:
            return {"shape": list(frame.shape), "numbers": [], "truncated": True}
        numbers = []
        for column in frame.columns:
            if not pd.api.types.is_numeric_dtype(frame[column]) or str(frame[column].dtype) == "bool":
                continue
            for item in frame[column].tolist():
                number = _musa_safe(item)
                if isinstance(number, (int, float)) and not isinstance(number, bool):
                    numbers.append(number)
        return {"shape": list(frame.shape), "columns": [str(c) for c in frame.columns][:20],
                "numbers": numbers[:60]}
    except Exception:
        return None


def _musa_multi_group_frame(anchors, schema, pd):
    """The same series for two ZIP codes, for functions written for a whole frame."""
    id_column = schema.get("id_column")
    if not id_column:
        return None
    base = schema["fill"].get(id_column)
    try:
        first = int(base)
        ids = (first, first + 1) if not isinstance(base, str) else (str(first), str(first + 1))
    except (TypeError, ValueError):
        ids = ("19102", "19103")
    frames = []
    for identifier in ids:
        frame = _musa_build_group_frame(anchors, schema, pd)
        frame[id_column] = identifier
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _musa_run_group_frame_test(func, spec, namespace, pd):
    """Call a function that takes a per-group DataFrame (design.md §22).

    Tried in order, stopping at the first call that does not raise: the student's
    own schema, the multi-spelling default schema, and each of those again with
    two ZIP codes in one frame — some students write the function for the whole
    split frame rather than one group, and it still computes the right numbers.
    """
    config = spec.get("frame", {})
    discovered = _musa_find_frame_schema(namespace, config, pd)
    schemas = []
    if discovered:
        schemas.append(("student_schema", discovered))
    schemas.append(("default_schema", _musa_default_schema(config)))

    attempts = [(name, schema, False) for name, schema in schemas]
    attempts += [(name + "_multi_group", schema, True) for name, schema in schemas]

    calls = []
    for case in spec.get("cases", []):
        anchors = case.get("anchors", [])
        call = {"label": case.get("label"), "anchors": anchors}
        for attempt_name, schema, multi in attempts:
            try:
                frame = (_musa_multi_group_frame(anchors, schema, pd) if multi
                         else _musa_build_group_frame(anchors, schema, pd))
            except Exception as exc:
                call["build_error"] = "{}: {}".format(type(exc).__name__, exc)[:300]
                continue
            if frame is None:
                continue
            try:
                value = func(frame)
            except Exception as exc:
                call["ok"] = False
                call.setdefault("error", "{}: {}".format(type(exc).__name__, exc)[:400])
                call["schema_used"] = attempt_name
                call["columns"] = schema["columns"]
                continue
            call["ok"] = True
            call.pop("error", None)
            call["value"] = _musa_safe(value)
            call["value_type"] = type(value).__name__
            call["table"] = _musa_table_numbers(value, pd)
            call["schema_used"] = attempt_name
            call["columns"] = schema["columns"]
            break
        calls.append(call)
    return calls, (discovered or {}).get("source")


def _musa_select_by_behaviour(namespace, functions, spec, entry, pd):
    """When no function name matches, find the answer by what it does.

    A correct `percInc(group_df)` names nothing the hints know. Each function
    with the right arity is called on the test frames; the first that returns a
    number (or a table of numbers) is graded. A helper such as
    `looks_like_a_date(column_name)` raises on a DataFrame and is passed over.
    """
    selector = spec.get("selector", {})
    want = selector.get("arity")
    for candidate in functions:
        if want is not None and candidate["arity"] != want and len(candidate["params"]) != want:
            continue
        func = namespace.get(candidate["name"])
        if not callable(func):
            continue
        calls, source = _musa_run_group_frame_test(func, spec, namespace, pd)
        answered = [
            call for call in calls
            if call.get("ok") and (
                (isinstance(call.get("value"), (int, float)) and not isinstance(call.get("value"), bool))
                or (call.get("table") or {}).get("numbers")
            )
        ]
        if answered:
            entry.update(function_name=candidate["name"], found=True, selected_by="behaviour",
                         calls=calls, schema_source=source)
            return func
    return None


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
        if func is None and entry["type"] == "group_frame" and pd is not None:
            func = _musa_select_by_behaviour(namespace, functions, spec, entry, pd)

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
            elif not entry["calls"]:
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
        # Assignment 3: raster arrays, polygons, open datasets and hvplot charts.
        "arrays": [],
        "geometries": [],
        "rasters": [],
        "plots": [],
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
            elif (
                pd is not None
                and type_name.endswith("GroupBy")
                and isinstance(getattr(obj, "obj", None), pd.DataFrame)
            ):
                # A frame that only survives as `df.groupby(...)` is still the
                # student's split; profile the frame the GroupBy wraps.
                profile = _musa_profile_dataframe(name, obj.obj, config, pd)
                profile["from_groupby"] = True
                payload["dataframes"].append(profile)
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
                        for level_number in range(obj.index.nlevels):
                            level = obj.index.get_level_values(level_number)
                            if pd.api.types.is_bool_dtype(level):
                                means = obj.groupby(level=level_number).mean()
                                entry["bool_level_means"] = {
                                    str(bool(key)): _musa_safe(value)
                                    for key, value in means.items()
                                }
                                break
                except Exception:
                    pass
                try:
                    if pd.api.types.is_numeric_dtype(obj) and str(obj.dtype) != "bool":
                        clean = obj.dropna()
                        if len(clean):
                            entry["numeric_summary"] = {
                                "min": _musa_safe(clean.min()),
                                "max": _musa_safe(clean.max()),
                                "mean": _musa_safe(clean.mean()),
                                "median": _musa_safe(clean.median()),
                                "sum": _musa_safe(clean.sum()),
                                "count": int(len(clean)),
                            }
                except Exception:
                    pass
                payload["series"].append(entry)
            elif _musa_from(obj, "holoviews") or _musa_from(obj, "geoviews"):
                payload["plots"].append(_musa_profile_plot(name, obj, "variable"))
            elif _musa_from(obj, "numpy") and type_name in ("ndarray", "MaskedArray", "matrix"):
                payload["arrays"].append(_musa_profile_array(name, obj))
            elif _musa_from(obj, "shapely"):
                payload["geometries"].append(_musa_profile_geometry(name, obj))
            elif _musa_from(obj, "rasterio") and hasattr(obj, "read"):
                payload["rasters"].append(_musa_profile_raster(name, obj))
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
                else:
                    # Too long to carry, but not too long to describe: a list of
                    # 2,480 sampled NDVI values is an answer, and dropping it
                    # would make that answer invisible.
                    entry = {"name": name, "type": type_name, "length": len(items)}
                    summary = _musa_sequence_summary(items)
                    if summary:
                        entry["numeric_summary"] = summary
                    payload["collections"].append(entry)
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

    # Charts the student displayed without naming (see _musa_displayed_objects).
    seen_plots = set(entry.get("name") for entry in payload["plots"])
    for name, obj in _musa_displayed_objects(namespace):
        if len(payload["plots"]) >= 60:
            break
        try:
            if not (_musa_from(obj, "holoviews") or _musa_from(obj, "geoviews")):
                continue
            if any(obj is namespace.get(known) for known in seen_plots):
                continue
            payload["plots"].append(_musa_profile_plot(name, obj, "output"))
        except Exception as exc:
            payload["errors"].append("plot {}: {}".format(name, exc)[:300])

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
