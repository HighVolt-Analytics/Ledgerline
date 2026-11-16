<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/**
 * Server-side link from website partner signup to the HighVolt partner service
 * (POST {PARTNER_SERVICE_URL}/applications).
 *
 * Off unless PARTNER_SERVICE_URL is set, so the live site is unchanged until it is configured.
 * Best-effort: a failure never blocks website signup; the account stays unlinked and can be retried.
 */
final class PartnerProgramClient
{
    public const PRODUCT_KEY = 'ledgerline';
    public const AGREEMENT_VERSION = 'ledgerline-partner-terms-2026-11';

    public function __construct(private ?string $baseUrl, private float $timeoutSeconds = 5.0)
    {
    }

    public static function fromEnv(): self
    {
        $url = partner_env('PARTNER_SERVICE_URL');
        return new self($url ? rtrim($url, '/') : null);
    }

    public function enabled(): bool
    {
        return $this->baseUrl !== null && preg_match('#^https?://#', $this->baseUrl) === 1;
    }

    /** @return string|null partner id from the service, or null when disabled or failed */
    public function apply(array $partner, bool $marketingConsent = false): ?string
    {
        if (!$this->enabled()) {
            return null;
        }
        $payload = json_encode([
            'product_key' => self::PRODUCT_KEY,
            'display_name' => $partner['firm'] !== '' ? $partner['firm'] : $partner['name'],
            'contact_email' => $partner['email'],
            'country' => $partner['country'],
            'agreement_version' => self::AGREEMENT_VERSION,
            'marketing_consent' => $marketingConsent,
        ], JSON_UNESCAPED_SLASHES);

        $context = stream_context_create([
            'http' => [
                'method' => 'POST',
                'header' => "Content-Type: application/json\r\nAccept: application/json\r\n",
                'content' => $payload,
                'timeout' => $this->timeoutSeconds,
                'ignore_errors' => true,
            ],
        ]);
        $body = @file_get_contents($this->baseUrl . '/applications', false, $context);
        $status = 0;
        foreach ($http_response_header ?? [] as $line) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m)) {
                $status = (int) $m[1];
            }
        }
        if ($status !== 201 || !is_string($body)) {
            // No PII in logs: status only.
            error_log('partner_program: application not linked, status=' . $status);
            return null;
        }
        $json = json_decode($body, true);
        $id = is_array($json) ? ($json['partner_id'] ?? null) : null;
        return is_string($id) && $id !== '' ? $id : null;
    }
}
