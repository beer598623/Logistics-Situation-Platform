# Returned ChatGPT assessments

Save the structured reply from a human-run ChatGPT review here as
`<package-id>.json`, matching `schemas/review_package_output.schema.json`.

This directory is empty by design. **No AI assessment has been produced or
approved under WO-010.** The workflow, its contracts and its rejection rules
are implemented and tested; producing an assessment requires a human to run a
package through ChatGPT out-of-band, which is outside what an automated
executor may do.

Nothing placed here is published. `scripts/import_review.py` validates it, and
`scripts/review_decision.py` records an explicit human approval or rejection
before anything reaches the Dashboard.
