#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
suffix="${2:-}"
backup_name="${3:-}"
expected_manifest="${4:-}"
expected_marker="${5:-}"
expected_archive_sha256="${6:-}"

fail() {
  printf 'ROLLBACK_FAILURE stage=%s category=%s\n' "$1" "$2" >&2
  exit 1
}

[[ "$suffix" == '/domains/quantumledgerline.com/public_html' ]] || fail configuration invalid_target_suffix
[[ "$backup_name" =~ ^backup-[0-9]{8}-[0-9]{6}-[0-9]+-[a-f0-9]{40}\.tar\.gz$ ]] || fail configuration invalid_backup_name
[[ "$expected_manifest" =~ ^[a-f0-9]{64}$ ]] || fail configuration invalid_expected_manifest
[[ "$expected_marker" == NO_MARKER || "$expected_marker" =~ ^[a-f0-9]{40}$ ]] || fail configuration invalid_expected_marker
[[ "$expected_archive_sha256" =~ ^[a-f0-9]{64}$ ]] || fail configuration invalid_expected_archive_checksum
[[ -n "$HOME" && -d "$HOME" ]] || fail configuration invalid_home

home_real="$(realpath -e -- "$HOME")"
target_real="$(realpath -e -- "$target")"
[[ "$target_real" == "$home_real$suffix" ]] || fail target target_mismatch
[[ "$target_real" != / && "$target_real" != "$home_real" ]] || fail target unsafe_target

backup_dir="$(realpath -e -- "$home_real/deployment_backups/ledgerline-production")" || fail snapshot missing_backup_directory
[[ "$backup_dir" == "$home_real/deployment_backups/ledgerline-production" ]] || fail snapshot unsafe_backup_directory
archive="$(realpath -e -- "$backup_dir/$backup_name")" || fail snapshot missing_archive
[[ "$archive" == "$backup_dir/"* && -f "$archive" && -s "$archive" ]] || fail snapshot missing_archive
archive_sha256="$(sha256sum -- "$archive" | awk '{ print $1 }')"
[[ "$archive_sha256" == "$expected_archive_sha256" ]] || fail snapshot archive_checksum_mismatch
tar -tzf "$archive" >/dev/null 2>&1 || fail snapshot invalid_archive
if ! tar -tzf "$archive" | awk '/^\// || /(^|\/)\.\.(\/|$)/ { bad=1 } END { exit bad }'; then
  fail snapshot unsafe_archive_path
fi
if ! tar -tvzf "$archive" 2>/dev/null | awk '$1 !~ /^[-d]/ { bad=1 } END { exit bad }'; then
  fail snapshot unsafe_archive_entry
fi

# Validate the archive against the captured pre-deployment manifest before any
# production file is removed. A damaged or incomplete archive leaves the site
# untouched and fails closed.
target_parent="$(dirname -- "$target_real")"
target_parent_real="$(realpath -e -- "$target_parent")"
[[ "$target_parent_real" == "$target_parent" && "$target_parent_real" != / ]] || fail target unsafe_parent
target_mode="$(stat -c '%a' -- "$target_real")"
target_owner_group="$(stat -c '%u:%g' -- "$target_real")"
stage_dir="$(mktemp -d "$target_parent_real/.ledgerline-restore.XXXXXX")" || fail restore staging_unavailable
trap '[[ -z "${stage_dir:-}" ]] || rm -rf -- "$stage_dir"' EXIT
tar -xzf "$archive" -C "$stage_dir" --no-same-owner --no-same-permissions 2>/dev/null || fail snapshot preflight_extract_failed
archive_manifest="$(cd "$stage_dir" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | awk '{ print $1 }')"
[[ "$archive_manifest" == "$expected_manifest" ]] || fail snapshot preflight_manifest_mismatch
if [[ "$expected_marker" == NO_MARKER ]]; then
  [[ ! -e "$stage_dir/deploy-info.txt" ]] || fail snapshot preflight_marker_mismatch
else
  grep -Fxq "Commit: $expected_marker" "$stage_dir/deploy-info.txt" || fail snapshot preflight_marker_mismatch
fi
[[ -s "$stage_dir/index.html" ]] || fail snapshot preflight_missing_index
[[ "$(stat -c '%u:%g' -- "$stage_dir")" == "$target_owner_group" ]] || fail restore staging_owner_mismatch
chmod "$target_mode" -- "$stage_dir" || fail restore staging_permissions_failed

old_dir="$target_parent_real/.ledgerline-before-rollback-$$"
[[ ! -e "$old_dir" ]] || fail restore recovery_path_collision
mv -- "$target_real" "$old_dir" || fail restore preserve_current_release_failed
if ! mv -- "$stage_dir" "$target_real"; then
  mv -- "$old_dir" "$target_real" || fail restore recovery_failed
  fail restore install_snapshot_failed
fi
stage_dir=''
recover_previous_release() {
  local rejected="$target_parent_real/.ledgerline-rejected-rollback-$$"
  [[ ! -e "$rejected" ]] || return 1
  mv -- "$target_real" "$rejected" || return 1
  mv -- "$old_dir" "$target_real" || return 1
  rm -rf -- "$rejected"
}
[[ -s "$target_real/index.html" ]] || fail restore missing_index
restored_manifest="$(cd "$target_real" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | awk '{ print $1 }')"
if [[ "$restored_manifest" != "$expected_manifest" ]]; then
  recover_previous_release || fail restore recovery_failed
  fail restore manifest_mismatch
fi
if [[ "$expected_marker" == NO_MARKER ]]; then
  if [[ -e "$target_real/deploy-info.txt" ]]; then
    recover_previous_release || fail restore recovery_failed
    fail restore marker_mismatch
  fi
else
  if ! grep -Fxq "Commit: $expected_marker" "$target_real/deploy-info.txt"; then
    recover_previous_release || fail restore recovery_failed
    fail restore marker_mismatch
  fi
fi
rm -rf -- "$old_dir"
trap - EXIT
printf '%s\n' ROLLBACK_CONTENTS_OK
