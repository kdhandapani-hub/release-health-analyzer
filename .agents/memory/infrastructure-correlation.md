---
name: Infrastructure correlation
description: Preserve the established root-cause trigger and clearance logic when reporting infrastructure events.
---

Keep infrastructure symptom/isolated-event classification separate from the established root-cause trigger attribution and change-clearance logic. On Oct 9, DBPATCH-1009 must remain the likely trigger; infrastructure is a later symptom.

**Why:** the user explicitly required the existing trigger attribution to remain unchanged when adding the infrastructure lane.

**How to apply:** when modifying correlation analysis, report infrastructure episodes and their relationship to existing layer breaches without allowing infra-only events to replace the established trigger or alter clearance results, unless the user explicitly asks for that behavior to change.
