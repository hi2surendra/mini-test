"""Start / stop / inspect the local minikube cluster from Python.

Usage:
    python cluster.py up       # create or resume the cluster + enable addons
    python cluster.py status
    python cluster.py down     # stop (keeps state, frees RAM)
    python cluster.py delete   # remove the cluster completely
"""
import json
import os
import shutil
import subprocess
import sys

import config


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(args))
    # Never let a work KUBECONFIG leak in: minikube writes to ~/.kube/config only.
    env = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}
    return subprocess.run(args, check=check, env=env)


def require(tool: str) -> None:
    if not shutil.which(tool):
        sys.exit(f"'{tool}' not found on PATH. Install it with: brew install {tool}")


def docker_running() -> bool:
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def profile_exists() -> bool:
    out = subprocess.run(["minikube", "profile", "list", "-o", "json"], capture_output=True, text=True)
    try:
        return any(p.get("Name") == config.PROFILE for p in json.loads(out.stdout).get("valid", []))
    except (json.JSONDecodeError, AttributeError):
        return False


def up() -> None:
    require("minikube")
    require("docker")
    if not docker_running():
        sys.exit("Docker is not running. Start Docker Desktop (open -a Docker) and retry.")
    if profile_exists():
        run("minikube", "start", "-p", config.PROFILE)  # resume with its existing size
    else:
        run(
            "minikube", "start", "-p", config.PROFILE, "--driver=docker",
            f"--nodes={config.NODES}", f"--cpus={config.CPUS}", f"--memory={config.MEMORY_MB}",
        )
    for addon in config.ADDONS:
        run("minikube", "addons", "enable", addon, "-p", config.PROFILE)
    print("\nCluster is up. Next: python setup_readonly.py")


def status() -> None:
    run("minikube", "status", "-p", config.PROFILE, check=False)


def down() -> None:
    run("minikube", "stop", "-p", config.PROFILE)


def delete() -> None:
    run("minikube", "delete", "-p", config.PROFILE)


if __name__ == "__main__":
    actions = {"up": up, "status": status, "down": down, "delete": delete}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        sys.exit(__doc__)
    actions[sys.argv[1]]()
