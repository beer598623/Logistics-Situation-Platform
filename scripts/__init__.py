"""Executable entry points.

This is a package only so that one script can import another (for example
``scripts/review_decision.py`` reusing the import gates in
``scripts/import_review.py``) without duplicating logic. Every module here is
still runnable directly as ``python scripts/<name>.py``.
"""
