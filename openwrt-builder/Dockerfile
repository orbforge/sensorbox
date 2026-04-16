# Lightweight builder image that checks if the custom ImageBuilder
# container is up-to-date and runs the OpenWrt buildroot if not.
#
# This container does NOT run the buildroot itself — it orchestrates:
# 1. git ls-remote to check the latest commit on the fork
# 2. Podman API to check the existing ImageBuilder container's label
# 3. If stale: clone/update the fork, run make, produce ImageBuilder
#    tarball, build a new container via Podman API, tag it

FROM docker.io/library/debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git curl python3 ca-certificates build-essential gawk unzip \
        file wget python3-distutils rsync libncurses-dev zlib1g-dev \
        xz-utils libelf-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
