# Ledgerline Hostinger release preparation

## Release controls

The Hostinger workflow deploys on every push to `main`, and also supports manual dispatch. Manual dispatch requires an exact commit equal to the dispatched `main` commit and the typed `DEPLOY` confirmation. The workflow builds the static marketing site, packages it as a run-scoped immutable GitHub Actions artifact, records a SHA-256 checksum, and then enters the GitHub `Production` environment before any SSH operation.

The `Production` environment is branch-restricted to `main`. No independent reviewer is configured, matching the last successful legacy deployment, which had no reviewer gate. The separate `rollback.yml` workflow remains manual-only and requires `RESTORE` plus a named backup.

**Current `main` is not safe to dispatch.** Its legacy `deploy.yml` uses `StrictHostKeyChecking=no`, appends `ssh-keyscan` output without pin validation, and recursively deletes most target contents before upload. PR #1 is being updated against `da53d33f8a5a33848594264b1a9190a6f3e4990f`; until that update is approved and merged, do not dispatch or enable either pipeline.

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

The historical website-specific package is dated 2026-10-10 and is not fresh enough for cutover. A new Hostinger site backup was created for the existing `quantumledgerlink.com` website at 2026-10-14 10:27 (hPanel local time), including website files and the selected database. The website files backup is now marked completed and prepared for download. The database backup is listed in the Restore and download panel. Download attempts surfaced a Hostinger network error, and no verified local copies were found; an off-panel rollback copy is therefore not confirmed. The domain-change dialog warns that existing website backups will be lost and cannot be restored after the change. The workflow's fresh pre-deployment snapshot is created only after cutover approval and exact target validation. It refuses to proceed if that archive contains symlinks or special files, because the current rollback workflow rejects them. Neither production workflow has been exercised against Hostinger.

## PR #1 update and merge-trigger safety (2026-10-14)

Existing PR #1 is updated and mergeable at head `171494aca9db4141f11117744ee68eeeb1de02fd`, based on current `main` (`da53d33f8a5a33848594264b1a9190a6f3e4990f`). The resolved change keeps the guarded Hostinger workflow, the manual rollback workflow, the read-only diagnostic workflow now present on `main`, and the intended marketing-site updates. The Azure Ledgerline product application is outside the PR change set.

The guarded workflow still listens for pushes to `main`, but its build and deploy jobs require `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=true`; automatic push deployment also requires `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`. Both variables were absent in the repository and Production environment at the latest check, and the owner confirmed neither exists at organization scope. Manual deployment also requires the exact dispatched main commit and typed `DEPLOY`. The push trigger now ignores workflow-only paths, which prevents a workflow-only update from starting this workflow. A merge containing website files will match the trigger, but the workflow version attached to the resulting merge commit will evaluate the gates and skip both jobs while the variables remain unset. This is why the guard must be present in the merge commit before the application changes are merged.

The update is not merged or dispatched. Current-main push run `38514892297` failed at `Validate Hostinger secrets`; all SSH setup, backup, target cleanup, upload, and verification steps were skipped. No Hostinger connection or deployment occurred. The revised branch passed YAML parsing, embedded Bash syntax checks, `git diff --check`, and `npm run build`; Vercel Preview checks passed. The repository defines no test or lint scripts. Vite emitted its existing warning that the main JavaScript chunk exceeds 500 kB.

## Direct production deployment limits

- **Local production build:** current main `5b5f91e` was built previously in a separate detached worktree. The updated PR tree was rebuilt after `npm ci` during this reconciliation; Vite succeeded and reported the main JavaScript chunk exceeds 500 kB. The build output is local only and has not been uploaded or deployed.

- **Deployment Portal rollout completed (2026-10-14):** `Ramhighvolt/highvolt-deploy-portal` PR #1 merged reviewed commit `4cfe179cbeee68767194e7fe4e771d24c4e3b042` as `05929bc60c9f500720a489facac8fab442c6ec99`. Vercel production deployment `2ALFTyp8WhpiY3HnNEm54EXEmVzw` is Ready on `main` and serves `webdeployment.highvolt.tech`. The authenticated Microsoft Entra operator session loaded successfully. Existing HVA Website, Quantum Agent, and Quantum EduPass mappings and their deployment history remained visible. The live Ledgerline status/history route returned GitHub Actions history for `HighVolt-Analytics/Ledgerline`; the Ledgerline Deploy action remains disabled. GitHub ran only the portal validation workflow; no Hostinger website deployment was triggered. No DNS, Hostinger setting, or production website file was changed. The pre-rollout Vercel production deployment (`185eac40add1c21cd6c3bf3d00b70d5978012287`, deployment `DZxe7Zd1kmuemXLqoJJW5x8A3rjf`) remains Ready, and its Vercel action menu offers Instant Rollback and Promote. This rollback path was inspected but not executed.
- At the latest read-only GitHub configuration check, repository-level Ledgerline cutover variables were absent; Hostinger secrets and target variables were also absent from the repository and its `Production` environment. The organization administrator manually confirmed there are no organization Actions variables, including either cutover gate. The portal's own Ledgerline dispatch control remains disabled. Required Hostinger credentials and target settings must only be added after separate approval and verified target-path classification.
- Read-only hPanel inspection found `quantumledgerlink.com` is the existing Business Web Hosting site and `quantumledgerline.com` is already connected to it as a parked domain. The plan shows 7 of 50 websites and expires 2027-01-21; the plan's other sites must remain untouched. The selected site's subdomain screen showed no entries. The owner manually confirmed the domains have no Hostinger mailboxes, the old domain has no email forwarding or subdomains, and the new domain has no mailboxes. GoDaddy DNS for the new domain already points to Hostinger at `92.113.28.62`. A fresh site backup completed at 2026-10-14 10:27 local hPanel time; files are prepared for download and the database backup is listed for download. Hostinger returned a network error during download attempts, so off-panel copies are not verified.
- Hostinger guidance and the actual hPanel dialog say the existing-site domain change removes associated subdomains and deletes Hostinger backup history so those backups cannot be restored after the change. The exact current dialog was opened but not submitted. See [Connecting a different domain to your existing website](https://support.hostinger.com/en/articles/6807580-connecting-a-different-domain-to-an-existing-website). This hPanel session is delegated admin access; changes apply to the account owner, so owner approval is required.
- No new Ledgerline production dispatch was made during this portal rollout or PR reconciliation.
- No live website files, databases, domains, DNS, credentials, or deployment settings have been changed. Only the requested site-specific backup was created; both backup components still need verified off-panel copies before any domain change.
- Both domains currently resolve to the same Hostinger endpoint and pass HTTPS checks while the new domain is still a parked alias. DNS/SSL after primary-domain change, ownership, mailbox dependencies, and the post-change document root remain unverified. The current legacy response returns 404 for `/interactive-tour`, `/resources`, `robots.txt`, and `sitemap.xml`; the Ledgerline build includes these routes and files.
- The target suffix must be confirmed after the Hostinger domain change before configuring the workflow.
- The upload overlays files without deletion. This reduces the chance of destroying persistent content but can leave stale hashed assets.
- The workflow attempts to restore the pre-deployment snapshot if any step after the snapshot fails. The separate manual rollback workflow is also available after the cutover gate is enabled. Both restore paths remain unverified against Hostinger and require a valid, link-free snapshot.
