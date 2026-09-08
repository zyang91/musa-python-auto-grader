# Isolated environment for executing student notebooks (design.md §18).
#
# Build:  docker build -t musa-grader:latest -f docker/Dockerfile .
#
# The container is started by grader/executor.py with --network none, memory and
# CPU limits, a read-only root filesystem and a tmpfs /tmp. Nothing in here
# should ever need network access or host credentials.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

# Wheels for geopandas/shapely need these; keep the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Pinned so a grading run is reproducible across the semester.
RUN pip install --no-cache-dir \
    "nbformat==5.10.4" \
    "nbclient==0.10.0" \
    "ipykernel==6.29.5" \
    "pandas==2.2.2" \
    "numpy==1.26.4" \
    "matplotlib==3.9.2" \
    "seaborn==0.13.2" \
    "scikit-learn==1.5.2" \
    "geopandas==1.0.1" \
    "shapely==2.0.6" \
    "pyproj==3.6.1" \
    "requests==2.32.3" \
    "openpyxl==3.1.5"

# A non-root user with no home directory of its own; /grading is bind-mounted.
RUN useradd --create-home --uid 10001 grader
USER grader
WORKDIR /grading

CMD ["python", "--version"]
