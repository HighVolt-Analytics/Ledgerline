# Hostinger deployment setup

The Hostinger workflow is manual-only and accepts a `target` input. It has no push trigger. The default is `staging`; the staging job uses the `Staging` GitHub environment. The production job is skipped unless the repository variable `LEDGERLINE_PRODUCTION_CUTOVER_ENABLED` is exactly `true` and the run targets `main`. Do not set that variable until production cutover has separate approval and the `Production` environment has required reviewers and branch restrictions.

## Per-environment configuration

Create separate `Staging` and `Production` environments. Populate each environment independently; do not copy a production private key or target into staging.

Required environment secrets:

- `HOSTINGER_HOST`
- `HOSTINGER_PORT`
- `HOSTINGER_USERNAME`
- `HOSTINGER_SSH_KEY`
- `HOSTINGER_KNOWN_HOSTS` — exact known-hosts record for the verified SSH host key; SSH uses strict host-key checking.

Required environment variables:

- `HOSTINGER_TARGET_PATH` — absolute path for that environment. The workflow resolves it remotely and refuses `/`, the SSH home itself, paths outside the SSH home, and dot path components.
- `HOSTINGER_PUBLIC_URL` — exact HTTPS origin for that environment.
- `HOSTINGER_EXPECTED_DOMAIN` — hostname that must match the public URL and is written to the deployment marker.

Do not configure these until Hostinger has provisioned and independently verified a staging hostname and document root. A distinct URL alone does not prove the filesystem path is isolated. Prefer staging-only SSH access restricted to its document root. The existing production path must never be reused for staging.

## Deployment behavior and current limits

Each deployment builds the site, verifies configuration and strict SSH host identity, checks that the canonical destination is a directory below the SSH home, creates a timestamped backup under `~/deployment_backups/ledgerline-{target}`, uploads the build without a broad remote delete, and checks the local and public deployment markers. The overlay upload preserves existing files, which can leave stale assets; a versioned-release/symlink strategy requires a separately reviewed hosting layout before adoption.

The rollback workflow is a manual production workflow. It requires an explicitly named backup and `RESTORE`, checks archive member paths and rejects links/special files before extraction, creates a pre-rollback backup, and verifies the public marker. It has not been run against Hostinger and is not considered validated until tested in isolated staging.

No Hostinger deployment secrets or target variables are currently configured in Ledgerline. Do not use either workflow until staging has been provisioned, environment protection and target values have been reviewed, and a separate staging deployment approval is provided.
