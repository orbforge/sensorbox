#!/bin/sh
# orb-forge custom ImageBuilder builder.
#
# Checks if the ImageBuilder container for a custom OpenWrt fork is
# up-to-date (by comparing the remote branch's HEAD commit against
# the label on the existing container image). If stale or missing,
# runs the full OpenWrt buildroot and produces a new ImageBuilder
# container image that ASU can use for per-user builds.
#
# Designed to run as a compose service: starts on `compose up`,
# builds if needed, exits when done. The resulting container image
# is tagged in the local Podman store where ASU finds it.

set -eu

: "${OPENWRT_REPO:?OPENWRT_REPO must be set}"
: "${OPENWRT_BRANCH:?OPENWRT_BRANCH must be set}"
: "${OPENWRT_TARGET:?OPENWRT_TARGET must be set}"
: "${IMAGEBUILDER_TAG:?IMAGEBUILDER_TAG must be set}"
: "${CONTAINER_SOCKET_PATH:?CONTAINER_SOCKET_PATH must be set}"

CACHE_DIR="/cache"
LABEL_KEY="org.orbforge.source-commit"

log() {
    echo "[openwrt-builder] $*"
}

# Get the latest commit hash from the remote branch.
get_remote_commit() {
    git ls-remote "$OPENWRT_REPO" "refs/heads/$OPENWRT_BRANCH" | awk '{print $1}'
}

# Check if the ImageBuilder container exists and has a matching commit label.
get_built_commit() {
    # Use podman via the socket to inspect the image
    curl -s --unix-socket "$CONTAINER_SOCKET_PATH" \
        "http://d/v5.0.0/libpod/images/$IMAGEBUILDER_TAG/json" 2>/dev/null \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    labels = data.get('Config', {}).get('Labels', {}) or {}
    print(labels.get('$LABEL_KEY', ''))
except:
    print('')
" 2>/dev/null || echo ""
}

# Build the ImageBuilder container from source.
do_build() {
    local commit="$1"
    log "Building ImageBuilder from $OPENWRT_REPO@$commit ($OPENWRT_BRANCH)"

    # Clone or update the source tree
    if [ -d "$CACHE_DIR/openwrt/.git" ]; then
        log "Updating existing clone..."
        cd "$CACHE_DIR/openwrt"
        git fetch origin "$OPENWRT_BRANCH"
        git checkout "origin/$OPENWRT_BRANCH"
        git clean -fdx
    else
        log "Cloning $OPENWRT_REPO ($OPENWRT_BRANCH)..."
        git clone --branch "$OPENWRT_BRANCH" --single-branch \
            "$OPENWRT_REPO" "$CACHE_DIR/openwrt"
        cd "$CACHE_DIR/openwrt"
    fi

    log "Updating feeds..."
    ./scripts/feeds update -a
    ./scripts/feeds install -a

    # Apply the defconfig if provided, otherwise use the cached .config
    if [ -f /builder-config/defconfig ]; then
        cp /builder-config/defconfig .config
        make defconfig
    elif [ ! -f .config ]; then
        log "ERROR: no .config or /builder-config/defconfig found"
        exit 1
    fi

    log "Starting build (this takes ~45 minutes)..."
    make -j"$(nproc)" V=s 2>&1 | tail -5

    # Find the ImageBuilder tarball
    local ib_tarball
    ib_tarball=$(find bin/targets -name 'openwrt-imagebuilder-*.tar.xz' | head -1)
    if [ -z "$ib_tarball" ]; then
        log "ERROR: ImageBuilder tarball not found in build output"
        exit 1
    fi
    log "ImageBuilder tarball: $ib_tarball"

    # Build the ImageBuilder container
    log "Building container image: $IMAGEBUILDER_TAG"
    local build_dir="$CACHE_DIR/ib-container"
    rm -rf "$build_dir"
    mkdir -p "$build_dir"
    cp "$ib_tarball" "$build_dir/imagebuilder.tar.xz"

    cat > "$build_dir/Containerfile" <<'CEOF'
FROM docker.io/library/debian:bookworm-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gawk unzip file wget python3 python3-distutils \
        rsync libncurses-dev zlib1g-dev ca-certificates xz-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN useradd -m buildbot
COPY imagebuilder.tar.xz /tmp/
RUN mkdir /builder && \
    tar xf /tmp/imagebuilder.tar.xz -C /builder --strip-components=1 && \
    rm /tmp/imagebuilder.tar.xz && \
    chown -R buildbot:buildbot /builder
USER buildbot
WORKDIR /builder
CEOF

    # Build via Podman socket
    # We use curl against the Podman API since we're inside a container
    # and can't run podman CLI directly.
    cd "$build_dir"
    tar cf - Containerfile imagebuilder.tar.xz | \
        curl -s --unix-socket "$CONTAINER_SOCKET_PATH" \
            -X POST \
            -H "Content-Type: application/x-tar" \
            --data-binary @- \
            "http://d/v5.0.0/libpod/build?t=$IMAGEBUILDER_TAG&labels={\"$LABEL_KEY\":\"$commit\"}" \
            > /dev/null

    log "Container image built and tagged: $IMAGEBUILDER_TAG (commit: $commit)"
}

# --- Main ---

log "Checking ImageBuilder status for $IMAGEBUILDER_TAG"

REMOTE_COMMIT=$(get_remote_commit)
if [ -z "$REMOTE_COMMIT" ]; then
    log "ERROR: could not fetch remote commit from $OPENWRT_REPO ($OPENWRT_BRANCH)"
    exit 1
fi
log "Remote HEAD: $REMOTE_COMMIT"

BUILT_COMMIT=$(get_built_commit)
log "Built commit: ${BUILT_COMMIT:-<none>}"

if [ "$REMOTE_COMMIT" = "$BUILT_COMMIT" ]; then
    log "ImageBuilder is up-to-date, nothing to build"
    exit 0
fi

log "ImageBuilder is stale or missing, building..."
do_build "$REMOTE_COMMIT"
log "Done"
