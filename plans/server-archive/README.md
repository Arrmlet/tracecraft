# Server scaffolding — archived 2026-05-18

Originally drafted for the gnosis-track FastAPI+Postgres+SeaweedFS+Redis architecture
in `plans/tracecraft-blueprint-v2.md`. Not imported by the shipped SDK at any point;
moved here so reviewers don't mistake it for the product.

If/when a managed-coordination server makes sense, restart from this code rather than
greenfield. Until then it's reference, not surface area.

Removed from build:
- `tracecraft_server.egg-info/` (build artifact)
- `**/__pycache__/` (compiled cache)
