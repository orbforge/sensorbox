#!/bin/sh
# Copies recipes from the read-only source bind mount into a writable
# location inside the container, then generates a small index.json so
# the firmware-selector JS can enumerate them without a directory listing.
#
# Executed by the nginx:alpine image's /docker-entrypoint.sh before nginx
# starts, via a bind mount at /docker-entrypoint.d/. Files landing under
# /orb-recipes/ are served by nginx at /recipes/ (see selector/nginx.conf).

set -e

SRC=/orb-recipes-src
DST=/orb-recipes

mkdir -p "$DST"
cp -r "$SRC"/. "$DST"/

cd "$DST"

# Build a JSON object: common pre-amble + list of device recipe filenames
# (everything with a .yaml extension, excluding the leading-underscore
# conventions like _common.yaml).
recipe_names=$(ls *.yaml 2>/dev/null | grep -v '^_' | sed 's/.*/"&"/' | paste -sd, -)
printf '{"common":"_common.yaml","recipes":[%s]}\n' "${recipe_names:-}" > index.json

echo "generate-recipes-index: wrote $DST/index.json with recipes=[${recipe_names:-}]"
