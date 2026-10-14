# Ledgerline Hostinger release preparation

## Release controls

The Hostinger workflow preserves the legacy `push` to `main` trigger and manual dispatch. Both require the `main` ref and the repository variable `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=true`. Automatic pushes additionally require `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`; both variables are unset/false by default, so merging workflow files cannot deploy. Manual dispatch additionally requires an exact commit equal to the dispatched `main` commit and the typed `DEPLOY` confirmation. The workflow builds the static marketing site, packages it as a run-scoped immutable GitHub Actions artifact, records a SHA-256 checksum, and then enters the GitHub `Production` environment before any SSH operation.

The `Production` environment is branch-restricted to `main`. No independent reviewer is configured, matching the last successful legacy deployment, which had no reviewer gate. The separate `rollback.yml` workflow remains manual-only and requires `RESTORE` plus a named backup.

No staging website will be created. This is **WAIVED BY OWNER — DIRECT PRODUCTION MIGRATION**. Direct production deployment has greater risk because the build will not have been exercised against an isolated Hostinger site.

## Production configuration required after explicit cutover approval

Configure values only after the domain change has been separately approved and the new document root has been verified. Do not reuse legacy deployment secrets or target values without review.

Production secrets:

- `HOSTINGER_HOST`
- `HOSTINGER_PORT`
- `HOSTINGER_USERNAME`
- `HOSTINGER_SSH_KEY` — dedicated Ledgerline key preferred
- `HOSTINGER_KNOWN_HOSTS` — the accepted host key, using strict SSH verification

Repository-level release gates (leave unset or `false` until separately approved):

- `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED` - enables the manual production path after the owner approves cutover
- `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED` - separately enables deployments on pushes to `main`

Production environment variables:

- `HOSTINGER_TARGET_PATH` - exact canonical document root after Hostinger's domain change
- `HOSTINGER_TARGET_SUFFIX` - must be the verified domain root suffix `/domains/quantumledgerline.com/public_html` or `/public_html`
- `HOSTINGER_PUBLIC_URL` - exactly `https://quantumledgerline.com`

The workflow resolves the configured target with `realpath -e` and requires an exact match between the canonical target and the SSH home plus the approved suffix. It creates a private, timestamped snapshot of the target before overlaying the release. It does not recursively delete files, so unrelated and persistent files are preserved; old hashed assets can remain after a release.

## Application and data scope

The Ledgerline `main` application is a Vite-built static site. Source inspection found no server API routes, database client, or submitted form handler. The pricing region helper optionally calls `https://ipapi.co/json/`, falls back to AUD on errors, and stores a currency selection in `sessionStorage`. Demo media and fonts load from external providers. This is evidence that the repository build is database-independent; it does not prove the existing Hostinger document root has no PHP files, uploads, or other persistent application data.

The 6.4 GB Hostinger website archive is account-wide and was previously structurally validated. It must not be restored wholesale. Filename-only mapping identified a 57-member subtree for the old domain's `public_html`: 51 regular files and six directories, with no links or special files. The files are static HTML/CSS/JS/image/SVG/TXT types; no PHP, SQL, JSON, or environment-named files were identified in that subtree. The separate 26 KB SQL export has 11 table definitions and has not been attributed to the marketing website. A website-scoped package was prepared from this historical subtree and passed a local extraction-and-file-hash round trip. No configuration content was opened, and nothing was restored to Hostinger.

The historical website-specific package is dated 2026-10-10 and is not fresh enough for cutover. The workflow's fresh pre-deployment snapshot is created only after cutover approval and exact target validation. It refuses to proceed if that archive contains symlinks or special files, because the current rollback workflow rejects them. Neither production workflow has been exercised against Hostinger.

## Direct production deployment limits

- No production dispatch has been made.
- No Hostinger files, databases, domains, DNS, credentials, or deployment settings have been changed.
- Both domains currently resolve to the same Hostinger endpoint and pass HTTPS checks while the new domain is still a parked alias. DNS/SSL after primary-domain change, ownership, mailbox dependencies, and the post-change document root remain unverified. The current legacy response returns 404 for `/interactive-tour`, `/resources`, `robots.txt`, and `sitemap.xml`; the Ledgerline build includes these routes and files.
- The target suffix must be confirmed after the Hostinger domain change before configuring the workflow.
- The upload overlays files without deletion. This reduces the chance of destroying persistent content but can leave stale hashed assets.
- The workflow attempts to restore the pre-deployment snapshot if any step after the snapshot fails. The separate manual rollback workflow is also available after the cutover gate is enabled. Both restore paths remain unverified against Hostinger and require a valid, link-free snapshot.
