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
pinned list in `requirements-sandbox.txt` and rebuild — do not install packages at grading
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

## Updating the pins

The sandbox's packages live in `requirements-sandbox.txt` so Dependabot can
propose bumps. CI rebuilds the image for every such PR, imports every package the
assignments use, and grades a real notebook in it. Passing CI means the image
still works — not that every student's numbers are unchanged, so merge sandbox
bumps between assignments rather than in the middle of grading one.

## Running the app itself in a container

`app.Dockerfile` packages the Streamlit UI and CLI; `docker-compose.yml` at the
repository root runs it:

```bash
docker build -t musa-grader:latest -f docker/Dockerfile .
docker compose up -d --build
```

The app never executes student code itself. It reaches the host's Docker daemon
through the mounted socket and starts one sandbox container per submission, as a
sibling, with every flag in the table above. Three details make that work:

| Detail | Why |
|---|---|
| `/tmp/musa-grader` is mounted at the **same path** on both sides | the sandbox's `-v <workdir>:/grading` is resolved by the host daemon, so the path the app sees must exist on the host |
| the app runs as uid 10001, the sandbox's user | work directories are mode 0700; the sandbox must be able to open them |
| the entrypoint joins the socket's group, then drops root | the socket's gid is 0 on Docker Desktop and `docker` on Linux |

Mounting the Docker socket gives the app container root-equivalent access to the
host. That is acceptable for a tool that runs on a TA's own machine and binds to
localhost only; do not expose port 8501 beyond it.

Outside a container the grader passes `--user <your uid>` to the sandbox for the
same reason, so docker mode works on a Linux host as well as on Docker Desktop.
