# CSV series fixtures

**These files contain no real published statistics.** They are generated
deterministically by `scripts/generate_synthetic_fixtures.py` and every
observation derived from them carries
`evidence_class: "synthetic_test_fixture"`.

They exist because no source could be live-validated in the WO-010 execution
environment (see `docs/source_qualification_report.md`). Rather than invent
numbers and present them as real, the platform runs on labelled fixtures and
states on the Dashboard's face that live coverage is insufficient.

Deliberate gaps are built into several series so that the missing-is-not-zero
path is exercised by data rather than only by unit tests:

| Series | Missing periods |
|---|---|
| `export_value_med` | 2026-05, 2026-06 |
| `import_value_oceania` | 2026-06 |
| `thailand_lsci` | 2026-04, 2026-05, 2026-06 |

Regenerating the fixtures on a clean tree must be a no-op;
`tests/test_derived_outputs.py` asserts that.
