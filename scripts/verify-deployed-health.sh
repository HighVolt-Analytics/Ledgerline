#!/usr/bin/env bash
set -euo pipefail

public_url="${1:-}"
release_commit="${2:-}"
index_file="${3:-}"
probe_id="${4:-${GITHUB_RUN_ID:-local}}"
marker_retries="${HEALTH_MARKER_RETRIES:-12}"
marker_interval="${HEALTH_MARKER_INTERVAL:-5}"

fail() {
  printf 'HEALTH_FAILURE stage=%s category=%s\n' "$1" "$2" >&2
  exit 1
}

[[ "$release_commit" =~ ^[0-9a-f]{40}$ ]] || fail configuration invalid_release_commit
[[ -s "$index_file" ]] || fail release_artifact missing_index
[[ "$marker_retries" =~ ^[1-9][0-9]*$ ]] || fail configuration invalid_retry_count
[[ "$marker_interval" =~ ^[0-9]+$ ]] || fail configuration invalid_retry_interval
[[ "$probe_id" =~ ^[A-Za-z0-9._-]+$ ]] || fail configuration invalid_probe_id

base_url="${public_url%/}"
if [[ "${HEALTH_TEST_ALLOW_HTTP:-false}" == true ]]; then
  valid_origin='false'
  [[ "$base_url" =~ ^http://(127\.0\.0\.1|localhost):[0-9]+$ ]] && valid_origin='true'
else
  valid_origin='false'
  [[ "$base_url" == 'https://quantumledgerline.com' ]] && valid_origin='true'
fi
if [[ "$valid_origin" != true ]]; then
  fail configuration invalid_public_origin
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "$tmp_dir"' EXIT
body_file="$tmp_dir/response"
last_category='transport_error'
last_status=''
last_content_type=''

# Fetch without printing response bodies or request URLs. The caller emits only
# an allowlisted stage and category if validation fails.
request() {
  local stage="$1" path="$2" query="${3:-}"
  local url="${public_url%/}${path}"
  local metrics rc
  [[ -z "$query" ]] || url+="?$query"

  if metrics="$(curl --silent --location --max-redirs 5 --connect-timeout 8 --max-time 30 \
    --header 'Cache-Control: no-cache, no-store' \
    --header 'Pragma: no-cache' \
    --output "$body_file" \
    --write-out $'%{http_code}\t%{url_effective}\t%{content_type}' \
    "$url" 2>/dev/null)"; then
    :
  else
    rc=$?
    if [[ "$rc" == 47 ]]; then last_category=redirect_limit; else last_category=transport_error; fi
    return 1
  fi

  local effective_url
  IFS=$'\t' read -r last_status effective_url last_content_type <<< "$metrics"
  if [[ "$last_status" != 200 ]]; then
    last_category=http_status
    return 1
  fi

  local effective_remainder effective_path requested_path
  if [[ "$effective_url" != "$base_url"* ]]; then
    last_category=redirect_origin_mismatch
    return 1
  fi
  effective_remainder="${effective_url#"$base_url"}"
  effective_path="${effective_remainder%%\?*}"
  [[ -n "$effective_path" ]] || effective_path='/'
  requested_path="${path%/}"
  effective_path="${effective_path%/}"
  [[ -n "$requested_path" ]] || requested_path='/'
  [[ -n "$effective_path" ]] || effective_path='/'
  if [[ "$requested_path" != "$effective_path" ]]; then
    last_category=redirect_path_mismatch
    return 1
  fi
  last_category=''
  return 0
}

check_shell_route() {
  local stage="$1" path="$2"
  request "$stage" "$path" "ledgerline_probe=${probe_id}" || fail "$stage" "$last_category"
  grep -Fq '<div id="root"></div>' "$body_file" || fail "$stage" content_mismatch
  printf 'HEALTH_OK stage=%s\n' "$stage"
}

check_shell_route public_home /

# The marker may take a short time to become visible over HTTPS after the
# verified SSH write. Cache-busting and bounded polling preserve the strict
# commit assertion while allowing normal host/CDN propagation.
marker_ok=false
for ((attempt = 1; attempt <= marker_retries; attempt++)); do
  if request public_marker /deploy-info.txt "ledgerline_probe=${probe_id}-${attempt}"; then
    if grep -Fxq "Commit: $release_commit" "$body_file"; then
      marker_ok=true
      break
    fi
    last_category=marker_mismatch
  fi
  if ((attempt < marker_retries && marker_interval > 0)); then sleep "$marker_interval"; fi
done
[[ "$marker_ok" == true ]] || fail public_marker "$last_category"
printf 'HEALTH_OK stage=public_marker\n'

check_shell_route spa_interactive_tour /interactive-tour
check_shell_route spa_resources /resources

request robots /robots.txt "ledgerline_probe=${probe_id}" || fail robots "$last_category"
grep -Fq 'User-agent:' "$body_file" || fail robots content_mismatch
printf 'HEALTH_OK stage=robots\n'

request sitemap /sitemap.xml "ledgerline_probe=${probe_id}" || fail sitemap "$last_category"
grep -Eq '<urlset|<sitemapindex' "$body_file" || fail sitemap content_mismatch
printf 'HEALTH_OK stage=sitemap\n'

mapfile -t static_assets < <(grep -oE '(src|href)="/assets/[A-Za-z0-9._-]+\.(js|css)"' "$index_file" | cut -d '"' -f2 | sort -u)
((${#static_assets[@]} > 0)) || fail release_artifact missing_static_assets
for asset in "${static_assets[@]}"; do
  [[ "$asset" =~ ^/assets/[A-Za-z0-9._-]+\.(js|css)$ ]] || fail release_artifact invalid_asset_reference
  request static_assets "$asset" "ledgerline_probe=${probe_id}" || fail static_assets "$last_category"
  content_type="${last_content_type,,}"
  case "$asset:$content_type" in
    *.js:application/javascript*|*.js:text/javascript*|*.js:application/x-javascript*) ;;
    *.css:text/css*) ;;
    *.js:*|*.css:*) fail static_assets content_type_mismatch ;;
    *) fail release_artifact unsupported_asset_type ;;
  esac
  [[ -s "$body_file" ]] || fail static_assets empty_asset
done
printf 'HEALTH_OK stage=static_assets count=%s\n' "${#static_assets[@]}"
