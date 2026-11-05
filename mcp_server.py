"""MCP server: the two-way channel between the AI and the cluster.

READS  the cluster through the read-only kubeconfig only (never the admin one).
WRITES only to eks-learnings.md (tacit memory). preferences.md stays human-owned.

Run by VS Code / Claude Code over stdio; you don't start it by hand.
Manual smoke test:  python mcp_server.py --check
"""
import functools
import json
import re
import sys
from datetime import date, datetime, timezone

from kubernetes import client, config as kconfig
from kubernetes.client.rest import ApiException
from urllib3.exceptions import HTTPError

import config

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server

server = Server(
    "k8s-local",
    instructions=(
        "Read-only access to the local 'eks-local' Kubernetes cluster. "
        "Always call get_context first and follow preferences.md. "
        "Check eks-learnings.md for a known pattern before diagnosing from scratch. "
        "After resolving a new issue, call record_learning."
    ),
)


# ---------- helpers ----------

def _api() -> client.ApiClient:
    # Loaded per call so a re-run of setup_readonly.py (new port/token) is picked up live.
    if not config.AI_KUBECONFIG.exists():
        raise RuntimeError("ai-readonly.yaml missing. Run: python setup_readonly.py")
    return kconfig.new_client_from_config(config_file=str(config.AI_KUBECONFIG))


def _safe(fn):
    """Turn API/connection failures into messages the AI can act on."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiException as e:
            if e.status == 401:
                return "Unauthorized: token expired. Ask the user to run: python setup_readonly.py"
            if e.status == 403:
                return f"Forbidden (read-only identity): {e.reason}. This is expected for writes and Secrets."
            if e.status == 404:
                return "Not found. Check the name and namespace."
            return f"Kubernetes API error {e.status}: {e.reason}"
        except RuntimeError as e:
            return str(e)
        except (HTTPError, OSError) as e:
            return (f"Cannot reach the cluster ({type(e).__name__}). Is minikube running? "
                    "Ask the user to run: python cluster.py up && python setup_readonly.py")
    return wrapper


def _age(ts) -> str:
    if not ts:
        return "-"
    secs = int((datetime.now(timezone.utc) - ts).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit}"
    return f"{secs}s"


def _container_state(cs) -> dict:
    out = {"name": cs.name, "ready": cs.ready, "restarts": cs.restart_count, "image": cs.image}
    if cs.state.waiting:
        out["state"] = f"Waiting: {cs.state.waiting.reason}"
    elif cs.state.terminated:
        out["state"] = f"Terminated: {cs.state.terminated.reason} (exit {cs.state.terminated.exit_code})"
    else:
        out["state"] = "Running"
    last = cs.last_state.terminated if cs.last_state else None
    if last:
        out["last_termination"] = f"{last.reason} (exit {last.exit_code}) {_age(last.finished_at)} ago"
    return out


# ---------- context layer ----------

@server.tool()
def get_context() -> str:
    """Return preferences.md (rules you must follow) and eks-learnings.md (known issues). Call this first."""
    prefs = config.PREFERENCES_FILE.read_text() if config.PREFERENCES_FILE.exists() else "(none)"
    learn = config.LEARNINGS_FILE.read_text() if config.LEARNINGS_FILE.exists() else "(none)"
    return f"# PREFERENCES (governance)\n{prefs}\n\n# LEARNINGS (known issues)\n{learn}"


@server.tool()
def record_learning(title: str, symptom: str, cause: str, fix: str) -> str:
    """Log a resolved issue to eks-learnings.md. If the title already exists, bump its 'Seen' count instead.
    Use a stable, specific title, e.g. 'OOMKilled: JVM heap >= container limit'."""
    path = config.LEARNINGS_FILE
    text = path.read_text() if path.exists() else "# EKS learnings\n"
    today = date.today().isoformat()

    header = re.compile(rf"^## {re.escape(title.strip())}\s*$", re.IGNORECASE | re.MULTILINE)
    match = header.search(text)
    if match:
        section_end = text.find("\n## ", match.end())
        section_end = len(text) if section_end == -1 else section_end
        section = text[match.start():section_end]
        seen = re.search(r"- Seen: (\d+)", section)
        count = int(seen.group(1)) + 1 if seen else 2
        new_section = re.sub(r"- Seen: .*", f"- Seen: {count} (last {today})", section) if seen \
            else section.rstrip() + f"\n- Seen: {count} (last {today})\n"
        path.write_text(text[:match.start()] + new_section + text[section_end:])
        return (f"Updated '{title}': seen {count} times. This mistake has repeated. "
                "Propose a rule for preferences.md to the user (do not edit it yourself).")

    entry = (f"\n## {title.strip()}\n- Symptom: {symptom}\n- Cause: {cause}\n"
             f"- Fix: {fix}\n- Seen: 1 (last {today})\n")
    path.write_text(text.rstrip() + "\n" + entry)
    return f"Recorded new learning '{title}'."


# ---------- cluster reads ----------

@server.tool()
@_safe
def list_pods(namespace: str = "default", all_namespaces: bool = False) -> str:
    """List pods with status, restarts, node and the reason for any failure."""
    core = client.CoreV1Api(_api())
    pods = (core.list_pod_for_all_namespaces() if all_namespaces
            else core.list_namespaced_pod(namespace)).items
    rows = []
    for p in pods:
        statuses = p.status.container_statuses or []
        problems = [s for s in (_container_state(c) for c in statuses) if s["state"] != "Running"]
        rows.append({
            "namespace": p.metadata.namespace, "name": p.metadata.name, "phase": p.status.phase,
            "ready": f"{sum(c.ready for c in statuses)}/{len(statuses)}",
            "restarts": sum(c.restart_count for c in statuses), "node": p.spec.node_name,
            "age": _age(p.metadata.creation_timestamp),
            **({"problems": problems} if problems else {}),
        })
    return json.dumps(rows, indent=1) if rows else f"No pods in {namespace}."


@server.tool()
@_safe
def describe_pod(name: str, namespace: str = "default") -> str:
    """Pod detail: container states, last termination, resource requests/limits, env-style JVM flags, conditions."""
    p = client.CoreV1Api(_api()).read_namespaced_pod(name, namespace)
    containers = []
    for c in p.spec.containers:
        jvm = [e.value for e in (c.env or []) if e.name in ("JAVA_OPTS", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS") and e.value]
        containers.append({
            "name": c.name, "image": c.image,
            "requests": (c.resources.requests or {}) if c.resources else {},
            "limits": (c.resources.limits or {}) if c.resources else {},
            "command": c.command, "args": c.args,
            **({"jvm_options": jvm} if jvm else {}),
            "liveness_probe": bool(c.liveness_probe), "readiness_probe": bool(c.readiness_probe),
        })
    return json.dumps({
        "name": p.metadata.name, "namespace": namespace, "node": p.spec.node_name,
        "phase": p.status.phase, "qos": p.status.qos_class, "labels": p.metadata.labels,
        "containers": containers,
        "status": [_container_state(c) for c in (p.status.container_statuses or [])],
        "conditions": [{"type": c.type, "status": c.status, "reason": c.reason}
                       for c in (p.status.conditions or [])],
    }, indent=1, default=str)


@server.tool()
@_safe
def get_pod_logs(name: str, namespace: str = "default", container: str | None = None,
                 previous: bool = False, tail_lines: int = 100) -> str:
    """Pod logs. Set previous=True to read the crashed container's logs after a restart."""
    logs = client.CoreV1Api(_api()).read_namespaced_pod_log(
        name, namespace, container=container, previous=previous,
        tail_lines=max(1, min(tail_lines, 500)))
    return logs or "(empty log: often means the process was killed before writing, e.g. OOMKilled)"


@server.tool()
@_safe
def get_events(namespace: str = "default", object_name: str | None = None) -> str:
    """Recent events (newest last), optionally for one object. Warnings explain most failures."""
    kwargs = {"field_selector": f"involvedObject.name={object_name}"} if object_name else {}
    items = client.CoreV1Api(_api()).list_namespaced_event(namespace, **kwargs).items
    items.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp)
    lines = [f"{_age(e.last_timestamp or e.event_time)} ago  {e.type:<7} {e.reason:<18} "
             f"{e.involved_object.kind}/{e.involved_object.name}: {e.message} (x{e.count or 1})"
             for e in items[-40:]]
    return "\n".join(lines) or "No events."


@server.tool()
@_safe
def list_deployments(namespace: str = "default") -> str:
    """Deployments with desired/ready replicas and images."""
    deps = client.AppsV1Api(_api()).list_namespaced_deployment(namespace).items
    if not deps:
        return f"No deployments in {namespace}."
    return json.dumps([{
        "name": d.metadata.name, "ready": f"{d.status.ready_replicas or 0}/{d.spec.replicas}",
        "images": [c.image for c in d.spec.template.spec.containers],
    } for d in deps], indent=1)


@server.tool()
@_safe
def top_pods(namespace: str = "default") -> str:
    """Live CPU/memory per pod (needs the metrics-server addon)."""
    data = client.CustomObjectsApi(_api()).list_namespaced_custom_object(
        "metrics.k8s.io", "v1beta1", namespace, "pods")
    items = data.get("items", [])
    if not items:
        return "No metrics yet (wait ~60s after pods start)."
    return json.dumps([{
        "pod": i["metadata"]["name"],
        "containers": {c["name"]: c["usage"] for c in i["containers"]},
    } for i in items], indent=1)


if __name__ == "__main__":
    if "--check" in sys.argv:
        print(list_pods(all_namespaces=True)[:2000])
    else:
        server.run()  # stdio
