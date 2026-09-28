# The grader itself — Streamlit UI and CLI — packaged so it moves to a new
# machine with `docker compose up` instead of a Python setup (see docker/README.md).
#
# This is NOT the sandbox that runs student notebooks; that is docker/Dockerfile.
# The app starts sandbox containers through the host's Docker socket, so they are
# siblings of this container, not children, and keep every isolation flag.
#
# Build:  docker build -t musa-grader-app:latest -f docker/app.Dockerfile .

# Only the docker CLI is taken from this image; the daemon is the host's.
FROM docker:29-cli AS docker-cli

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    # Work directories must sit at the same path on the host and in here: the
    # sandbox bind-mounts them, and the host daemon resolves that path on the
    # host. docker-compose.yml mounts this directory at an identical path.
    TMPDIR=/tmp/musa-grader

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Same uid as the sandbox user, so a work directory this app creates (mode
# 0700) is one the sandbox can open.
RUN useradd --no-create-home --uid 10001 grader \
    && mkdir -p results .musa_grader_data submissions \
    && chown -R grader:grader results .musa_grader_data submissions \
    && chmod +x docker/app-entrypoint.sh

EXPOSE 8501
ENTRYPOINT ["docker/app-entrypoint.sh"]
CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
