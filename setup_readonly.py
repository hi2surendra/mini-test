"""Create the AI's read-only identity and write its own kubeconfig.

Governance layer: the AI only ever gets ~/.kube/ai-readonly.yaml, bound to the
built-in 'view' ClusterRole (read pods/logs/events/deployments; no Secrets, no writes).

Safe to re-run. Re-run it after `minikube stop/start` if the API port changed,
or when the token expires.
"""
import base64
import sys

import yaml
from kubernetes import client, config as kconfig
from kubernetes.client.rest import ApiException

import config


def admin_client() -> client.ApiClient:
    if not config.ADMIN_KUBECONFIG.exists():
        sys.exit(f"{config.ADMIN_KUBECONFIG} not found. Run: python cluster.py up")
    return kconfig.new_client_from_config(
        config_file=str(config.ADMIN_KUBECONFIG), context=config.PROFILE
    )


def ignore_exists(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except ApiException as e:
        if e.status != 409:  # 409 = already exists
            raise


def create_identity(api: client.ApiClient) -> None:
    core = client.CoreV1Api(api)
    rbac = client.RbacAuthorizationV1Api(api)

    ignore_exists(core.create_namespace,
                  client.V1Namespace(metadata=client.V1ObjectMeta(name=config.AI_NAMESPACE)))
    ignore_exists(core.create_namespaced_service_account, config.AI_NAMESPACE,
                  client.V1ServiceAccount(metadata=client.V1ObjectMeta(name=config.AI_SERVICE_ACCOUNT)))
    ignore_exists(rbac.create_cluster_role_binding, client.V1ClusterRoleBinding(
        metadata=client.V1ObjectMeta(name=config.AI_SERVICE_ACCOUNT),
        role_ref=client.V1RoleRef(api_group="rbac.authorization.k8s.io",
                                  kind="ClusterRole", name="view"),
        subjects=[client.RbacV1Subject(kind="ServiceAccount", name=config.AI_SERVICE_ACCOUNT,
                                       namespace=config.AI_NAMESPACE)],
    ))
    print(f"Service account {config.AI_NAMESPACE}/{config.AI_SERVICE_ACCOUNT} bound to ClusterRole 'view'")


def issue_token(api: client.ApiClient) -> str:
    req = client.AuthenticationV1TokenRequest(
        spec=client.V1TokenRequestSpec(audiences=[],
                                       expiration_seconds=config.AI_TOKEN_HOURS * 3600))
    resp = client.CoreV1Api(api).create_namespaced_service_account_token(
        config.AI_SERVICE_ACCOUNT, config.AI_NAMESPACE, req)
    return resp.status.token


def write_kubeconfig(api: client.ApiClient, token: str) -> None:
    server = api.configuration.host
    with open(api.configuration.ssl_ca_cert, "rb") as f:
        ca_b64 = base64.b64encode(f.read()).decode()

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": config.PROFILE,
                      "cluster": {"server": server, "certificate-authority-data": ca_b64}}],
        "users": [{"name": config.AI_SERVICE_ACCOUNT, "user": {"token": token}}],
        "contexts": [{"name": "ai", "context": {"cluster": config.PROFILE,
                                                 "user": config.AI_SERVICE_ACCOUNT}}],
        "current-context": "ai",
    }
    config.AI_KUBECONFIG.parent.mkdir(parents=True, exist_ok=True)
    config.AI_KUBECONFIG.write_text(yaml.safe_dump(kubeconfig, sort_keys=False))
    config.AI_KUBECONFIG.chmod(0o600)
    print(f"Wrote {config.AI_KUBECONFIG} (server {server}, token valid {config.AI_TOKEN_HOURS}h)")


def verify() -> bool:
    """Prove the AI identity can read but not write or see Secrets."""
    api = kconfig.new_client_from_config(config_file=str(config.AI_KUBECONFIG))
    authz = client.AuthorizationV1Api(api)

    def can(verb: str, resource: str, sub: str | None = None) -> bool:
        review = client.V1SelfSubjectAccessReview(spec=client.V1SelfSubjectAccessReviewSpec(
            resource_attributes=client.V1ResourceAttributes(verb=verb, resource=resource,
                                                            subresource=sub)))
        return authz.create_self_subject_access_review(review).status.allowed

    checks = [
        ("list pods", can("list", "pods"), True),
        ("read pod logs", can("get", "pods", "log"), True),
        ("list events", can("list", "events"), True),
        ("delete pods", can("delete", "pods"), False),
        ("create deployments", can("create", "deployments"), False),
        ("read secrets", can("get", "secrets"), False),
    ]
    ok = True
    print("\nPermission check for the AI identity:")
    for label, actual, expected in checks:
        mark = "PASS" if actual == expected else "FAIL"
        ok &= actual == expected
        print(f"  [{mark}] {label:<20} allowed={actual}")
    return ok


if __name__ == "__main__":
    api = admin_client()
    create_identity(api)
    write_kubeconfig(api, issue_token(api))
    if verify():
        print("\nRead-only identity ready. Next: open this folder in VS Code; the MCP server starts from .vscode/mcp.json")
    else:
        sys.exit("\nPermission check failed. Do not hand this kubeconfig to the AI.")
