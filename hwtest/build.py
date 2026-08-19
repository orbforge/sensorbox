#!/usr/bin/env python3
"""Build a recipe's image through the local ASU and report where it landed.

This is the "build" half of the loop; hwtest.py is the "flash and verify"
half:

    ./build.py --recipe radxa_e20c
    ./hwtest.py flash --image <path it prints>

With --form it produces exactly what the web form produces, including
uci-defaults. The templating is not re-implemented: render_defaults.mjs
imports the selector's own mergedPackages() and assembleDefaults() and runs
them under Node with the same vendored Mustache, so this cannot drift from
the UI. That makes form-driven features testable end to end -- root password,
Wi-Fi credentials and band policy, ORB_DEPLOYMENT_TOKEN, ttylogin, and the
option-gated template sections.

Without --form no defaults are sent at all, which produces an UNHARDENED
image: no ttylogin and no root password, so its serial console drops straight
to a root shell. Fine for validating a build, wrong for anything else.

The form file holds real secrets. Keep it out of the repo.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPES = os.path.join(os.path.dirname(HERE), "recipes")
# Absolute path: a login shell's command hash can be stale right after nodejs
# is installed, so "node" may not resolve even with /usr/bin on PATH.
NODE = os.environ.get("NODE", "/usr/bin/node")


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


def render_via_selector(recipe, common, form):
    """Get packages and uci-defaults from the selector's own JS."""
    job = {
        "recipe": recipe,
        "common": common,
        "formValues": form.get("formValues", {}),
        "selectedOptions": form.get("selectedOptions", {}),
        "extraDefaults": form.get("extraDefaults", "") or "",
    }
    proc = subprocess.run(
        [NODE, os.path.join(HERE, "render_defaults.mjs")],
        input=json.dumps(job), capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit("render_defaults.mjs failed:\n%s" % proc.stderr.strip())
    return json.loads(proc.stdout)


def autofill_form(recipe, form, keys):
    """Fill in the form values the UI derives rather than asks for.

    The selector computes these from the recipe and from the key files it
    fetched, so a hand-written form file should not have to repeat them.
    """
    values = dict(form.get("formValues", {}))

    # _common.yaml uses orb_apk_key to persist the Orb feed on the device so
    # orb-update can fetch new versions at runtime. The UI passes the contents
    # of the first repository_keys entry.
    if keys and "orb_apk_key" not in values:
        values["orb_apk_key"] = keys[0].strip()

    # The install_* values mirror the recipe's `install` block, and only apply
    # when the user ticks "Install to eMMC".
    install = recipe.get("install") or {}
    if values.get("install_to_emmc"):
        for field in ("sd_device", "emmc_device", "size_from_partition", "status_led"):
            key = "install_%s" % field
            if field in install and key not in values:
                values[key] = install[field]

    form = dict(form)
    form["formValues"] = values
    return form


# These additions live in sensorbox-main.js's buildRequest() rather than in
# mergedPackages(), so they are the ONE piece of selector logic mirrored here
# instead of imported. Keep in sync with buildRequest().
TOGGLE_PACKAGES = (
    ("telemetry_enabled", ["telegraf-full"]),
    ("tailscale_enabled", ["tailscale"]),
    # scandump implies docker in the UI: dockerEnabled = docker_enabled || scandumpEnabled
    ("docker_enabled", ["dockerd", "docker", "docker-compose"]),
    ("scandump_enabled", ["dockerd", "docker", "docker-compose"]),
)


def toggle_packages(values):
    out = []
    for key, pkgs in TOGGLE_PACKAGES:
        if values.get(key):
            out += [p for p in pkgs if p not in out]
    return out


def build_request(recipe_id, form=None):
    with open(os.path.join(RECIPES, "_common.yaml")) as fh:
        common = yaml.safe_load(fh)
    with open(os.path.join(RECIPES, "%s.yaml" % recipe_id)) as fh:
        recipe = yaml.safe_load(fh)

    keys = []
    for name in recipe.get("repository_keys", []):
        with open(os.path.join(RECIPES, "keys", name)) as fh:
            keys.append(fh.read())

    packages = list(common.get("packages", [])) + list(recipe.get("packages", []))
    defaults = None
    if form is not None:
        form = autofill_form(recipe, form, keys)
        rendered = render_via_selector(recipe, common, form)
        packages = rendered["packages"] + toggle_packages(form["formValues"])
        defaults = rendered["defaults"]
        log("rendered defaults: %d bytes (mustache %s)"
            % (len(defaults), rendered.get("mustacheVersion")))
        if "{{" in defaults:
            sys.exit("defaults still contain unrendered Mustache tags")
    else:
        log("no --form: sending NO uci-defaults (image will be unhardened)")

    request = {
        "distro": "openwrt",
        "version": recipe["version"],
        "target": recipe["target"],
        "profile": recipe["profile"],
        # Additions on top of the profile defaults, not a replacement set --
        # which is why diff_packages must stay false. With it true ASU treats
        # the list as a full override and strips base-files and much of
        # busybox out of the image.
        "packages": packages,
        "diff_packages": False,
        "repositories": recipe.get("repositories", {}),
        # Without "append" ASU replaces the stock OpenWrt feeds with just the
        # Orb one, and every standard package becomes unresolvable.
        "repositories_mode": "append",
        "repository_keys": keys,
    }
    if defaults:
        # ASU needs ALLOW_DEFAULTS=1 in its env to accept this at all, and
        # caps it at max_defaults_length (20480 by default).
        request["defaults"] = defaults
    return recipe, request


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recipe", default="radxa_e20c")
    p.add_argument("--form", metavar="FILE",
                   help="YAML/JSON of form values, to build exactly what the "
                        "web form would (including uci-defaults). Holds "
                        "secrets -- keep it out of the repo.")
    p.add_argument("--asu", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=float, default=1800)
    a = p.parse_args()

    form = None
    if a.form:
        with open(a.form) as fh:
            form = yaml.safe_load(fh) or {}
    recipe, payload = build_request(a.recipe, form)
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
