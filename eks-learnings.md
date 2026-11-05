# EKS learnings

Tacit memory. The AI appends here via record_learning; I review it in git.
A "Seen: 2" entry means the mistake repeated, so promote it to a rule in preferences.md.

## OOMKilled: JVM heap (-Xmx) exceeds container memory limit
- Symptom: Pod repeatedly OOMKilled (exit 137), restarts climbing. JVM never throws OutOfMemoryError — kernel kills the container before the heap limit is reached.
- Cause: -Xmx is set higher than the container's limits.memory. The JVM heap ceiling exceeds the cgroup limit, so the kernel OOM-killer intervenes first.
- Fix: Replace fixed -Xmx with -XX:MaxRAMPercentage=75 so the heap is always a fraction of the container limit. Also ensure the app does not hold unbounded references (memory leak). Verify with: kubectl get pod -w and check restarts stop climbing.
- Seen: 2 (last 2026-11-05)
