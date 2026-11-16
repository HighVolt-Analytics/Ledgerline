<?php
declare(strict_types=1);

// Router for `php -S` local development. Production uses Apache/.htaccess.
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
if (preg_match('#^/api/partners(?:/|$)#', $uri)) {
    require __DIR__ . '/partners/index.php';
    return true;
}
$file = __DIR__ . '/../' . ltrim($uri, '/');
if ($uri !== '/' && is_file($file)) {
    return false;
}
return false;
