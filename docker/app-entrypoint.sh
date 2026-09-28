#!/bin/sh
# Starts as root only long enough to make the shared work directory writable and
# to join the group that owns the Docker socket (its gid differs per host: 0 on
# Docker Desktop, the `docker` group on Linux), then drops to the grader user.
set -e

if [ "$(id -u)" = "0" ]; then
    # Bind-mounted from the host, where Docker may have created them as root.
    mkdir -p "$TMPDIR"
    chown grader:grader "$TMPDIR" results .musa_grader_data
fi

groups=""
if [ -S /var/run/docker.sock ]; then
    groups="--groups $(stat -c %g /var/run/docker.sock)"
else
    echo "warning: /var/run/docker.sock is not mounted; only --mode local will work" >&2
fi

if [ "$(id -u)" = "0" ]; then
    # shellcheck disable=SC2086
    exec setpriv --reuid=10001 --regid=10001 ${groups:---clear-groups} "$@"
fi
exec "$@"
