"""Teach upstream ASU about sensorbox's custom branches (branches.yaml).

Python imports this module automatically at interpreter start because
compose.yaml puts this directory on PYTHONPATH for asu-server and asu-worker.
It changes ASU's behaviour in memory only; the upstream image and its source
stay untouched, as GOALS.md requires.

Upstream ASU declares a `branches_file` setting but never reads it, and even
with the branch defined it cannot build one whose ImageBuilder exists only
locally:

  - Versions, targets and profiles are validated against
    downloads.openwrt.org, which knows nothing about e.g. `zero2`.
  - The worker always pulls the ImageBuilder from ghcr.io first, and a tag
    that only openwrt-builder produced fails with ImageNotFound.

So for each branch in BRANCHES_FILE this:

  1. merges it into settings.branches;
  2. lists its name as a version;
  3. answers target/profile lookups from branches.yaml (`builder.target`,
     `arch`, `profiles`) instead of fetching upstream metadata;
  4. falls back to the local image when ghcr.io doesn't have that branch's
     ImageBuilder tag. Stock branches still always pull.

Everything is patched before ASU's own modules import these names, which is
why this must run as sitecustomize rather than later. If anything here fails
the process exits: running ASU half-patched would reject custom branches with
misleading upstream errors.
"""

import importlib.util
import os
import sys


def _install(branches_file):
    import yaml
    from podman import errors
    from podman.domain.images_manager import ImagesManager

    from asu import util
    from asu.config import settings

    with open(branches_file) as fh:
        custom = yaml.safe_load(fh) or {}

    for name, branch in custom.items():
        branch.setdefault("enabled", True)
        branch.setdefault("snapshot", False)
        branch.setdefault("path", "releases/{version}")
        branch.setdefault("path_packages", "DEPRECATED")
        branch.setdefault("package_changes", [])
        if not branch.get("builder", {}).get("target") or not branch.get("arch"):
            raise ValueError(f"{name}: needs builder.target and arch")
        if not branch.get("profiles"):
            raise ValueError(f"{name}: needs a profiles list")
        settings.branches[name] = branch

    def custom_branch(version):
        name = util.get_branch(version)["name"]
        return custom.get(name)

    orig_reload_versions = util.reload_versions

    def reload_versions(app):
        changed = orig_reload_versions(app)
        # Upstream appends "<branch>-SNAPSHOT" for every branch. For a custom
        # branch that would select the setup.sh download path, which has
        # nothing to download, so offer only the bare name.
        app.versions[:] = [v for v in app.versions if v.removesuffix("-SNAPSHOT") not in custom]
        for name, branch in custom.items():
            if branch["enabled"]:
                app.versions.append(name)
        return changed

    orig_reload_targets = util.reload_targets

    def reload_targets(app, version):
        branch = custom_branch(version)
        if branch is None:
            return orig_reload_targets(app, version)
        app.targets[version] = {branch["builder"]["target"]: branch["arch"]}
        return True

    orig_reload_profiles = util.reload_profiles

    def reload_profiles(app, version, target):
        branch = custom_branch(version)
        if branch is None:
            return orig_reload_profiles(app, version, target)
        app.profiles[version][target] = (
            {p: p for p in branch["profiles"]}
            if target == branch["builder"]["target"]
            else {}
        )
        return True

    util.reload_versions = reload_versions
    util.reload_targets = reload_targets
    util.reload_profiles = reload_profiles

    local_tags = tuple("-" + util.get_container_version_tag(name) for name in custom)
    orig_pull = ImagesManager.pull

    def pull(self, repository, *args, **kwargs):
        try:
            return orig_pull(self, repository, *args, **kwargs)
        except errors.ImageNotFound:
            if repository.endswith(local_tags) and self.exists(repository):
                return self.get(repository)
            raise

    ImagesManager.pull = pull


_branches_file = os.environ.get("BRANCHES_FILE")
# PYTHONPATH reaches every interpreter in the container, including the
# isolated environment `uv run` builds the asu package in, which has none of
# ASU's dependencies (and its own VIRTUAL_ENV, so that can't tell them
# apart). podman-py is a hard ASU runtime dependency and never in a build
# environment, so it marks ASU's own venv.
_in_asu_venv = importlib.util.find_spec("podman") is not None
if _branches_file and _in_asu_venv:
    try:
        _install(_branches_file)
    except Exception as exc:
        # site.py would print this and carry on with an unpatched ASU.
        sys.stderr.write(f"sensorbox asu-shim: {exc!r}\n")
        raise SystemExit(1)
