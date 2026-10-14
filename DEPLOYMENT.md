# Ledgerline Hostinger release preparation

## Release controls

The current `main` workflow is manual-only after PR #5. This branch prepares the proposed steady-state workflow: approved `main` changes to the marketing site may deploy only when `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`; manual runs require an exact current `main` commit, typed `DEPLOY`, and either the temporary cutover gate or the independent portal dispatch gate. Push events can never use the manual gates. Workflow-only changes are excluded from the production push path filter. The workflow packages an immutable run artifact with SHA-256 and enters the GitHub `Production` environment before SSH operations.

The `Production` environment is branch-restricted to `main`. No independent reviewer is configured, matching the last successful legacy deployment, which had no reviewer gate. The separate `rollback.yml` workflow remains manual-only and requires `RESTORE` plus a named backup.

**Verified live baseline (2026-10-14):** production serves `31f80592b385eabfc559e12b23e52d3b9da9b811`; `main` was `12239682c245f2f52688bb0aa31b69edac27a909` at the start of this work. The `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED` repository variable is `false`; `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED` and `LEDGERLINE_PORTAL_DISPATCH_ENABLED` are unset. This proposed PR does not change any gate, credential, Hostinger setting, or production file. Its merge changes only workflow, helper, test, and documentation paths excluded from the deployment push filter.

No staging website will be created. This is **WAIVED BY OWNER — DIRECT PRODUCTION MIGRATION**. Direct production deployment has greater risk because the build will not have been exercised against an isolated Hostinger site.

## Verified Production configuration

The Hostinger `Production` environment is restricted to `main`, and its SSH/target settings are already configured for the verified canonical document root. Do not change those values as part of this automation PR. The SMTP secret names below are not configured in Ledgerline yet; add them only after the existing provider and approved recipient are confirmed through the official GitHub environment UI.

Production secrets:

- `HOSTINGER_HOST`
- `HOSTINGER_PORT`
- `HOSTINGER_USERNAME`
- `HOSTINGER_SSH_KEY` — dedicated Ledgerline key preferred
- `HOSTINGER_KNOWN_HOSTS` — the accepted host key, using strict SSH verification

Repository-level release gates (leave unset or `false` until separately approved):

- `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED` - temporary migration/manual deployment gate
- `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED` - separately enables marketing-source deployments on pushes to `main`
- `LEDGERLINE_PORTAL_DISPATCH_ENABLED` - steady-state independent manual dispatch gate; set in both the Ledgerline repository and live Vercel project only after approval

Production environment variables:

- `HOSTINGER_TARGET_PATH` - exact canonical document root after Hostinger's domain change
- `HOSTINGER_TARGET_SUFFIX` - must be the verified domain root suffix `/domains/quantumledgerline.com/public_html` or `/public_html`
- `HOSTINGER_PUBLIC_URL` - exactly `https://quantumledgerline.com`

The workflow resolves the configured target with `realpath -e` and requires an exact match between the canonical target and the SSH home plus the approved suffix. It creates a private, timestamped snapshot of the target before overlaying the release. It does not recursively delete files, so unrelated and persistent files are preserved; old hashed assets can remain after a release.

Production notification uses the existing SMTP integration pattern from the disabled legacy deployment, with values provisioned separately in the Ledgerline `Production` environment. Required secret names are `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, and `MAIL_TO`. The workflow checks for all of them before its first SSH operation. A separate final notification job sends one success or failure message after each authorized attempt; SMTP delivery errors are reported in the run summary and do not conceal deployment/rollback results. Secret values and recipients are never written to logs. Do not copy a recipient or credential until the existing provider and approved recipient have been confirmed.

## Proposed developer and operator flow

1. Open a PR for marketing-site changes; the required `Validate Ledgerline marketing site` check runs locked install, policy tests, and a production build.
2. Merge through the protected `main` branch after the required check passes. No review-count requirement is proposed.
3. Automatic production deployment occurs only if the merged change touches the explicit marketing build paths and `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`. It does not use either manual gate.
4. An authorized operator can request a manual deployment in the live portal by entering the exact `main` SHA and `DEPLOY`. Portal server auth, email allowlist, same-origin check, fixed repository routing, and `LEDGERLINE_PORTAL_DISPATCH_ENABLED` remain required. The GitHub workflow additionally requires the portal/cutover gate and Production environment branch restriction.
5. Check the marker at `https://quantumledgerline.com/deploy-info.txt` before saying a release is live. The portal reports the run URL, commit, health status and failure/rollback classification from Actions job steps.

Pause automatic deployment by setting `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=false` or unsetting it. Pause portal dispatch by disabling the server-side `LEDGERLINE_PORTAL_DISPATCH_ENABLED` variable in both Vercel production and the Ledgerline repository. A rollback remains a separate manually dispatched workflow requiring a named backup, `RESTORE`, and the cutover gate. Production secrets and SMTP settings are changed through GitHub's official environment settings, never chat.

## Application and data scope

> **Historical preparation notes below** record the earlier cutover stage and should not be read as current status. The verified live baseline is above; production is now live on Ledgerline.

The Ledgerline `main` application is a Vite-built static site. Source inspection found no server API routes, database client, or submitted form handler. The pricing region helper optionally calls `https://ipapi.co/json/`, falls back to AUD on errors, and stores a currency selection in `sessionStorage`. Demo media and fonts load from external providers. This is evidence that the repository build is database-independent; it does not prove the existing Hostinger document root has no PHP files, uploads, or other persistent application data.

The 6.4 GB Hostinger website archive is account-wide and was previously structurally validated. It must not be restored wholesale. Filename-only mapping identified a 57-member subtree for the old domain's `public_html`: 51 regular files and six directories, with no links or special files. The files are static HTML/CSS/JS/image/SVG/TXT types; no PHP, SQL, JSON, or environment-named files were identified in that subtree. The separate 26 KB SQL export has 11 table definitions and has not been attributed to the marketing website. A website-scoped package was prepared from this historical subtree and passed a local extraction-and-file-hash round trip. No configuration content was opened, and nothing was restored to Hostinger.

The historical website-specific package is dated 2026-10-10 and is not fresh enough for cutover. A new Hostinger site backup was created for the existing `quantumledgerlink.com` website at 2026-10-14 10:27 (hPanel local time), including website files and the selected database. The website files backup is now marked completed and prepared for download. The database backup is listed in the Restore and download panel. Download attempts surfaced a Hostinger network error, and no verified local copies were found; an off-panel rollback copy is therefore not confirmed. The domain-change dialog warns that existing website backups will be lost and cannot be restored after the change. The workflow's fresh pre-deployment snapshot is created only after cutover approval and exact target validation. It refuses to proceed if that archive contains symlinks or special files, because the current rollback workflow rejects them. Neither production workflow has been exercised against Hostinger.

## Historical PR #1 update and merge-trigger safety (2026-10-14)

Existing PR #1 is updated and mergeable at head `171494aca9db4141f11117744ee68eeeb1de02fd`, based on current `main` (`da53d33f8a5a33848594264b1a9190a6f3e4990f`). The resolved change keeps the guarded Hostinger workflow, the manual rollback workflow, the read-only diagnostic workflow now present on `main`, and the intended marketing-site updates. The Azure Ledgerline product application is outside the PR change set.

The guarded workflow still listens for pushes to `main`, but its build and deploy jobs require `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=true`; automatic push deployment also requires `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`. Both variables were absent in the repository and Production environment at the latest check, and the owner confirmed neither exists at organization scope. Manual deployment also requires the exact dispatched main commit and typed `DEPLOY`. The push trigger now ignores workflow-only paths, which prevents a workflow-only update from starting this workflow. A merge containing website files will match the trigger, but the workflow version attached to the resulting merge commit will evaluate the gates and skip both jobs while the variables remain unset. This is why the guard must be present in the merge commit before the application changes are merged.

The update is not merged or dispatched. Current-main push run `38514892297` failed at `Validate Hostinger secrets`; all SSH setup, backup, target cleanup, upload, and verification steps were skipped. No Hostinger connection or deployment occurred. The revised branch passed YAML parsing, embedded Bash syntax checks, `git diff --check`, and `npm run build`; Vercel Preview checks passed. The repository defines no test or lint scripts. Vite emitted its existing warning that the main JavaScript chunk exceeds 500 kB.

## Historical direct production deployment limits

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
