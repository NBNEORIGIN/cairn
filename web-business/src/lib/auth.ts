export const AUTH_COOKIE_NAME = 'nbne_access';
export const REFRESH_COOKIE_NAME = 'nbne_refresh';

/**
 * Decode a JWT payload without verification.
 * Safe for client-side expiry checks only — not for authorization.
 */
export function decodeJWT(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    // Base64url → Base64 → decode
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const decoded = Buffer.from(padded, 'base64').toString('utf-8');
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Returns true if the token is expired or cannot be decoded.
 * Uses the `exp` claim (Unix seconds). Adds a 10-second clock-skew buffer.
 */
export function isTokenExpired(token: string): boolean {
  const payload = decodeJWT(token);
  if (!payload) return true;
  const exp = payload['exp'];
  if (typeof exp !== 'number') return true;
  return Date.now() / 1000 > exp - 10;
}
