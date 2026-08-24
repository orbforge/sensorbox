#!/usr/bin/env python3
"""Build a recipe's image through the local ASU and report where it landed.

This is the "build" half of the loop; hwtest.py is the "flash and verify"
half:

    ./build.py --recipe radxa_e20c
    ./hwtest.py flash --image <path it prints>

Scope note: this sends the recipe's packages, repositories and signing keys,
but NOT its uci-defaults. Those are Mustache templates that the
firmware-selector renders against live form values (Wi-Fi credentials,
ORB_DEPLOYMENT_TOKEN, root password), and re-implementing that here would be
a second source of truth that could silently drift. So this validates the
image build -- version, package resolution, Orb feed, boot -- and NOT
credential injection. Use the selector UI for a build with real secrets.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPES = os.path.join(os.path.dirname(HERE), "recipes")


def log(msg):
    sys.stderr.write("[build] %s\n" % msg)
    sys.stderr.flush()


def api(url, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"detail": body}


def build_request(recipe_id):
    with open(os.path.join(RECIPES, "_common.yaml")) as fh:
        common = yaml.safe_load(fh)
    with open(os.path.join(RECIPES, "%s.yaml" % recipe_id)) as fh:
        recipe = yaml.safe_load(fh)

    keys = []
    for name in recipe.get("repository_keys", []):
        with open(os.path.join(RECIPES, "keys", name)) as fh:
            keys.append(fh.read())

    return recipe, {
        "distro": "openwrt",
        "version": recipe["version"],
        "target": recipe["target"],
        "profile": recipe["profile"],
        # Additions on top of the profile defaults, not a replacement set --
        # which is why diff_packages must stay false. With it true ASU treats
        # the list as a full override and strips base-files and much of
        # busybox out of the image.
        "packages": list(common.get("packages", [])) + list(recipe.get("packages", [])),
        "diff_packages": False,
        "repositories": recipe.get("repositories", {}),
        # Without "append" ASU replaces the stock OpenWrt feeds with just the
        # Orb one, and every standard package becomes unresolvable.
        "repositories_mode": "append",
        "repository_keys": keys,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recipe", default="radxa_e20c")
    p.add_argument("--asu", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=1800)
    a = p.parse_args()

    recipe, payload = build_request(a.recipe)
    log("%s -> openwrt %s  %s / %s"
        % (a.recipe, payload["version"], payload["target"], payload["profile"]))
    log("packages: %s" % " ".join(payload["packages"]))

    status, body = api(a.asu + "/api/v1/build", payload)
    request_hash = body.get("request_hash")
    if status >= 400 or not request_hash:
        sys.exit("build request rejected (HTTP %s): %s"
                 % (status, body.get("detail") or body))
    log("queued: %s" % request_hash)

    deadline = time.time() + a.timeout
    last = None
    while time.time() < deadline:
        status, body = api("%s/api/v1/build/%s" % (a.asu, request_hash))
        state = body.get("status") or body.get("detail")
        if state != last:
            log("status: %s" % state)
            last = state
        if status == 200 and body.get("image_prefix"):
            break
        if status >= 400 and state not in ("queued", "started"):
            sys.exit("build failed: %s\n%s"
                     % (state, (body.get("stderr") or "")[-2000:]))
        time.sleep(5)
    else:
        sys.exit("timed out after %ss" % a.timeout)

    bin_dir = body.get("bin_dir", "")
    store = os.path.join(os.path.dirname(HERE), "public", "store", bin_dir)
    log("build complete in %s" % store)

    images = [i for i in body.get("images", [])
              if i.get("type") in ("sysupgrade", "combined")]
    print()
    for img in images:
        print(os.path.join(store, img["name"]))
    if not images:
        print(json.dumps(body.get("images", []), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
