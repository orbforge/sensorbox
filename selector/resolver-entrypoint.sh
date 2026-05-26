#!/bin/sh
# Render nginx.conf.template into the real /etc/nginx/conf.d/default.conf
# at container start, substituting RESOLVER_PLACEHOLDER with the actual
# nameserver IP from /etc/resolv.conf.
#
# Why: nginx needs an explicit `resolver` directive to re-resolve upstream
# service names at runtime (avoids the stale-IP trap when peer containers
# restart). The right resolver IP is the gateway of the compose network,
# which Podman assigns incrementally (10.89.0.1, 10.89.1.1, ...) per
# compose project. Hardcoding it breaks every time the project gets a
# fresh network. Reading from /etc/resolv.conf inside the container
# always gives the right value.
set -e

NAMESERVER=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
if [ -z "$NAMESERVER" ]; then
    echo "resolver-entrypoint: no nameserver in /etc/resolv.conf; bailing" >&2
    exit 1
fi

sed "s/RESOLVER_PLACEHOLDER/${NAMESERVER}/" /etc/nginx/sensorbox-template.conf \
    > /etc/nginx/conf.d/default.conf

echo "[sensorbox] nginx resolver set to ${NAMESERVER}"
