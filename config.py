"""Shared settings for the local EKS-style lab. Edit here, not in each script."""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# minikube cluster
PROFILE = "eks-local"
NODES = 2
CPUS = 2
MEMORY_MB = 3072
ADDONS = ["metrics-server", "ingress"]

# Admin kubeconfig (written by minikube) and the AI's read-only kubeconfig
ADMIN_KUBECONFIG = Path.home() / ".kube" / "config"
AI_KUBECONFIG = Path.home() / ".kube" / "ai-readonly.yaml"

# Read-only identity for the AI
AI_NAMESPACE = "ai-system"
AI_SERVICE_ACCOUNT = "ai-readonly"
AI_TOKEN_HOURS = 720  # 30 days

# Memory layers
PREFERENCES_FILE = PROJECT_DIR / "preferences.md"
LEARNINGS_FILE = PROJECT_DIR / "eks-learnings.md"
