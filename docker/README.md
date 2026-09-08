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
