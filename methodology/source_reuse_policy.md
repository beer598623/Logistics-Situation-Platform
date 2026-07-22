# Public-source access and reuse policy

## Purpose

This policy governs collection of public information for the Logistics Situation Platform. Public
availability does not automatically grant unrestricted copying, redistribution, or commercial reuse.

## Rules

1. A source contract must record its owner, access method, expected cadence, licence review state,
   terms URL when available, and known limitations.
2. Live collection remains disabled until the endpoint, parser fixture, and reuse position have been
   reviewed.
3. The repository stores structured facts, metadata, short analyst-written summaries, hashes, and
   source links. It does not republish full articles or full reports unless the licence explicitly
   permits that use and the project records the decision.
4. Raw snapshots, when retained for reproducibility, must use a documented retention period and must
   not be published automatically.
5. Robots, rate limits, authentication requirements, and source terms must be respected.
6. A source outage or licence uncertainty must be shown as a gap; missing information must not be
   represented as zero or as an all-clear condition.
7. Vendor material is labelled as a vendor claim until independent evidence supports an operational
   result.
8. Source terms and endpoints must be re-reviewed after material source changes and at least annually.

## Publication controls

- Facts retain a source URL, publication date, retrieval time, content hash, parser version, and
  limitation.
- A source marked `restricted` cannot feed public dashboard content.
- A source marked `pending_review` can be researched manually but cannot be enabled as an automated
  collector.
- Machine-readable status must be `verified` before an adapter is enabled.
