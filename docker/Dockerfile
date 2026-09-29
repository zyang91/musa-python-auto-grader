# Isolated environment for executing student notebooks (design.md §18).
#
# Build:  docker build -t musa-grader:latest -f docker/Dockerfile .
#
# The container is started by grader/executor.py with --network none, memory and
# CPU limits, a read-only root filesystem and a tmpfs /tmp. Nothing in here
# should ever need network access or host credentials.
FROM python:3.14-slim

# MPLBACKEND is the *inline* backend, not Agg. Under Agg, `plt.show()` draws
# nothing and the notebook keeps no image — which is fine for Assignment 1 but
# silently deletes the graded artefact of a visualization assignment. The
# inline backend renders through Agg too, so it is just as headless.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=module://matplotlib_inline.backend_inline \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

# Wheels for geopandas/shapely/rasterio need these; keep the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Pinned so a grading run is reproducible across the semester. The list lives in
# its own file so Dependabot can propose bumps; the reasons behind individual
# pins are written next to them there.
COPY docker/requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt \
    && rm /tmp/requirements-sandbox.txt

# A non-root user with no home directory of its own; /grading is bind-mounted.
RUN useradd --create-home --uid 10001 grader
USER grader
WORKDIR /grading

CMD ["python", "--version"]
