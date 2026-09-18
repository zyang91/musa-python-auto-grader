# Grading container

Build the image once per semester:

```bash
docker build -t musa-grader:latest -f docker/Dockerfile .
```

The grader starts one container per submission with:

| Flag | Why |
|---|---|
| `--network none` | student code cannot reach the internet or the campus network |
| `--memory 2g --memory-swap 2g` | a runaway allocation kills the container, not the laptop |
| `--cpus 1.0 --pids-limit 256` | one submission cannot starve the others |
| `--read-only` + `--tmpfs /tmp` | the image cannot be modified; scratch space is discarded |
| `-v <workdir>:/grading` | only the copied submission is visible, never the rest of the disk |

No host environment variables are forwarded, so API keys and credentials on the
grading machine are not visible to student code.

If a student notebook needs a package that is not in the image, add it to the
pinned list in `Dockerfile` and rebuild — do not install packages at grading
time, since the container has no network.

## Memory and time

Assignment 3 is the heavy one: a 24 MB GeoJSON, a spatial join over 34,108
points and two masks of a ten-band raster. It fits inside the 2 GB cap, but a
correct submission takes a few minutes rather than a few seconds, so the rubric
raises `execution_timeout_seconds` to 1800 — set the same on the command line
with `--timeout` and `--cell-timeout`.

## What is in the image, and why

The base list (pandas, matplotlib, seaborn, altair, geopandas, shapely) covers
Assignments 1 and 2. Assignment 3 adds rasterio, rasterstats, hvplot, holoviews,
bokeh, panel, cartopy, geoviews and mapclassify.

`geoviews` is there for a reason worth writing down: `hvplot.polygons()` on a
GeoDataFrame — the ordinary way to draw the two widget-driven choropleths the
assignment asks for — raises `ModuleNotFoundError` without it. A missing package
here is not a student's mistake, it is a zero for a correct submission.

Two pins are narrower than they look. `rasterio` must be 1.4.4 or newer:
earlier 1.4.x releases have no linux/arm64 wheel, and the build falls back to
compiling against a GDAL that is not in the image. `rasterstats` must be 0.21.0
or newer: 0.20.0 requires `fiona`, which has no linux/arm64 wheel at all.
Neither shows up on an Intel machine, only on Apple Silicon.
