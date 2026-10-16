#!/usr/bin/env bash
set -euo pipefail

public_url="${1:-}"
release_commit="${2:-}"
index_file="${3:-}"
probe_id="${4:-${GITHUB_RUN_ID:-local}}"
marker_retries="${HEALTH_MARKER_RETRIES:-12}"
marker_interval="${HEALTH_MARKER_INTERVAL:-5}"
python_bin="${PYTHON_BIN:-python3}"

fail() {
  printf 'HEALTH_FAILURE stage=%s category=%s\n' "$1" "$2" >&2
  exit 1
}

[[ "$release_commit" =~ ^[0-9a-f]{40}$ ]] || fail configuration invalid_release_commit
[[ -s "$index_file" ]] || fail release_artifact missing_index
release_root="$(dirname -- "$index_file")"
for required_file in deploy-info.txt robots.txt sitemap.xml; do
  [[ -s "$release_root/$required_file" ]] || fail release_artifact "missing_${required_file//[^a-zA-Z0-9]/_}"
done
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
header_file="$tmp_dir/headers"
last_category='transport_error'
last_status=''
last_content_type=''
last_remote_ip=''
last_tls_verify=''
last_redirect_count=0
last_final_path=''
marker_inconclusive=false
marker_mismatch=false

origin_of() {
  local url="$1"
  if [[ "$url" =~ ^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]+) ]]; then
    printf '%s://%s' "${BASH_REMATCH[1],,}" "${BASH_REMATCH[2],,}"
  else
    return 1
  fi
}

# Fetch without printing response bodies or request URLs. The caller emits only
# an allowlisted stage and category if validation fails.
request() {
  local stage="$1" path="$2" query="${3:-}"
  local current_url="${public_url%/}${path}" metrics rc redirects=0 location location_origin path_query expected_origin
  local response_remote_ip response_tls_verify
  last_status=''
  last_content_type=''
  last_remote_ip=''
  last_tls_verify=''
  last_redirect_count=0
  last_final_path="$path"
  [[ -z "$query" ]] || current_url+="?$query"
  expected_origin="$(origin_of "${public_url%/}")" || { last_category=invalid_origin; return 1; }

  while :; do
    if metrics="$(curl --silent --connect-timeout 8 --max-time 30 \
      --header 'Cache-Control: no-cache, no-store' \
      --header 'Pragma: no-cache' \
      --dump-header "$header_file" \
      --output "$body_file" \
      --write-out $'%{http_code}\t%{content_type}\t%{remote_ip}\t%{ssl_verify_result}' \
      "$current_url" 2>/dev/null)"; then
      :
    else
      last_category=transport_error
      return 1
    fi

    IFS=$'\t' read -r last_status last_content_type response_remote_ip response_tls_verify <<< "$metrics"
    last_remote_ip="$response_remote_ip"
    last_tls_verify="$response_tls_verify"
    if [[ "$public_url" == https://* && "$last_tls_verify" != 0 ]]; then
      last_category=tls_verification_failure
      return 1
    fi
    last_redirect_count="$redirects"
    last_final_path="${current_url#"$base_url"}"
    last_final_path="${last_final_path%%\?*}"
    case "$last_status" in
      301|302|303|307|308)
        ((redirects < 5)) || { last_category=redirect_limit; return 1; }
        location="$(awk 'tolower($1) == "location:" { sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); value=$0 } END { print value }' "$header_file")"
        [[ -n "$location" ]] || { last_category=invalid_redirect; return 1; }
        if [[ "$location" == /* && "$location" != //* ]]; then
          current_url="${public_url%/}${location}"
        else
          location_origin="$(origin_of "$location")" || { last_category=redirect_origin_mismatch; return 1; }
          [[ "$location_origin" == "$expected_origin" ]] || { last_category=redirect_origin_mismatch; return 1; }
          if [[ "$location" =~ ^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+(/[^#]*)? ]]; then
            path_query="${BASH_REMATCH[1]:-/}"
            [[ "$path_query" == /* ]] || path_query="/$path_query"
            current_url="${public_url%/}${path_query}"
          else
            last_category=invalid_redirect
            return 1
          fi
        fi
        ((redirects += 1))
        continue
        ;;
      *) break ;;
    esac
  done

  if [[ "$last_status" != 200 ]]; then
    last_category=http_status
    return 1
  fi

  local effective_remainder effective_path requested_path current_origin
  current_origin="$(origin_of "$current_url")" || { last_category=redirect_origin_mismatch; return 1; }
  if [[ "$current_origin" != "$expected_origin" ]]; then
    last_category=redirect_origin_mismatch
    return 1
  fi
  effective_remainder="${current_url#"$base_url"}"
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

safe_header_value() {
  local wanted="$1" value=''
  local safe_value_re='^[A-Za-z0-9._,:=/+ -]+$'
  value="$(awk -v wanted="${wanted,,}" 'tolower($1) == wanted ":" { sub(/^[^:]*:[[:space:]]*/, ""); gsub(/\r/, ""); value=$0 } END { print value }' "$2")"
  value="${value:0:100}"
  value="${value//\"/}"
  if [[ -z "$value" ]]; then
    printf 'absent'
  elif [[ "$value" =~ $safe_value_re ]]; then
    printf '%s' "${value// /_}"
  else
    printf 'unavailable'
  fi
}

marker_commit_from_body() {
  local body="$1"
  sed -nE 's/^Commit: ([a-f0-9]{40})[[:space:]]*$/\1/p' "$body" | head -n 1
}

report_marker_response() {
  local source="$1" body="$2" headers="$3" status="$4" content_type="$5" remote_ip="$6" tls_verify="$7"
  local redirect_count="$8" final_path="$9" observed_commit body_hash diagnostic_host
  local content_type_re='^[A-Za-z0-9._/+;-]{1,80}$'
  observed_commit="$(marker_commit_from_body "$body")"
  [[ "$observed_commit" =~ ^[a-f0-9]{40}$ ]] || observed_commit='unparseable'
  body_hash='unavailable'
  [[ ! -s "$body" ]] || body_hash="$(sha256sum -- "$body" | cut -d ' ' -f1)"
  diagnostic_host="${public_url#*://}"
  diagnostic_host="${diagnostic_host%%/*}"
  [[ "$content_type" =~ $content_type_re ]] || content_type='unavailable'
  [[ "$remote_ip" =~ ^[A-Fa-f0-9:.]{1,64}$ ]] || remote_ip='unavailable'
  [[ "$tls_verify" =~ ^[0-9]+$ ]] || tls_verify='unavailable'
  [[ "$redirect_count" =~ ^[0-9]+$ ]] || redirect_count='unavailable'
  [[ "$final_path" =~ ^/[A-Za-z0-9._/-]*$ ]] || final_path='unavailable'
  printf 'HEALTH_DIAGNOSTIC stage=public_marker source=%s hostname=%s final_path=%s redirects=%s status=%s content_type=%s remote_ip=%s tls_verify=%s expected_sha256=%s body_sha256=%s marker_commit=%s cache_control=%s age=%s etag=%s last_modified=%s server=%s via=%s x_cache=%s cf_cache_status=%s\n' \
    "$source" "$diagnostic_host" "$final_path" "$redirect_count" "${status:-unavailable}" "$content_type" "$remote_ip" "$tls_verify" "$expected_marker_hash" "$body_hash" "$observed_commit" \
    "$(safe_header_value Cache-Control "$headers")" "$(safe_header_value Age "$headers")" "$(safe_header_value ETag "$headers")" \
    "$(safe_header_value Last-Modified "$headers")" "$(safe_header_value Server "$headers")" "$(safe_header_value Via "$headers")" \
    "$(safe_header_value X-Cache "$headers")" "$(safe_header_value CF-Cache-Status "$headers")"
}

report_direct_origin_marker() {
  local origin_address="${HOSTINGER_HOST:-}" direct_body="$tmp_dir/direct-origin-response" direct_headers="$tmp_dir/direct-origin-headers"
  local status='' content_type='' remote_ip='' tls_verify='' metrics rc host
  host="${public_url#https://}"
  host="${host%%/*}"
  if [[ "$public_url" != https://* || ! "$origin_address" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    printf 'HEALTH_DIAGNOSTIC stage=public_marker source=direct_origin result=unavailable reason=origin_address_unavailable\n'
    return 0
  fi
  local octet
  local -a octets=()
  IFS=. read -r -a octets <<< "$origin_address"
  for octet in "${octets[@]}"; do
    ((10#$octet <= 255)) || { printf 'HEALTH_DIAGNOSTIC stage=public_marker source=direct_origin result=unavailable reason=invalid_origin_address\n'; return 0; }
  done
  if metrics="$(curl --silent --connect-timeout 8 --max-time 15 \
    --header 'Cache-Control: no-cache, no-store' --header 'Pragma: no-cache' \
    --resolve "$host:443:$origin_address" --dump-header "$direct_headers" --output "$direct_body" \
    --write-out $'%{http_code}\t%{content_type}\t%{remote_ip}\t%{ssl_verify_result}' \
    "${public_url%/}/deploy-info.txt?ledgerline_origin_probe=${probe_id}" 2>/dev/null)"; then
    IFS=$'\t' read -r status content_type remote_ip tls_verify <<< "$metrics"
    report_marker_response direct_origin "$direct_body" "$direct_headers" "$status" "$content_type" "$remote_ip" "$tls_verify" 0 /deploy-info.txt
  else
    rc=$?
    printf 'HEALTH_DIAGNOSTIC stage=public_marker source=direct_origin result=unavailable reason=transport_error curl_exit=%s\n' "$rc"
  fi
}

diagnose_public_marker_failure() {
  report_marker_response public "$body_file" "$header_file" "$last_status" "$last_content_type" "$last_remote_ip" "$last_tls_verify" "$last_redirect_count" "$last_final_path"
  report_direct_origin_marker
}

check_shell_route() {
  local stage="$1" path="$2"
  request "$stage" "$path" "ledgerline_probe=${probe_id}" || fail "$stage" "$last_category"
  grep -Fq '<div id="root"></div>' "$body_file" || fail "$stage" content_mismatch
  local expected_hash actual_hash
  expected_hash="$(sha256sum -- "$index_file" | cut -d ' ' -f1)"
  actual_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
  [[ "$actual_hash" == "$expected_hash" ]] || fail "$stage" release_hash_mismatch
  printf 'HEALTH_OK stage=%s\n' "$stage"
}

check_shell_route public_home /

# The marker may take a short time to become visible over HTTPS after the
# verified SSH write. Cache-busting and bounded polling preserve the strict
# commit assertion while allowing normal host/CDN propagation.
marker_ok=false
marker_status=''
expected_marker_hash="$(sha256sum -- "$release_root/deploy-info.txt" | cut -d ' ' -f1)"
marker_failure_category='marker_mismatch'
for ((attempt = 1; attempt <= marker_retries; attempt++)); do
  if request public_marker /deploy-info.txt "ledgerline_probe=${probe_id}-${attempt}"; then
    if [[ "$last_content_type" != text/plain* ]]; then
      marker_inconclusive=true
      marker_failure_category=content_type_mismatch
      last_category=content_type_mismatch
      continue
    fi
    actual_marker_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
    if grep -Fxq "Commit: $release_commit" "$body_file" && [[ "$actual_marker_hash" == "$expected_marker_hash" ]]; then
      marker_ok=true
      break
    fi
    marker_mismatch=true
    last_category=marker_mismatch
  else
    marker_inconclusive=true
    marker_failure_category="$last_category"
  fi
  if ((attempt < marker_retries && marker_interval > 0)); then sleep "$marker_interval"; fi
done
if [[ "$marker_ok" != true ]]; then
  diagnose_public_marker_failure
  if [[ "$marker_inconclusive" == true || "$marker_mismatch" != true ]]; then
    fail public_marker "${marker_failure_category:-verification_inconclusive}"
  fi
  marker_status=stale_warning
else
  marker_status=matched
fi

check_shell_route spa_interactive_tour /interactive-tour
check_shell_route spa_resources /resources
check_shell_route marketing_spectra /industries/spectra

request robots /robots.txt "ledgerline_probe=${probe_id}" || fail robots "$last_category"
grep -Fq 'User-agent:' "$body_file" || fail robots content_mismatch
expected_hash="$(sha256sum -- "$release_root/robots.txt" | cut -d ' ' -f1)"
actual_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
[[ "$actual_hash" == "$expected_hash" ]] || fail robots release_hash_mismatch
printf 'HEALTH_OK stage=robots\n'

request sitemap /sitemap.xml "ledgerline_probe=${probe_id}" || fail sitemap "$last_category"
grep -Eq '<urlset|<sitemapindex' "$body_file" || fail sitemap content_mismatch
expected_hash="$(sha256sum -- "$release_root/sitemap.xml" | cut -d ' ' -f1)"
actual_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
[[ "$actual_hash" == "$expected_hash" ]] || fail sitemap release_hash_mismatch
printf 'HEALTH_OK stage=sitemap\n'

mapfile -t static_assets < <(grep -oE '(src|href)="/assets/[A-Za-z0-9._-]+\.(js|css)"' "$index_file" | cut -d '"' -f2 | sort -u)
((${#static_assets[@]} > 0)) || fail release_artifact missing_static_assets
for asset in "${static_assets[@]}"; do
  [[ "$asset" =~ ^/assets/[A-Za-z0-9._-]+\.(js|css)$ ]] || fail release_artifact invalid_asset_reference
  expected_file="$release_root$asset"
  [[ -s "$expected_file" ]] || fail release_artifact missing_referenced_asset
  expected_hash="$(sha256sum -- "$expected_file" | cut -d ' ' -f1)"
  request static_assets "$asset" "ledgerline_probe=${probe_id}" || fail static_assets "$last_category"
  content_type="${last_content_type,,}"
  case "$asset:$content_type" in
    *.js:application/javascript*|*.js:text/javascript*|*.js:application/x-javascript*) ;;
    *.css:text/css*) ;;
    *.js:*|*.css:*) fail static_assets content_type_mismatch ;;
    *) fail release_artifact unsupported_asset_type ;;
  esac
  [[ -s "$body_file" ]] || fail static_assets empty_asset
  actual_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
  [[ "$actual_hash" == "$expected_hash" ]] || fail static_assets release_hash_mismatch
done
printf 'HEALTH_OK stage=static_assets count=%s\n' "${#static_assets[@]}"

verify_release_mime() {
  local relative="$1" content_type="${2,,}"
  case "$relative:$content_type" in
    *.js:application/javascript*|*.js:text/javascript*|*.js:application/x-javascript*) ;;
    *.css:text/css*) ;;
    *.html:text/html*) ;;
    *.svg:image/svg+xml*) ;;
    *.png:image/png*) ;;
    *.jpg:image/jpeg*|*.jpeg:image/jpeg*) ;;
    *.txt:text/plain*) ;;
    *.xml:application/xml*|*.xml:text/xml*) ;;
    *.htaccess:*) return 0 ;;
    *:text/html*) return 1 ;;
    *) return 1 ;;
  esac
}

public_release_files=0
while IFS= read -r relative_file; do
  [[ -n "$relative_file" ]] || continue
  encoded_path="/$("$python_bin" -c 'import sys, urllib.parse; sys.stdout.write(urllib.parse.quote(sys.argv[1], safe="/-._~"))' "$relative_file")"
  request release_files "$encoded_path" "ledgerline_probe=${probe_id}" || fail release_files "$last_category"
  verify_release_mime "$relative_file" "$last_content_type" || fail release_files content_type_mismatch
  expected_hash="$(sha256sum -- "$release_root/$relative_file" | cut -d ' ' -f1)"
  actual_hash="$(sha256sum -- "$body_file" | cut -d ' ' -f1)"
  [[ "$actual_hash" == "$expected_hash" ]] || fail release_files release_hash_mismatch
  ((public_release_files += 1))
done < <(cd "$release_root" && find . -type f ! -name deploy-info.txt ! -name .htaccess -print | LC_ALL=C sort | sed 's#^./##')
((public_release_files > 0)) || fail release_artifact missing_public_release_files
printf 'HEALTH_OK stage=release_files count=%s\n' "$public_release_files"

if [[ "$marker_status" == stale_warning ]]; then
  printf 'HEALTH_WARNING stage=public_marker category=stale_marker_content expected_commit=%s\n' "$release_commit"
  printf 'PUBLIC_MARKER_STATUS=stale_warning\n'
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'public_marker_status=stale_warning\n' >> "$GITHUB_OUTPUT"
  fi
else
  printf 'HEALTH_OK stage=public_marker\n'
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'public_marker_status=matched\n' >> "$GITHUB_OUTPUT"
  fi
fi
