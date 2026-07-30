# Deployment verification

**Work Order:** WO-014 · **Status:** implemented

This document records what was actually verified about this repository's live deployment,
as opposed to what the workflow files merely claim to do. Every fact below was checked, not
assumed, during WO-014.

## 1. GitHub Pages is genuinely live

Pages is served from the **GitHub Actions artifact pipeline**, not from a `gh-pages` branch.
`git ls-remote` / the repository's branch list carries no `gh-pages` branch; the deployment
mechanism is `.github/workflows/deploy-pages.yml`, which builds `dashboard/public` and
publishes it via `actions/upload-pages-artifact@v5` + `actions/deploy-pages@v5` under the
`github-pages` environment.

The most recent `deploy-pages.yml` run's log records:

```
Created deployment for <commit sha>, ID: <commit sha>
Getting Pages deployment status...
Reported success!
Evaluated environment url: https://beer598623.github.io/Logistics-Situation-Platform/
```

The published site is **https://beer598623.github.io/Logistics-Situation-Platform/**.

## 2. The deploy pipeline fails closed

`deploy-pages.yml`'s `build` job runs `scripts/validate.py` and
`scripts/run_historical_validation.py` before `scripts/build_dashboard.py`, and the Pages
upload only happens after a successful build. If any step fails, the job stops and nothing is
uploaded — the previously published site stays live. This was true before WO-014 and is
unchanged by it; see `docs/operations_runbook.md` §4 ("A generator fails").

## 3. What WO-014 added: verifying the *published* site, not just the build inputs

Before WO-014, `health-check.yml` checked that committed files existed and parsed as JSON —
it never checked that the actually-published URL was reachable or serving the expected
content. A build could succeed and deploy while the CDN, DNS, or Pages service itself had an
unrelated problem, and nothing would notice.

`health-check.yml` now:

- Runs **daily** (was weekly), plus `workflow_dispatch`.
- Fetches `https://beer598623.github.io/Logistics-Situation-Platform/` directly, requires
  HTTP 200, and requires the response body to contain the page's own `<h1>` text ("Thailand
  Ocean Logistics Intelligence") as a content marker — catching both total unreachability and
  a Pages deployment that "succeeded" but served something unexpected.
- On any failure (file check, JSON syntax, or liveness), opens a GitHub issue titled
  `[Automated] Repository health check failed` linking the run, or comments on that issue if
  it is already open (deduplicated by exact title match, not GitHub's fuzzy search, to avoid
  false matches).
- On the next successful run, comments on and closes that issue automatically if it is still
  open.

This closes the "a scheduled failure was silent" gap the production-readiness roadmap audit
found: a failure now produces a persistent, visible record instead of only a red run in the
Actions tab that nobody was necessarily watching.

## 4. What is still not covered

- No paid uptime/monitoring service and no external status page. The daily check is the only
  liveness signal, and its floor is a 24-hour detection window.
- No alerting beyond the GitHub issue itself (no email/Slack/pager integration). Whoever
  watches this repository's issues is the alerting channel.
- No synthetic check of Dashboard *interactivity* (JavaScript execution, data fetches from
  the page) — only that the HTML document itself is reachable and contains the expected
  marker. `dashboard/public/assets/app.js` fetching `dashboard/public/data/*.json` client-side
  is exercised by `tests/test_dashboard_build.py` and the CI build step, not by this check.

See `docs/operations_runbook.md` for the rollback procedure and incident-response section
this Work Order also adds.
