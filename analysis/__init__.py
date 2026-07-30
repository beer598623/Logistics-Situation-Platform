"""Deterministic Logistics analysis layer.

Everything in this package is pure computation over version-controlled records:
no network access, no AI call, no hidden weighting. The separation is
deliberate -- thresholds and directions produced here are *not* AI
interpretation, and AI interpretation (``analysis.review_package``) never
recomputes an indicator. A reviewer can therefore check any published
direction against a documented rule ID without re-running a model.
"""
