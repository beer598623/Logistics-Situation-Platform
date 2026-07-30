# Security policy

## Supported versions

This project has not yet cut a tagged release. Security fixes are applied to `main` only.
Once released versions exist, this section will list which lines receive fixes.

## Reporting a vulnerability

Please report suspected security issues privately, using
[GitHub private security advisories](https://github.com/beer598623/Logistics-Situation-Platform/security/advisories/new)
for this repository. This requires no shared credential or mailbox and keeps the report out
of the public issue tracker until a fix is available.

Please do not open a public issue for a suspected vulnerability.

Include, where possible: the affected file(s) or workflow, the conditions needed to trigger
the issue, and what you observed versus what you expected. There is no bug-bounty program;
reports are handled on a best-effort basis.

## What is, and is not, in scope

This is a public-data logistics-intelligence platform, not a service that holds user
accounts, sessions, or private company data (see
[`docs/security_and_privacy_boundary.md`](docs/security_and_privacy_boundary.md) §6). The
security-relevant surface is narrow:

- **`collectors/http_client.py`** — the bounded fetch transport used by every collector
  adapter: no-redirect discovery transport, DNS-pinned candidate transport with fail-closed
  rejection of non-global addresses, response size and content-type bounds.
- **`.github/workflows/manual-live-source-test.yml`** — the one path in this repository
  authorized to make a live outbound request, `workflow_dispatch` only, human-triggered.
- **The public Dashboard** (`dashboard/public/`) — loads no external JavaScript, stylesheet,
  font, or image; a test asserts the only absolute URL on the page is the repository link.
- **Data-contract validation** (`scripts/validate.py`, `schemas/`) — the fail-closed gate that
  every published record must pass.

Out of scope: findings that require a source's own machine-readable feed to be enabled and
live (none is — every source in `config/sources.yaml` carries `enabled: false`), and reports
about the absence of a feature that is explicitly listed as a known limitation in
`docs/known_data_gaps.md`.

## Credentials

No credential exists in this repository, and none is required to build, validate, test, or
publish anything (`docs/security_and_privacy_boundary.md` §5). If you find a committed
secret, key, or token, please report it as above rather than opening a public issue.

## Dependencies

Runtime dependencies are pinned in `requirements.lock` and recorded in
`THIRD_PARTY_NOTICES.md`. If you find a vulnerable dependency version in use, a private report
is still the fastest path — please include the advisory identifier if you have one.
