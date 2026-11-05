# eks-local: AI-assisted Kubernetes lab (Python + VS Code)

Four layers, all in this folder:

| Layer | File |
|---|---|
| Structured state | the minikube cluster + manifests in `demo/` (later: your GitOps repo) |
| Two-way channel | `mcp_server.py`: reads the cluster read-only, writes only to `eks-learnings.md` |
| Governance | `preferences.md` (human-owned) + `setup_readonly.py` (RBAC `view` role) |
| Tacit memory | `eks-learnings.md` (AI-maintained, reviewed in git) |

## One-time setup (VS Code terminal)

```bash
cd ~/sbsa/aws-cdk/cdk-python/mini-test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
git init && git add . && git commit -m "eks-local lab"
```

## Every session

```bash
python cluster.py up          # start minikube + addons
python setup_readonly.py      # refresh the AI's read-only kubeconfig (port can change after restart)
python mcp_server.py --check  # optional: prove the AI identity can list pods
```

Then use the AI in VS Code:
- **Copilot Chat (Agent mode)**: picks up `.vscode/mcp.json`. Click Start on `k8s-local` if prompted.
- **Claude Code extension**: picks up `.mcp.json`. Approve the `k8s-local` server once.

## Test the learning loop

```bash
kubectl apply -f demo/oom-java.yaml
```
Ask: "Why is memory-hog crashing in the default namespace?"
The AI should find OOMKilled (exit 137), see -Xmx400m > 256Mi limit, propose a fix, and call `record_learning`.
Break it again later and it should cite the learning instead of starting over.

Clean up: `kubectl delete -f demo/oom-java.yaml` and `python cluster.py down`.
