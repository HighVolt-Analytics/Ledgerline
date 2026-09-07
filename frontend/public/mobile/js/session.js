/* LedgerLink session for the mobile shell (same keys as the React web app). */
(function (global) {
  'use strict';

  var ACCESS_KEY = 'ledgerline_access_token';
  var REFRESH_KEY = 'ledgerline_refresh_token';
  var USER_KEY = 'ledgerline_user';
  var MEMBERSHIPS_KEY = 'ledgerline_memberships';
  var LAST_TENANT_KEY = 'ledgerline_last_tenant_id';

  function readStore(key) {
    try {
      var v = localStorage.getItem(key);
      if (v != null) return v;
      v = sessionStorage.getItem(key);
      if (v == null) return null;
      localStorage.setItem(key, v);
      sessionStorage.removeItem(key);
      return v;
    } catch (e) {
      return null;
    }
  }

  function writeStore(key, value) {
    try {
      localStorage.setItem(key, value);
      sessionStorage.removeItem(key);
    } catch (e) { /* ignore */ }
  }

  function removeStore(key) {
    try {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    } catch (e) { /* ignore */ }
  }

  function appPrefix() {
    var path = location.pathname || '';
    var idx = path.indexOf('/mobile/');
    return idx >= 0 ? path.slice(0, idx) : '';
  }

  function apiBase() {
    if (typeof global.__LL_API_BASE__ === 'string') {
      return String(global.__LL_API_BASE__).replace(/\/$/, '');
    }
    return appPrefix();
  }

  function loginUrl() {
    return appPrefix() + '/login?returnTo=' + encodeURIComponent('/m');
  }

  function parseJson(raw, fallback) {
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  function getAccessToken() {
    return readStore(ACCESS_KEY);
  }

  function getRefreshToken() {
    return readStore(REFRESH_KEY);
  }

  function getUser() {
    return parseJson(readStore(USER_KEY), null);
  }

  function getMemberships() {
    var list = parseJson(readStore(MEMBERSHIPS_KEY), []);
    return Array.isArray(list) ? list : [];
  }

  function persistSession(payload) {
    if (!payload || !payload.access_token || !payload.refresh_token || !payload.user) return;
    writeStore(ACCESS_KEY, payload.access_token);
    writeStore(REFRESH_KEY, payload.refresh_token);
    writeStore(USER_KEY, JSON.stringify(payload.user));
    if (payload.memberships) {
      writeStore(MEMBERSHIPS_KEY, JSON.stringify(payload.memberships));
    }
    if (payload.user.tenant_id) {
      try {
        localStorage.setItem(LAST_TENANT_KEY, String(payload.user.tenant_id));
      } catch (e) { /* ignore */ }
    }
  }

  function clearSession() {
    removeStore(ACCESS_KEY);
    removeStore(REFRESH_KEY);
    removeStore(USER_KEY);
    removeStore(MEMBERSHIPS_KEY);
    try {
      localStorage.removeItem(LAST_TENANT_KEY);
    } catch (e) { /* ignore */ }
    try {
      sessionStorage.removeItem('ll_mobile_pending');
    } catch (e) { /* ignore */ }
  }

  function initialsFromName(name) {
    var parts = String(name || '')
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function firstName(name) {
    var parts = String(name || '')
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    return parts[0] || 'there';
  }

  function formatRole(role) {
    var raw = String(role || '').trim();
    if (!raw) return 'Member';
    return raw
      .replace(/_/g, ' ')
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function greetingPrefix() {
    var h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  function formatToday() {
    try {
      return new Intl.DateTimeFormat(undefined, {
        weekday: 'long',
        day: 'numeric',
        month: 'long'
      }).format(new Date());
    } catch (e) {
      return '';
    }
  }

  function authHeaders(extra) {
    var headers = Object.assign({}, extra || {});
    var access = getAccessToken();
    var user = getUser();
    if (access) headers.Authorization = 'Bearer ' + access;
    if (user && user.tenant_id) headers['X-Tenant-Id'] = String(user.tenant_id);
    return headers;
  }

  function unwrapData(json) {
    if (json && typeof json === 'object' && 'data' in json) return json.data;
    return json;
  }

  async function apiFetch(path, init) {
    var res = await fetch(apiBase() + path, init);
    var json = null;
    try {
      json = await res.json();
    } catch (e) {
      json = null;
    }
    if (!res.ok) {
      var detail =
        (json && (json.detail || (json.error && json.error.message))) || res.statusText;
      var err = new Error(typeof detail === 'string' ? detail : res.statusText);
      err.status = res.status;
      throw err;
    }
    return unwrapData(json);
  }

  async function refreshMe() {
    var access = getAccessToken();
    var refresh = getRefreshToken();
    if (!access || !refresh) return null;

    var me = await apiFetch('/api/auth/me', {
      method: 'GET',
      headers: authHeaders()
    });

    var memberships = getMemberships();
    try {
      memberships = await apiFetch('/api/auth/me/memberships', {
        method: 'GET',
        headers: authHeaders()
      });
    } catch (e) {
      /* keep cached memberships */
    }

    persistSession({
      access_token: access,
      refresh_token: refresh,
      user: me,
      memberships: memberships
    });
    return me;
  }

  async function fetchPermissions() {
    return apiFetch('/api/auth/me/permissions', {
      method: 'GET',
      headers: authHeaders()
    });
  }

  async function listApprovals(pageSize) {
    var size = pageSize || 50;
    return apiFetch('/api/approvals?page=1&page_size=' + size, {
      method: 'GET',
      headers: authHeaders()
    });
  }

  async function approveInvoice(id) {
    return apiFetch('/api/approvals/' + encodeURIComponent(id) + '/approve', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' })
    });
  }

  async function rejectInvoice(id) {
    return apiFetch('/api/approvals/' + encodeURIComponent(id) + '/reject', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' })
    });
  }

  async function logout() {
    var refresh = getRefreshToken();
    var headers = authHeaders({ 'Content-Type': 'application/json' });
    clearSession();
    try {
      await fetch(apiBase() + '/api/auth/logout', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(refresh ? { refresh_token: refresh } : {})
      });
    } catch (e) {
      /* still leave the app */
    }
    location.replace(loginUrl());
  }

  async function switchTenant(tenantId) {
    var data = await apiFetch('/api/auth/switch-tenant', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ tenant_id: tenantId })
    });
    persistSession({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: data.user,
      memberships: data.memberships || getMemberships()
    });
    try {
      localStorage.setItem(LAST_TENANT_KEY, String(tenantId));
    } catch (e) { /* ignore */ }
    location.reload();
  }

  global.LLSession = {
    getAccessToken: getAccessToken,
    getRefreshToken: getRefreshToken,
    getUser: getUser,
    getMemberships: getMemberships,
    persistSession: persistSession,
    clearSession: clearSession,
    initialsFromName: initialsFromName,
    firstName: firstName,
    formatRole: formatRole,
    greetingPrefix: greetingPrefix,
    formatToday: formatToday,
    loginUrl: loginUrl,
    apiBase: apiBase,
    authHeaders: authHeaders,
    apiFetch: apiFetch,
    refreshMe: refreshMe,
    fetchPermissions: fetchPermissions,
    listApprovals: listApprovals,
    approveInvoice: approveInvoice,
    rejectInvoice: rejectInvoice,
    logout: logout,
    switchTenant: switchTenant
  };
})(window);
