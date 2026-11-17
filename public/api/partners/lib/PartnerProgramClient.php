<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/**
 * Server-side link from the website partner program to the HighVolt partner service.
 *
 * - Signup: POST {PARTNER_SERVICE_URL}/applications (anonymous, rate-limited).
 * - Portal: GET {PARTNER_SERVICE_URL}/site/me/... with a 60-second RS256 token this server signs for the
 *   signed-in partner only (partner-service ADR-0018). The private key comes from PARTNER_SITE_SIGNING_KEY
 *   (env or private/partner-secrets.php) and never leaves this server.
 *
 * Off unless PARTNER_SERVICE_URL is set, so the live site is unchanged until it is configured.
 * Best-effort: a failure never blocks website signup or sign-in.
 */
final class PartnerProgramClient
{
    public const PRODUCT_KEY = 'ledgerline';
    public const AGREEMENT_VERSION = 'ledgerline-partner-terms-2026-11';
    public const AUDIENCE = 'hva-partner-site';
    public const TOKEN_TTL_SECONDS = 60;

    public function __construct(
        private ?string $baseUrl,
        private ?string $signingKeyPem = null,
        private string $keyId = 'ledgerline-1',
        private string $issuer = 'https://quantumledgerline.com/partnership',
        private float $timeoutSeconds = 5.0,
    ) {
    }

    public static function fromEnv(): self
    {
        $url = partner_env('PARTNER_SERVICE_URL');
        return new self(
            $url ? rtrim($url, '/') : null,
            partner_secret('PARTNER_SITE_SIGNING_KEY'),
            partner_env('PARTNER_SITE_KEY_ID', 'ledgerline-1'),
            partner_env('PARTNER_SITE_ISSUER', 'https://quantumledgerline.com/partnership'),
        );
    }

    public function enabled(): bool
    {
        return $this->baseUrl !== null && preg_match('#^https?://#', $this->baseUrl) === 1;
    }

    public function portalEnabled(): bool
    {
        return $this->enabled() && $this->signingKeyPem !== null;
    }

    /** @return string|null partner id from the service, or null when disabled or failed */
    public function apply(array $partner, bool $marketingConsent = false): ?string
    {
        if (!$this->enabled()) {
            return null;
        }
        [$status, $json] = $this->request('POST', '/applications', null, [
            'product_key' => self::PRODUCT_KEY,
            'display_name' => $partner['firm'] !== '' ? $partner['firm'] : $partner['name'],
            'contact_email' => $partner['email'],
            'country' => $partner['country'],
            'agreement_version' => self::AGREEMENT_VERSION,
            'marketing_consent' => $marketingConsent,
        ]);
        if ($status !== 201) {
            error_log('partner_program: application not linked, status=' . $status); // status only, no PII
            return null;
        }
        $id = is_array($json) ? ($json['partner_id'] ?? null) : null;
        return is_string($id) && $id !== '' ? $id : null;
    }

    /**
     * Live program data for one partner: status, referral codes and balance (minor units).
     * Returns null when the portal link is off or the service did not answer.
     */
    public function summary(string $hvaPartnerId): ?array
    {
        if (!$this->portalEnabled()) {
            return null;
        }
        $token = $this->signFor($hvaPartnerId);
        if ($token === null) {
            return null;
        }
        [$s1, $profile] = $this->request('GET', '/site/me', $token);
        if ($s1 !== 200 || !is_array($profile)) {
            error_log('partner_program: profile unavailable, status=' . $s1);
            return null;
        }
        [$s2, $balance] = $this->request('GET', '/site/me/balance', $token);
        [$s3, $codes] = $this->request('GET', '/site/me/referral-codes', $token);
        [$s4, $accounts] = $this->request('GET', '/site/me/payout-account', $token);
        $bank = [];
        if ($s4 === 200 && is_array($accounts)) {
            foreach (array_filter($accounts, 'is_array') as $a) {
                // Masked only: the service never returns full bank details.
                $bank[] = ['status' => (string) ($a['status'] ?? ''), 'masked' => (string) ($a['account_masked'] ?? ''),
                    'holder' => (string) ($a['account_holder_name'] ?? '')];
            }
        }
        return [
            'bank' => $bank,
            'status' => is_string($profile['status'] ?? null) ? $profile['status'] : null,
            // Public click link: Edge /r/{code} redirects to the LedgerLine landing page and sets the referral cookie.
            'referralBase' => $this->baseUrl . '/r/',
            'codes' => $s3 === 200 && is_array($codes) ? array_values(array_map(
                static fn ($c) => ['code' => (string) ($c['code'] ?? ''), 'status' => (string) ($c['status'] ?? '')],
                array_filter($codes, 'is_array'),
            )) : [],
            'balance' => $s2 === 200 && is_array($balance) ? [
                'currency' => (string) ($balance['currency'] ?? ''),
                'pendingMinor' => (int) ($balance['pending_minor'] ?? 0),
                'approvedMinor' => (int) ($balance['approved_minor'] ?? 0),
                'paidMinor' => (int) ($balance['paid_minor'] ?? 0),
                'debtMinor' => (int) ($balance['debt_minor'] ?? 0),
            ] : null,
        ];
    }

    /** Creates the partner's referral code (only allowed once the partner is approved). Returns HTTP status. */
    public function createCode(string $hvaPartnerId): int
    {
        if (!$this->portalEnabled()) {
            return 0;
        }
        $token = $this->signFor($hvaPartnerId);
        return $token === null ? 0 : $this->request('POST', '/site/me/referral-codes', $token, new stdClass())[0];
    }

    /**
     * Submits bank details for the partner. Saved as PENDING by partner-service and unusable for payouts until a
     * PartnerAdmin confirms them. Returns HTTP status (0 when off or unreachable).
     */
    public function savePayoutAccount(string $hvaPartnerId, string $holder, string $accountNumber, string $bankCode): int
    {
        if (!$this->portalEnabled()) {
            return 0;
        }
        $token = $this->signFor($hvaPartnerId);
        return $token === null ? 0 : $this->request('PUT', '/site/me/payout-account', $token, [
            'provider' => 'MANUAL_BANK_BATCH',
            'account_holder_name' => $holder,
            'account_number' => $accountNumber,
            'bank_code' => $bankCode,
        ])[0];
    }

    /** RS256 JWT, 60 s, for exactly this partner and product. */
    public function signFor(string $hvaPartnerId): ?string
    {
        if ($this->signingKeyPem === null || preg_match('/^[0-9a-f-]{36}$/i', $hvaPartnerId) !== 1) {
            return null;
        }
        $key = openssl_pkey_get_private($this->signingKeyPem);
        if ($key === false) {
            error_log('partner_program: signing key unreadable');
            return null;
        }
        $now = time();
        $header = ['alg' => 'RS256', 'typ' => 'JWT', 'kid' => $this->keyId];
        $claims = [
            'iss' => $this->issuer,
            'aud' => self::AUDIENCE,
            'sub' => $hvaPartnerId,
            'partner_id' => $hvaPartnerId,
            'app_id' => self::PRODUCT_KEY,
            'role' => 'Partner',
            'type' => 'access',
            'iat' => $now,
            'exp' => $now + self::TOKEN_TTL_SECONDS,
            'jti' => bin2hex(random_bytes(16)),
        ];
        $input = self::b64(json_encode($header, JSON_UNESCAPED_SLASHES)) . '.'
            . self::b64(json_encode($claims, JSON_UNESCAPED_SLASHES));
        if (!openssl_sign($input, $signature, $key, OPENSSL_ALGO_SHA256)) {
            return null;
        }
        return $input . '.' . self::b64($signature);
    }

    private static function b64(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }

    /** @return array{0:int,1:mixed} HTTP status (0 on network failure) and decoded JSON body */
    private function request(string $method, string $path, ?string $bearer, mixed $body = null): array
    {
        $headers = "Accept: application/json\r\n";
        if ($bearer !== null) {
            $headers .= 'Authorization: Bearer ' . $bearer . "\r\n";
        }
        $http = ['method' => $method, 'header' => $headers, 'timeout' => $this->timeoutSeconds, 'ignore_errors' => true];
        if ($body !== null) {
            $http['header'] .= "Content-Type: application/json\r\n";
            $http['content'] = json_encode($body, JSON_UNESCAPED_SLASHES);
        }
        $raw = @file_get_contents($this->baseUrl . $path, false, stream_context_create(['http' => $http]));
        $status = 0;
        foreach ($http_response_header ?? [] as $line) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m)) {
                $status = (int) $m[1];
            }
        }
        return [$status, is_string($raw) ? json_decode($raw, true) : null];
    }
}
