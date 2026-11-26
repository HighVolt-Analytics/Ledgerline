<?php
declare(strict_types=1);

require_once __DIR__ . '/lib/AuthService.php';

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization, X-Partner-Admin-Token');
    header('Access-Control-Allow-Credentials: true');
    http_response_code(204);
    exit;
}

try {
    $auth = PartnerAuthService::create();
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    $path = rtrim($path, '/') ?: '/';
    $cookieName = partner_cookie_name();
    $sessionId = isset($_COOKIE[$cookieName]) ? (string) $_COOKIE[$cookieName] : null;

    // Accept /api/partners, /api/partners/signup, /api/partners/admin/list, etc.
    $action = 'me';
    if (preg_match('#/api/partners/program/bank$#', $path)) {
        $action = 'program_bank';
    } elseif (preg_match('#/api/partners/program/code$#', $path)) {
        $action = 'program_code';
    } elseif (preg_match('#/api/partners/program/reapply$#', $path)) {
        $action = 'program_reapply';
    } elseif (preg_match('#/api/partners/program$#', $path)) {
        $action = 'program';
    } elseif (preg_match('#/api/partners/admin/list$#', $path)) {
        $action = 'admin_list';
    } elseif (preg_match('#/api/partners(?:/(signup|signin|signout|me))?$#', $path, $m)) {
        $action = $m[1] ?? 'me';
    } elseif (preg_match('#/(admin/list)$#', $path)) {
        $action = 'admin_list';
    } elseif (preg_match('#/(signup|signin|signout|me)$#', $path, $m)) {
        // When invoked via PHP built-in server with rewritten SCRIPT path.
        $action = $m[1];
    }

    if ($method === 'GET' && $action === 'admin_list') {
        if (!partner_admin_authorized()) {
            partner_respond(401, [
                'error' => 'unauthorized',
                'message' => 'Admin token required.',
            ]);
            exit;
        }
        $result = $auth->listForAdmin();
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method === 'GET' && $action === 'program') {
        $result = $auth->program($sessionId);
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method === 'POST' && $action === 'program_bank') {
        $result = $auth->programBank($sessionId, partner_json_input());
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method === 'POST' && $action === 'program_reapply') {
        $result = $auth->programReapply($sessionId, partner_json_input());
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method === 'POST' && $action === 'program_code') {
        $result = $auth->programCode($sessionId);
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method === 'GET' && ($action === 'me' || $path === '/api/partners')) {
        $result = $auth->me($sessionId);
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($method !== 'POST') {
        partner_respond(405, ['error' => 'method_not_allowed']);
        exit;
    }

    $input = partner_json_input();

    if ($action === 'signup') {
        $result = $auth->signup($input);
        if (!empty($result['sessionId'])) {
            partner_set_session_cookie($result['sessionId']);
        }
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($action === 'signin') {
        $result = $auth->signin($input);
        if (!empty($result['sessionId'])) {
            partner_set_session_cookie($result['sessionId']);
        }
        partner_respond($result['status'], $result['body']);
        exit;
    }

    if ($action === 'signout') {
        $result = $auth->signout($sessionId);
        partner_clear_session_cookie();
        partner_respond($result['status'], $result['body']);
        exit;
    }

    partner_respond(404, ['error' => 'not_found']);
} catch (Throwable $e) {
    error_log('partner_auth: ' . $e->getMessage());
    partner_respond(500, [
        'error' => 'server_error',
        'message' => 'Partner authentication is temporarily unavailable.',
    ]);
}
