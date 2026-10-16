# Ledgerline production operations

**Last checked:** 15 October 2026

**Production:** <https://quantumledgerline.com>

**Portal:** <https://webdeployment.highvolt.tech>

## Current production state

- Source: `HighVolt-Analytics/Ledgerline`, branch `main`.
- Current `main` and live marker: `e6dfad3ef6ee4812f9891bc1096e043bab6938d6`.
- Latest successful automatic release: [Actions run 38704396028](https://github.com/HighVolt-Analytics/Ledgerline/actions/runs/38704396028), triggered by a push to `main`.
- Hostinger document root: `/home/u359614291/domains/quantumledgerline.com/public_html`.
- Freshness check: the marker, homepage, SPA routes, Spectra page/image, `robots.txt`, and `sitemap.xml` returned HTTP 200. The latest automatic run verified all 56 release-file hashes at the target and passed public health checks.
- Hostinger `Production` environment is restricted to `main`. `Validate Ledgerline marketing site` is the required PR check; `main` requires PRs and blocks force pushes/deletion. No approval-count requirement is configured.

Recheck the `main` SHA and live marker before every manual release. A prepared SHA is no longer valid for dispatch if `main` has moved.

## Deployment policy

`.github/workflows/deploy.yml` is the only active Ledgerline production deployment workflow.

- Push deployment matches only the approved marketing-site paths on `main` and requires repository variable `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=true`. Feature branches and pull requests do not deploy.
- Manual dispatch requires `ref=main`, `release_commit` equal to the dispatched/current `main` SHA, and `confirm_production=DEPLOY`. It additionally requires either `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=true` (temporary operator gate) or `LEDGERLINE_PORTAL_DISPATCH_ENABLED=true` (portal gate). Manual gates do not authorize push deployments.
- The automatic gate is currently `true`; the manual cutover gate is `false`.
- Production SSH uses strict host-key checking. The workflow resolves the target and requires the exact canonical Ledgerline root above. It serializes runs and does not cancel an in-progress deployment.

### Portal dispatch state

The live Vercel project `highvolt-deploy-portal` is connected to `Ramhighvolt/highvolt-deploy-portal` on production `main`. The portal maps website ID `quantum-ledgerline` to `HighVolt-Analytics/Ledgerline`, `main`, and `deploy.yml`. At this check the authenticated dashboard reported the matching successful release and showed recent successful and failed deployment history. Entra sign-in and allowlist authorization are enforced server-side; mutating requests require same-origin checks and fixed server-side project routing. The GitHub token is loaded from a server-only module and is not returned to clients.

Portal dispatch is currently **disabled**: `LEDGERLINE_PORTAL_DISPATCH_ENABLED` is absent from the Vercel Production variables and the Ledgerline repository variables. The Ledgerline cutover gate remains false. The Vercel project also lists `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED`; the portal code does not use that variable as its dispatch gate. Its value has not been revealed or changed.

To run the separately approved one-time portal test, temporarily set `LEDGERLINE_PORTAL_DISPATCH_ENABLED=true` in both Vercel Production and the Ledgerline repository, and redeploy the portal so Vercel applies the setting. Keep `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=false` and automatic deployment `true`. Dispatch only the exact current `main` SHA with `DEPLOY`; monitor the Actions result and marker. Then unset or set both portal gates to `false`, redeploy the portal to apply the closed state, and verify both gates are closed. Do not perform this sequence without explicit approval.

Prepared test (revalidate immediately before approval/dispatch): repository `HighVolt-Analytics/Ledgerline`, workflow `deploy.yml`, ref `main`, `release_commit=e6dfad3ef6ee4812f9891bc1096e043bab6938d6`, `confirm_production=DEPLOY`. This repeats the current release to test the portal path and creates a new pre-deployment backup; it is not needed for website release freshness.

## Backup, verification, and rollback

Before overlaying a release, `deploy.yml` saves a website-specific archive under the account's private `deployment_backups/ledgerline-production` directory. It validates the archive, records a SHA-256 and the pre-deployment file manifest/marker, and fails before upload if the snapshot cannot be validated. The deployment overlays only the verified document root and checks the full release manifest over SSH. Public checks verify the release marker, exact homepage/SPA response hashes, static JavaScript/CSS hashes and MIME types, robots, sitemap, and Spectra route. Any failure after a valid snapshot invokes the staged rollback; the snapshot is validated and extracted into staging before the site is swapped, then the restored manifest and marker are checked.

The separate manual `.github/workflows/rollback.yml` requires `main`, `confirm_restore=RESTORE`, the temporary cutover gate, and an exact backup filename. It checks archive paths/types, snapshots the current site, restores the selected archive, and checks the restored index/marker. Unlike automatic rollback, it does not compare the selected archive to a recorded checksum and manifest before replacement. Before using it, independently verify the website-specific archive hash, marker, and contents, and obtain explicit approval. Never use an account-wide archive or restore over unrelated websites.

### Emergency pause

1. Set repository variable `LEDGERLINE_AUTOMATIC_DEPLOY_ENABLED=false` (or unset it) to stop future push-triggered deployments.
2. Keep `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED=false`.
3. Keep the portal Vercel and Ledgerline repository `LEDGERLINE_PORTAL_DISPATCH_ENABLED` gates unset/false. A Vercel variable change requires a new Vercel deployment to take effect.
4. Confirm there are no already queued or running production jobs. Do not cancel an active release until its outcome and rollback state are known.

## Notifications and credentials

The deploy notification job uses Microsoft Graph through GitHub OIDC, not a mailbox password or long-lived client secret. The configured notification sender is `support@highvolt.tech`; recipient is `alerts@highvolt.tech`. Success and failure messages include the release outcome and rollback status. Graph application mail permission is scoped to the approved sender mailbox. The simulated success and failure smoke test and subsequent production notification jobs succeeded.

Hostinger SSH credentials are stored in the Ledgerline GitHub `Production` environment; values and private keys must never be copied into this document, source, chat, or logs. Rotate a key by registering a new public key with Hostinger first, validating SSH access, updating the protected GitHub secret, and only then retiring the old key. Graph OIDC/Exchange permissions are owned by the Microsoft 365/Entra administrator; do not widen the mailbox scope as part of key rotation.

## Domain isolation and legacy workflows

`quantumledgerline.com` is independent in application content: its canonical and Open Graph URLs, robots, and sitemap use the new domain; the current application source/public tree has no `quantumledgerlink.com` references. The production root, route checks, marker, and asset requests use only the new domain. The new domain's HTTPS requests validate successfully. Static external references are to Fontshare, Google Fonts, and Supademo; none point to the old domain. The marketing SPA has no application sign-in or callback routes; Microsoft Entra authentication belongs to the Deployment Portal.

Do not redirect, forward, alias, proxy, or canonicalize the old domain to the new one. Preserve its registration and DNS records until a separate retirement decision. Current DNS lookups returned A records for both domains to the Hostinger endpoint and no CNAME; this shared hosting IP does not itself indicate a DNS forwarding rule. `http://quantumledgerlink.com/` returned 403 without a `Location` redirect. The old domain's HTTPS handshake failed, so its HTTPS redirect/certificate behavior could not be inspected. Do not bypass reputation filtering; recheck only if the owner approves a supported remediation.

In `HighVolt-Analytics/Quantum-Ledgerlink`, workflow ID `297418439` (`deploy.yml`, Deploy Ledgerline to Hostinger) remains disabled manually. Its read-only diagnostic remains active. **The old repository's rollback workflow is still active** and its code targets the new Ledgerline document root; if configured and its cutover gate is enabled, it could replace that root. At this check, the old repository has no deployment variables and no `Production` environment, so its rollback fails closed before SSH. Treat this as a latent cross-repository write path; obtain separate approval before disabling that workflow. Do not delete its repository, credentials, backup history, or domain records as part of this handover.

## Handover status

- Ledgerline production and automatic deployment are live and verified.
- Portal history is current; portal dispatch remains disabled pending its separately approved one-time test.
- The active legacy rollback workflow and the old domain's unavailable HTTPS response remain documented items for separate owner decisions.
- The next HighVolt application requires a separate discovery: purpose, domain/DNS ownership, repository/branch, architecture, data/storage, hosting, secrets, auth, TLS, CI/CD, monitoring, backups/rollback, staging/production, and acceptance/security checks. Do not infer Ledgerline's architecture or provision infrastructure for it without a separate scope and approval.
