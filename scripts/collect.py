#!/usr/bin/env python3
"""Collector placeholder for Implementation v0.1.

Live sources are intentionally disabled until source-specific parsers and
licensing checks are implemented. This script verifies that the collector
entry point is operational without changing published data.
"""
import argparse
from datetime import datetime, timezone

p=argparse.ArgumentParser()
p.add_argument("--dry-run",action="store_true")
args=p.parse_args()
print({"status":"dry_run" if args.dry_run else "disabled","checked_at":datetime.now(timezone.utc).isoformat()})
