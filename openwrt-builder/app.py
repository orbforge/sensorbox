"""sensorbox custom ImageBuilder builder service.

Always-running API that builds OpenWrt ImageBuilder containers on
demand for devices needing custom kernel patches / DTS. Triggered
by the firmware-selector when a recipe references a custom_branch.

Endpoints:
    GET  /status/{branch}  — is the ImageBuilder ready?
    POST /build/{branch}   — trigger a build (if not already running)
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("openwrt-builder")

app = FastAPI(title="sensorbox OpenWrt Builder")

# Load builder configs from branches.yaml
BRANCHES_FILE = os.environ.get("BRANCHES_FILE", "/app/branches.yaml")
CONTAINER_SOCKET = os.environ.get("CONTAINER_SOCKET_PATH", "")
BASE_CONTAINER = os.environ.get("BASE_CONTAINER", "ghcr.io/openwrt/imagebuilder")
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")

branches_config = {}

# In-memory state for each branch
build_state = {}  # branch -> {status, commit, started_at, error, log_tail}


def load_branches():
    """Load custom branch configs from branches.yaml."""
    global branches_config
    try:
        with open(BRANCHES_FILE) as f:
            all_branches = yaml.safe_load(f) or {}
        # Only branches with builder config
        branches_config = {
            name: cfg for name, cfg in all_branches.items()
            if cfg.get("builder")
        }
        log.info(f"Loaded {len(branches_config)} builder-enabled branch(es): "
                 + ", ".join(branches_config.keys()))
    except FileNotFoundError:
        log.warning(f"Branches file not found: {BRANCHES_FILE}")


def get_container_tag(branch: str, target: str) -> str:
    """Compute the container tag ASU expects for this branch."""
    target_slug = target.replace("/", "-")
    return f"{BASE_CONTAINER}:{target_slug}-openwrt-{branch}"


def get_remote_commit(repo: str, branch: str) -> str:
    """Get the latest commit hash from the remote branch."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo, f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.split()[0]
    except Exception as e:
        log.error(f"Failed to get remote commit: {e}")
    return ""


def get_built_commit(tag: str) -> str:
    """Check if the ImageBuilder container exists and get its source commit."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--unix-socket", CONTAINER_SOCKET,
             f"http://d/v5.0.0/libpod/images/{tag}/json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            labels = data.get("Config", {}).get("Labels", {}) or {}
            return labels.get("org.orbforge.source-commit", "")
    except Exception:
        pass
    return ""


def run_build(branch: str):
    """Run the buildroot in a background thread."""
    cfg = branches_config.get(branch)
    if not cfg or not cfg.get("builder"):
        build_state[branch] = {"status": "error", "error": "No builder config"}
        return

    builder = cfg["builder"]
    repo = builder["repo"]
    git_branch = builder["branch"]
    target = builder["target"]
    defconfig = builder.get("defconfig", f"{branch}.defconfig")
    tag = get_container_tag(branch, target)

    build_state[branch] = {
        "status": "building",
        "started_at": time.time(),
        "commit": "",
        "error": None,
        "log_tail": "Starting build...",
    }

    try:
        # Get the commit we're building
        commit = get_remote_commit(repo, git_branch)
        build_state[branch]["commit"] = commit

        # Run build.sh with the right env vars
        env = {
            **os.environ,
            "OPENWRT_REPO": repo,
            "OPENWRT_BRANCH": git_branch,
            "OPENWRT_TARGET": target,
            "IMAGEBUILDER_TAG": tag,
            "CONTAINER_SOCKET_PATH": CONTAINER_SOCKET,
            "CACHE_DIR": CACHE_DIR,
            "DEFCONFIG": f"/builder-configs/{defconfig}",
            "SOURCE_COMMIT": commit,
        }

        process = subprocess.Popen(
            ["/app/build.sh"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Stream output, keep last few lines for status
        log_lines = []
        for line in process.stdout:
            line = line.rstrip()
            log_lines.append(line)
            if len(log_lines) > 20:
                log_lines.pop(0)
            build_state[branch]["log_tail"] = "\n".join(log_lines[-5:])
            log.info(f"[{branch}] {line}")

        process.wait()

        if process.returncode == 0:
            build_state[branch]["status"] = "ready"
            build_state[branch]["log_tail"] = "Build complete"
            log.info(f"Build complete for {branch} (commit {commit[:12]})")
        else:
            build_state[branch]["status"] = "error"
            build_state[branch]["error"] = f"Build failed with exit code {process.returncode}"
            build_state[branch]["log_tail"] = "\n".join(log_lines[-10:])
            log.error(f"Build failed for {branch}")

    except Exception as e:
        build_state[branch]["status"] = "error"
        build_state[branch]["error"] = str(e)
        log.exception(f"Build error for {branch}")


@app.on_event("startup")
def startup():
    load_branches()


@app.get("/status/{branch}")
def status(branch: str):
    if branch not in branches_config:
        raise HTTPException(404, f"Unknown branch: {branch}")

    cfg = branches_config[branch]
    builder = cfg.get("builder", {})
    target = builder.get("target", "")
    tag = get_container_tag(branch, target)

    # Check current state
    state = build_state.get(branch, {})
    if state.get("status") == "building":
        elapsed = int(time.time() - state.get("started_at", 0))
        return {
            "ready": False,
            "building": True,
            "elapsed_seconds": elapsed,
            "eta_minutes": max(0, 45 - elapsed // 60),
            "commit": state.get("commit", ""),
            "log_tail": state.get("log_tail", ""),
        }

    # Check if container exists and is up-to-date
    remote_commit = get_remote_commit(builder["repo"], builder["branch"])
    built_commit = get_built_commit(tag)

    ready = bool(built_commit) and built_commit == remote_commit

    return {
        "ready": ready,
        "building": False,
        "remote_commit": remote_commit,
        "built_commit": built_commit or None,
        "stale": bool(built_commit) and built_commit != remote_commit,
        "commit": built_commit or remote_commit,
    }


@app.post("/build/{branch}")
def trigger_build(branch: str):
    if branch not in branches_config:
        raise HTTPException(404, f"Unknown branch: {branch}")

    state = build_state.get(branch, {})
    if state.get("status") == "building":
        return {"status": "already_building", "message": "Build already in progress"}

    # Check if already up-to-date
    cfg = branches_config[branch]
    builder = cfg.get("builder", {})
    tag = get_container_tag(branch, builder.get("target", ""))
    remote_commit = get_remote_commit(builder["repo"], builder["branch"])
    built_commit = get_built_commit(tag)

    if built_commit and built_commit == remote_commit:
        return {"status": "up_to_date", "commit": built_commit}

    # Start build in background
    thread = threading.Thread(target=run_build, args=(branch,), daemon=True)
    thread.start()

    return {"status": "started", "commit": remote_commit}
