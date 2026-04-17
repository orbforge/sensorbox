#!/bin/sh
# Runs the OpenWrt buildroot and produces an ImageBuilder container.
# Called by app.py with environment variables set:
#   OPENWRT_REPO, OPENWRT_BRANCH, OPENWRT_TARGET, IMAGEBUILDER_TAG,
#   CONTAINER_SOCKET_PATH, CACHE_DIR, DEFCONFIG, SOURCE_COMMIT

set -eu

log() { echo "[build.sh] $*"; }

log "Building ImageBuilder from $OPENWRT_REPO@$OPENWRT_BRANCH"
log "Target: $OPENWRT_TARGET"
log "Tag: $IMAGEBUILDER_TAG"
log "Commit: $SOURCE_COMMIT"

# Clone or update the source tree
if [ -d "$CACHE_DIR/openwrt/.git" ]; then
    log "Updating existing clone..."
    cd "$CACHE_DIR/openwrt"
    git fetch origin "$OPENWRT_BRANCH"
    git checkout "origin/$OPENWRT_BRANCH"
else
    log "Cloning $OPENWRT_REPO ($OPENWRT_BRANCH)..."
    git clone --branch "$OPENWRT_BRANCH" --single-branch \
        "$OPENWRT_REPO" "$CACHE_DIR/openwrt"
    cd "$CACHE_DIR/openwrt"
fi

log "Updating feeds..."
./scripts/feeds update -a
./scripts/feeds install -a

# Apply the defconfig
if [ -f "$DEFCONFIG" ]; then
    cp "$DEFCONFIG" .config
    make defconfig
elif [ ! -f .config ]; then
    log "ERROR: no .config or defconfig found at $DEFCONFIG"
    exit 1
fi

log "Starting build (this takes ~45 minutes)..."
export FORCE_UNSAFE_CONFIGURE=1
# IGNORE_ERRORS=1 continues past ALL build failures including boot
# packages. The rockchip/armv8 target builds u-boot for ALL board
# variants, and unrelated ones (e.g. sige7-rk3588) may fail without
# affecting our target device's ImageBuilder.
make -j"$(nproc)" IGNORE_ERRORS=1 V=s || true

# Find the ImageBuilder tarball
IB_TARBALL=$(find bin/targets -name 'openwrt-imagebuilder-*.tar.xz' | head -1)
if [ -z "$IB_TARBALL" ]; then
    log "ERROR: ImageBuilder tarball not found in build output"
    exit 1
fi
log "ImageBuilder tarball: $IB_TARBALL"

# Build the ImageBuilder container via Podman API
log "Building container image: $IMAGEBUILDER_TAG"
BUILD_DIR="$CACHE_DIR/ib-container"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp "$IB_TARBALL" "$BUILD_DIR/imagebuilder.tar.xz"

cat > "$BUILD_DIR/Containerfile" <<'CEOF'
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

# Build via Podman API
LABEL_KEY="org.orbforge.source-commit"
cd "$BUILD_DIR"
tar cf context.tar Containerfile imagebuilder.tar.xz

# URL-encode the tag and label
ENCODED_TAG=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$IMAGEBUILDER_TAG', safe=''))")
ENCODED_LABELS=$(python3 -c "import urllib.parse, json; print(urllib.parse.quote(json.dumps({'$LABEL_KEY': '$SOURCE_COMMIT'})))")

curl -s --unix-socket "$CONTAINER_SOCKET_PATH" \
    -X POST \
    -H "Content-Type: application/x-tar" \
    --data-binary @context.tar \
    "http://d/v5.0.0/libpod/build?t=${ENCODED_TAG}&labels=${ENCODED_LABELS}" \
    > /dev/null 2>&1

log "Container image built: $IMAGEBUILDER_TAG (commit: $SOURCE_COMMIT)"
