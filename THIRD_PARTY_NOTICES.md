# Third-party notices

Implementation v0.1.1 does not copy source code from the reference repositories used during research.
Design patterns were studied independently and reimplemented for this project.

Runtime and development dependencies retain their own licences:

- jsonschema — MIT
- PyYAML — MIT
- defusedxml — Python Software Foundation License
- DuckDB — MIT (added by WO-010; used only to build the derived, gitignored analytical warehouse)
- pytest — MIT
- Ruff — MIT
- pre-commit — MIT

The published Dashboard loads no third-party JavaScript, stylesheet, font or image. It is
self-contained static HTML, CSS and vanilla JavaScript authored in this repository, so no
external library licence applies to it.

Public data and source notices are governed separately from this software licence. Their access,
reuse, attribution, and limitations are recorded in `config/sources.yaml` and
`methodology/source_reuse_policy.md`.
