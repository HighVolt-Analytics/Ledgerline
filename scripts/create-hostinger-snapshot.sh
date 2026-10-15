#!/usr/bin/env bash
set -euo pipefail

target="${1:-}"
suffix="${2:-}"
commit="${3:-}"
run_id="${4:-}"

fail() {
  printf 'SNAPSHOT_FAILURE stage=%s category=%s\n' "$1" "$2" >&2
  exit 1
}

[[ "$suffix" == '/domains/quantumledgerline.com/public_html' ]] || fail configuration invalid_target_suffix
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || fail configuration invalid_release_commit
[[ "$run_id" =~ ^[0-9]+$ ]] || fail configuration invalid_run_id
[[ -n "$HOME" && -d "$HOME" ]] || fail configuration invalid_home

home_real="$(realpath -e -- "$HOME")"
target_real="$(realpath -e -- "$target")"
[[ "$target_real" == "$home_real$suffix" ]] || fail target target_mismatch
[[ "$target_real" != / && "$target_real" != "$home_real" ]] || fail target unsafe_target
[[ -r "$target_real" && -w "$target_real" ]] || fail target inaccessible_target

backup_dir="$home_real/deployment_backups/ledgerline-production"
umask 077
mkdir -p -- "$backup_dir"
backup_dir="$(realpath -e -- "$backup_dir")"
[[ "$backup_dir" == "$home_real/deployment_backups/ledgerline-production" ]] || fail snapshot unsafe_backup_directory
timestamp="$(date -u +%Y%m%d-%H%M%S)"
backup_name="backup-${timestamp}-${run_id}-${commit}.tar.gz"
archive="$backup_dir/$backup_name"
[[ ! -e "$archive" ]] || fail snapshot backup_name_collision

tar -czf "$archive" -C "$target_real" .
[[ -s "$archive" ]] || fail snapshot empty_archive
tar -tzf "$archive" >/dev/null 2>&1 || fail snapshot invalid_archive
if ! tar -tzf "$archive" | awk '/^\// || /(^|\/)\.\.(\/|$)/ { bad=1 } END { exit bad }'; then
  fail snapshot unsafe_archive_path
fi
if ! tar -tvzf "$archive" | awk '$1 !~ /^[-d]/ { bad=1 } END { exit bad }'; then
  fail snapshot unsafe_archive_entry
fi

verify_dir="$(mktemp -d "$backup_dir/verify.XXXXXX")"
trap 'rm -rf -- "$verify_dir"' EXIT
tar -xzf "$archive" -C "$verify_dir" --no-same-owner --no-same-permissions || fail snapshot extraction_failed
current_manifest="$(cd "$target_real" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | awk '{ print $1 }')"
archive_manifest="$(cd "$verify_dir" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | awk '{ print $1 }')"
[[ "$current_manifest" =~ ^[a-f0-9]{64}$ && "$archive_manifest" =~ ^[a-f0-9]{64}$ ]] || fail snapshot manifest_unavailable
[[ "$archive_manifest" == "$current_manifest" ]] || fail snapshot archive_manifest_mismatch

old_marker='NO_MARKER'
if [[ -s "$target_real/deploy-info.txt" ]]; then
  old_marker="$(sed -n 's/^Commit: //p' "$target_real/deploy-info.txt" | head -n 1)"
  [[ "$old_marker" =~ ^[a-f0-9]{40}$ ]] || fail snapshot invalid_existing_marker
fi
if [[ "$old_marker" == NO_MARKER ]]; then
  [[ ! -e "$verify_dir/deploy-info.txt" ]] || fail snapshot archive_marker_mismatch
else
  grep -Fxq "Commit: $old_marker" "$verify_dir/deploy-info.txt" || fail snapshot archive_marker_mismatch
fi
backup_sha256="$(sha256sum -- "$archive" | awk '{ print $1 }')"
[[ "$backup_sha256" =~ ^[a-f0-9]{64}$ ]] || fail snapshot invalid_archive_checksum
printf 'BACKUP_SHA256:%s\n' "$backup_sha256"
printf 'PREDEPLOY_MARKER:%s\n' "$old_marker"
printf 'PREDEPLOY_MANIFEST:%s\n' "$current_manifest"
printf 'BACKUP_NAME:%s\n' "$backup_name"
printf '%s\n' BACKUP_OK
