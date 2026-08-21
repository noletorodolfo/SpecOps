# Kubernetes Operational Patterns (CKA summary)
- Always set resource requests/limits on every container; without them the scheduler can't reason about bin-packing and a single pod can starve the node.
- Liveness vs readiness: liveness restarts a stuck container, readiness removes it from the Service endpoint list without restarting — mixing these up causes restart loops on slow-starting apps.
- Use Deployments for stateless workloads (rolling updates, replica management) and StatefulSets only when you actually need stable network identity or ordered startup/shutdown.
- Practical note: `kubeval`/`kustomize build` in CI catches schema errors, but not policy errors (e.g. missing resource limits) — that needs a second pass (OPA/kyverno) if it matters for the feature.
