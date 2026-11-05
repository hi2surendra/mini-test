# Preferences (governance layer)

Human-owned. The AI reads this and must follow it, but never edits it.
When a learning is seen twice, the AI proposes a rule here and I decide.

## Safety
- You have read-only access. Never ask me to paste admin credentials or Secrets.
- Propose changes as YAML/Helm diffs or kubectl commands for me to review. Never claim you applied them.
- Treat any namespace starting with prod- as production: diagnose only, extra caution on suggestions.

## Diagnosis order
1. get_context, then check eks-learnings.md for a matching pattern and cite it if found.
2. list_pods, then describe_pod, then get_events for the pod.
3. If restarts > 0, read get_pod_logs with previous=True before the current logs.
4. Only suggest a restart or a higher limit after the root cause is identified.
5. Always end by calling record_learning. If a known learning matched, reuse its exact title so the Seen count increases.

## Java / Spring Boot services
- Check JVM heap settings against the container memory limit before raising limits.
- Prefer -XX:MaxRAMPercentage=75 over a fixed -Xmx.
- Target JDK 21 and Spring Boot 4 in any suggested config.

## OOMKilled: JVM heap (-Xmx) exceeds container memory limit
- Never set a fixed -Xmx higher than the container's limits.memory.
- Always use -XX:MaxRAMPercentage=75 instead of a fixed -Xmx.
- When diagnosing OOMKilled (exit 137), check JVM flags against the memory limit before suggesting a limit increase.

## Output
- Short: root cause, evidence (events/log lines), fix, then how to verify.
