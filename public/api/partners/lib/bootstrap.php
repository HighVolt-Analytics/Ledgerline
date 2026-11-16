<?php
declare(strict_types=1);

/**
 * Partner auth bootstrap for Hostinger (PHP + SQLite).
 * Database path can be overridden with PARTNER_DB_PATH (absolute or relative).
 */

function partner_env(string $key, ?string $default = null): ?string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        return $default;
    }
    return $value;
}

function partner_db_path(): string
{
    $configured = partner_env('PARTNER_DB_PATH');
    if ($configured) {
        return $configured;
    }
    // Default: private data directory next to the API (blocked by .htaccess).
    return dirname(__DIR__, 2) . DIRECTORY_SEPARATOR . 'data' . DIRECTORY_SEPARATOR . 'partners.sqlite';
}

function partner_pdo(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $path = partner_db_path();
    $dir = dirname($path);
    if (!is_dir($dir) && !mkdir($dir, 0700, true) && !is_dir($dir)) {
        throw new RuntimeException('Unable to create partner database directory.');
    }

    $pdo = new PDO('sqlite:' . $path, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA foreign_keys = ON');
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS partners (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            firm TEXT NOT NULL,
            type TEXT NOT NULL,
            country TEXT NOT NULL,
            abn TEXT NOT NULL DEFAULT \'\',
            code TEXT NOT NULL,
            founding INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(email),
            UNIQUE(code)
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS partner_sessions (
            id TEXT PRIMARY KEY,
            partner_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(partner_id) REFERENCES partners(id) ON DELETE CASCADE
        )'
    );
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_partner_sessions_partner ON partner_sessions(partner_id)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_partner_sessions_expires ON partner_sessions(expires_at)');
    return $pdo;
}

function partner_json_input(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') {
        return [];
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : [];
}

function partner_respond(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body, JSON_UNESCAPED_SLASHES);
}

function partner_new_id(string $prefix): string
{
    return $prefix . bin2hex(random_bytes(8));
}

function partner_make_code(string $firm): string
{
    $base = strtoupper(preg_replace('/[^A-Za-z0-9]+/', '', $firm) ?: 'PARTNER');
    $base = substr($base, 0, 6);
    if ($base === '') {
        $base = 'PARTNER';
    }
    return $base . random_int(10, 99);
}

function partner_public_row(array $row): array
{
    return [
        'id' => $row['id'],
        'email' => $row['email'],
        'name' => $row['name'],
        'firm' => $row['firm'],
        'type' => $row['type'],
        'country' => $row['country'],
        'abn' => $row['abn'],
        'code' => $row['code'],
        'founding' => (bool) $row['founding'],
        'created' => substr((string) $row['created_at'], 0, 10),
    ];
}

function partner_cookie_name(): string
{
    return partner_env('PARTNER_SESSION_COOKIE', 'll_partner_session') ?: 'll_partner_session';
}

function partner_session_ttl_seconds(): int
{
    $ttl = (int) (partner_env('PARTNER_SESSION_TTL_SECONDS', '1209600') ?: '1209600');
    return max(3600, $ttl);
}

function partner_set_session_cookie(string $sessionId): void
{
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['SERVER_PORT']) && (string) $_SERVER['SERVER_PORT'] === '443')
        || (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
    setcookie(partner_cookie_name(), $sessionId, [
        'expires' => time() + partner_session_ttl_seconds(),
        'path' => '/',
        'secure' => $secure,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
}

function partner_clear_session_cookie(): void
{
    $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (isset($_SERVER['SERVER_PORT']) && (string) $_SERVER['SERVER_PORT'] === '443')
        || (isset($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
    setcookie(partner_cookie_name(), '', [
        'expires' => time() - 3600,
        'path' => '/',
        'secure' => $secure,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
}

function partner_valid_email(string $email): bool
{
    return (bool) filter_var($email, FILTER_VALIDATE_EMAIL);
}

/**
 * Document root used to locate private/partner-secrets.php beside public_html.
 * PARTNER_DOCUMENT_ROOT is a test/local override only.
 */
function partner_document_root(): ?string
{
    $override = partner_env('PARTNER_DOCUMENT_ROOT');
    if ($override !== null && $override !== '') {
        $resolved = realpath($override);
        return $resolved !== false ? $resolved : null;
    }
    $doc = $_SERVER['DOCUMENT_ROOT'] ?? '';
    if (!is_string($doc) || $doc === '') {
        return null;
    }
    $resolved = realpath($doc);
    return $resolved !== false ? $resolved : null;
}

/**
 * Hostinger layout: private/partner-secrets.php sits beside public_html (outside the web root).
 * Returns null when the path cannot be proven to be outside the document root.
 */
function partner_secrets_file_path(): ?string
{
    $docRoot = partner_document_root();
    if ($docRoot === null) {
        return null;
    }
    $parent = dirname($docRoot);
    if ($parent === '' || $parent === '.' || $parent === $docRoot) {
        return null;
    }
    $candidate = $parent . DIRECTORY_SEPARATOR . 'private' . DIRECTORY_SEPARATOR . 'partner-secrets.php';
    $resolved = realpath($candidate);
    if ($resolved === false || !is_file($resolved)) {
        return null;
    }
    $docPrefix = $docRoot . DIRECTORY_SEPARATOR;
    if ($resolved === $docRoot || str_starts_with($resolved, $docPrefix)) {
        return null;
    }
    return $resolved;
}

/**
 * Load PARTNER_ADMIN_TOKEN from private/partner-secrets.php (outside document root).
 * Fail closed on missing/invalid files. Never log or echo the token.
 */
function partner_admin_token_from_secrets_file(): ?string
{
    $path = partner_secrets_file_path();
    if ($path === null) {
        return null;
    }
    try {
        /** @var mixed $config */
        $config = require $path;
    } catch (Throwable $e) {
        return null;
    }
    if (!is_array($config)) {
        return null;
    }
    $token = $config['PARTNER_ADMIN_TOKEN'] ?? null;
    if (!is_string($token) || $token === '') {
        return null;
    }
    return $token;
}

/**
 * Shared secret for HighVolt deployment portal → Ledgerline partner list (server-to-server).
 * Prefer getenv('PARTNER_ADMIN_TOKEN'); otherwise private/partner-secrets.php beside public_html.
 * Fail closed when unset. Never authorize partner listing via session cookies.
 */
function partner_admin_token(): ?string
{
    $token = partner_env('PARTNER_ADMIN_TOKEN');
    if ($token !== null && $token !== '') {
        return $token;
    }
    return partner_admin_token_from_secrets_file();
}

function partner_request_admin_token(): ?string
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (is_string($header) && preg_match('/^\s*Bearer\s+(\S+)\s*$/i', $header, $m)) {
        return $m[1];
    }
    $custom = $_SERVER['HTTP_X_PARTNER_ADMIN_TOKEN'] ?? '';
    if (is_string($custom) && $custom !== '') {
        return $custom;
    }
    return null;
}

function partner_admin_authorized(): bool
{
    $expected = partner_admin_token();
    if ($expected === null) {
        return false;
    }
    $provided = partner_request_admin_token();
    if ($provided === null || $provided === '') {
        return false;
    }
    return hash_equals($expected, $provided);
}

/** Read-only account fields for the deployment portal Partners tab. */
function partner_admin_row(array $row): array
{
    return [
        'name' => $row['name'],
        'email' => $row['email'],
        'firm' => $row['firm'],
        'country' => $row['country'],
        'type' => $row['type'],
        'created' => substr((string) $row['created_at'], 0, 10),
    ];
}
