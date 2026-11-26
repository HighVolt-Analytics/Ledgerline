<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/PartnerProgramClient.php';

final class PartnerAuthService
{
    public function __construct(private PDO $pdo, private PartnerProgramClient $program)
    {
    }

    public static function create(): self
    {
        return new self(partner_pdo(), PartnerProgramClient::fromEnv());
    }

    public function signup(array $input): array
    {
        $name = trim((string) ($input['name'] ?? ''));
        $email = strtolower(trim((string) ($input['email'] ?? '')));
        $password = (string) ($input['password'] ?? $input['pw'] ?? '');
        $firm = trim((string) ($input['firm'] ?? ''));
        $type = trim((string) ($input['type'] ?? 'Accounting firm'));
        $country = strtoupper(trim((string) ($input['country'] ?? 'AU')));
        $abn = trim((string) ($input['abn'] ?? ''));

        $errors = [];
        if ($name === '') {
            $errors['name'] = 'Enter your name';
        }
        if (!partner_valid_email($email)) {
            $errors['email'] = 'Enter a valid email address';
        }
        if (strlen($password) < 8) {
            $errors['password'] = 'Use at least 8 characters';
        }
        if ($firm === '') {
            $errors['firm'] = 'Enter your firm name';
        }
        if ($errors) {
            return ['ok' => false, 'status' => 400, 'body' => ['error' => 'invalid', 'fields' => $errors]];
        }

        $existing = $this->pdo->prepare('SELECT id FROM partners WHERE email = ? COLLATE NOCASE LIMIT 1');
        $existing->execute([$email]);
        if ($existing->fetch()) {
            return [
                'ok' => false,
                'status' => 409,
                'body' => [
                    'error' => 'duplicate_email',
                    'message' => 'A partner account already uses this email. Sign in instead.',
                    'signinPath' => '/partnership/signin',
                ],
            ];
        }

        $id = partner_new_id('P_');
        $code = $this->uniqueCode($firm);
        $hash = password_hash($password, PASSWORD_DEFAULT);
        if ($hash === false) {
            return ['ok' => false, 'status' => 500, 'body' => ['error' => 'hash_failed', 'message' => 'Unable to create account.']];
        }
        $createdAt = gmdate('c');

        $insert = $this->pdo->prepare(
            'INSERT INTO partners (id, email, password_hash, name, firm, type, country, abn, code, founding, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)'
        );
        $insert->execute([$id, $email, $hash, $name, $firm, $type, $country, $abn, $code, $createdAt]);

        $partner = $this->findById($id);
        $hvaPartnerId = $this->program->apply($partner, !empty($input['marketingConsent']));
        if ($hvaPartnerId !== null) {
            $this->pdo->prepare('UPDATE partners SET hva_partner_id = ? WHERE id = ?')->execute([$hvaPartnerId, $id]);
            $partner = $this->findById($id);
        }
        $sessionId = $this->createSession($id);
        return [
            'ok' => true,
            'status' => 201,
            'sessionId' => $sessionId,
            'body' => ['partner' => partner_public_row($partner)],
        ];
    }

    public function signin(array $input): array
    {
        $email = strtolower(trim((string) ($input['email'] ?? '')));
        $password = (string) ($input['password'] ?? $input['pw'] ?? '');
        if (!partner_valid_email($email) || $password === '') {
            return [
                'ok' => false,
                'status' => 401,
                'body' => ['error' => 'invalid_credentials', 'message' => 'Email or password is incorrect'],
            ];
        }

        $stmt = $this->pdo->prepare('SELECT * FROM partners WHERE email = ? COLLATE NOCASE LIMIT 1');
        $stmt->execute([$email]);
        $row = $stmt->fetch();
        if (!$row || !password_verify($password, $row['password_hash'])) {
            return [
                'ok' => false,
                'status' => 401,
                'body' => ['error' => 'invalid_credentials', 'message' => 'Email or password is incorrect'],
            ];
        }

        $sessionId = $this->createSession($row['id']);
        return [
            'ok' => true,
            'status' => 200,
            'sessionId' => $sessionId,
            'body' => ['partner' => partner_public_row($row)],
        ];
    }

    public function signout(?string $sessionId): array
    {
        if ($sessionId) {
            $stmt = $this->pdo->prepare('DELETE FROM partner_sessions WHERE id = ?');
            $stmt->execute([$sessionId]);
        }
        return ['ok' => true, 'status' => 200, 'body' => ['ok' => true]];
    }

    public function me(?string $sessionId): array
    {
        $partner = $this->partnerFromSession($sessionId);
        if (!$partner) {
            return [
                'ok' => false,
                'status' => 401,
                'body' => ['error' => 'unauthenticated', 'message' => 'Sign in to continue.', 'signinPath' => '/partnership/signin'],
            ];
        }
        return ['ok' => true, 'status' => 200, 'body' => ['partner' => partner_public_row($partner)]];
    }

    /**
     * Live partner-program data (status, referral codes, balance) for the signed-in partner only.
     * The service partner id is read from this server's database, never from the browser.
     */
    public function program(?string $sessionId): array
    {
        $partner = $this->partnerFromSession($sessionId);
        if (!$partner) {
            return ['ok' => false, 'status' => 401, 'body' => ['error' => 'unauthenticated', 'signinPath' => '/partnership/signin']];
        }
        $hvaId = $this->ensureLinked($partner);
        if ($hvaId === null) {
            return ['ok' => true, 'status' => 200, 'body' => ['linked' => false]];
        }
        $summary = $this->program->summary($hvaId);
        if ($summary === null) {
            return ['ok' => true, 'status' => 200, 'body' => ['linked' => true, 'available' => false]];
        }
        return ['ok' => true, 'status' => 200, 'body' => ['linked' => true, 'available' => true] + $summary];
    }

    /** Creates the signed-in partner's referral code once they are approved. */
    public function programCode(?string $sessionId): array
    {
        $partner = $this->partnerFromSession($sessionId);
        if (!$partner) {
            return ['ok' => false, 'status' => 401, 'body' => ['error' => 'unauthenticated']];
        }
        $hvaId = $partner['hva_partner_id'] ?? null;
        if (!is_string($hvaId) || $hvaId === '') {
            return ['ok' => false, 'status' => 409, 'body' => ['error' => 'not_linked']];
        }
        $status = $this->program->createCode($hvaId);
        if ($status === 201) {
            return $this->program($sessionId);
        }
        return ['ok' => false, 'status' => $status === 403 ? 409 : 502, 'body' => [
            'error' => $status === 403 ? 'not_approved' : 'program_unavailable',
            'message' => $status === 403 ? 'Your partner application is still being reviewed.' : 'Please try again later.',
        ]];
    }

    /**
     * Saves the signed-in partner's bank details (sent server-to-server; never stored on this website).
     * They wait for HighVolt admin confirmation before any payout uses them.
     */
    public function programBank(?string $sessionId, array $input): array
    {
        $partner = $this->partnerFromSession($sessionId);
        if (!$partner) {
            return ['ok' => false, 'status' => 401, 'body' => ['error' => 'unauthenticated']];
        }
        $hvaId = $partner['hva_partner_id'] ?? null;
        if (!is_string($hvaId) || $hvaId === '') {
            return ['ok' => false, 'status' => 409, 'body' => ['error' => 'not_linked']];
        }
        $holder = trim((string) ($input['holder'] ?? ''));
        $number = preg_replace('/[\s-]/', '', (string) ($input['accountNumber'] ?? '')) ?? '';
        $code = strtoupper(preg_replace('/[\s-]/', '', (string) ($input['bankCode'] ?? '')) ?? '');
        $errors = [];
        if ($holder === '' || strlen($holder) > 200) {
            $errors['holder'] = 'Enter the account holder name';
        }
        if (!preg_match('/^[0-9]{6,20}$/', $number)) {
            $errors['accountNumber'] = 'Enter 6 to 20 digits';
        }
        if (!preg_match('/^[A-Z0-9]{4,11}$/', $code)) {
            $errors['bankCode'] = 'Enter your BSB, routing number or SWIFT code';
        }
        if ($errors) {
            return ['ok' => false, 'status' => 400, 'body' => ['error' => 'invalid', 'fields' => $errors]];
        }
        $status = $this->program->savePayoutAccount($hvaId, $holder, $number, $code);
        if ($status === 200) {
            return $this->program($sessionId);
        }
        return ['ok' => false, 'status' => in_array($status, [403, 422], true) ? 409 : 502, 'body' => [
            'error' => $status === 403 ? 'not_approved' : ($status === 422 ? 'invalid' : 'program_unavailable'),
            'message' => $status === 403 ? 'Your partner application is still being reviewed.'
                : ($status === 422 ? 'Please check your bank details.' : 'Please try again later.'),
        ]];
    }

    /**
     * Apply again after the partnership was ended. Ending is final for the team; the partner re-opens it by accepting
     * the terms again, and the team approves again. Partner-service re-opens the SAME partner (history, earnings and
     * bank details stay) and is idempotent, so double clicks never create a second application.
     */
    public function programReapply(?string $sessionId, array $input): array
    {
        $partner = $this->partnerFromSession($sessionId);
        if (!$partner) {
            return ['ok' => false, 'status' => 401, 'body' => ['error' => 'unauthenticated']];
        }
        if (($input['acceptTerms'] ?? false) !== true) {
            return ['ok' => false, 'status' => 400, 'body' => [
                'error' => 'terms_required',
                'message' => 'Please accept the partnership terms to apply again.',
            ]];
        }
        $hvaId = $partner['hva_partner_id'] ?? null;
        if (!is_string($hvaId) || $hvaId === '') {
            return ['ok' => false, 'status' => 409, 'body' => ['error' => 'not_linked']];
        }
        $status = $this->program->reapply($hvaId);
        if ($status === 200) {
            return $this->program($sessionId);
        }
        if ($status === 409) {
            return ['ok' => false, 'status' => 409, 'body' => [
                'error' => 'not_ended',
                'message' => 'You can only apply again after your partnership has ended.',
            ]];
        }
        return ['ok' => false, 'status' => 502, 'body' => ['error' => 'program_unavailable', 'message' => 'Please try again later.']];
    }

    /** Retries the link for accounts created while the partner service was unavailable. */
    private function ensureLinked(array $partner): ?string
    {
        $hvaId = $partner['hva_partner_id'] ?? null;
        if (is_string($hvaId) && $hvaId !== '') {
            return $hvaId;
        }
        $hvaId = $this->program->apply($partner);
        if ($hvaId !== null) {
            $this->pdo->prepare('UPDATE partners SET hva_partner_id = ? WHERE id = ? AND hva_partner_id IS NULL')
                ->execute([$hvaId, $partner['id']]);
        }
        return $hvaId;
    }

    /**
     * Read-only partner account list for the HighVolt deployment portal.
     * Caller must already enforce PARTNER_ADMIN_TOKEN.
     */
    public function listForAdmin(): array
    {
        $stmt = $this->pdo->query(
            'SELECT name, email, firm, country, type, created_at
             FROM partners
             ORDER BY created_at DESC, email ASC'
        );
        $partners = [];
        while ($row = $stmt->fetch()) {
            $partners[] = partner_admin_row($row);
        }
        return [
            'ok' => true,
            'status' => 200,
            'body' => [
                'partners' => $partners,
                'count' => count($partners),
            ],
        ];
    }

    private function findById(string $id): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM partners WHERE id = ? LIMIT 1');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            throw new RuntimeException('Partner not found after insert.');
        }
        return $row;
    }

    private function uniqueCode(string $firm): string
    {
        for ($i = 0; $i < 20; $i++) {
            $code = partner_make_code($firm);
            $stmt = $this->pdo->prepare('SELECT id FROM partners WHERE code = ? LIMIT 1');
            $stmt->execute([$code]);
            if (!$stmt->fetch()) {
                return $code;
            }
        }
        return partner_new_id('CODE');
    }

    private function createSession(string $partnerId): string
    {
        $this->pdo->prepare('DELETE FROM partner_sessions WHERE partner_id = ? OR expires_at < ?')
            ->execute([$partnerId, gmdate('c')]);
        $sessionId = bin2hex(random_bytes(32));
        $expires = gmdate('c', time() + partner_session_ttl_seconds());
        $this->pdo->prepare(
            'INSERT INTO partner_sessions (id, partner_id, expires_at, created_at) VALUES (?, ?, ?, ?)'
        )->execute([$sessionId, $partnerId, $expires, gmdate('c')]);
        return $sessionId;
    }

    private function partnerFromSession(?string $sessionId): ?array
    {
        if (!$sessionId) {
            return null;
        }
        $stmt = $this->pdo->prepare(
            'SELECT p.* FROM partner_sessions s
             INNER JOIN partners p ON p.id = s.partner_id
             WHERE s.id = ? AND s.expires_at >= ?
             LIMIT 1'
        );
        $stmt->execute([$sessionId, gmdate('c')]);
        $row = $stmt->fetch();
        return $row ?: null;
    }
}
