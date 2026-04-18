/**
 * Deek web auth helper — validates CRM-issued NextAuth session cookies.
 *
 * The CRM (crm.nbnesigns.co.uk) uses NextAuth v4 with JWT strategy. It
 * sets a session cookie scoped to `.nbnesigns.co.uk` so Deek subdomains
 * can see it.
 *
 * NextAuth v4 JWTs are actually JWEs (encrypted, not just signed). The
 * encryption key is derived from NEXTAUTH_SECRET via HKDF with a fixed
 * info string. We replicate that derivation here so we can decrypt the
 * cookie without running the full NextAuth library.
 *
 * See: https://github.com/nextauthjs/next-auth/blob/v4/packages/next-auth/src/jwt/index.ts
 *
 * Both deek-web and the CRM must share the same NEXTAUTH_SECRET env var.
 */
import { cookies } from 'next/headers'
import { jwtDecrypt } from 'jose'
import { hkdf } from '@panva/hkdf'

// NextAuth v4 uses this info string when deriving the encryption key.
const HKDF_INFO = 'NextAuth.js Generated Encryption Key'

// In production the cookie is prefixed with __Secure-. In dev/test it's not.
const SECURE_COOKIE_NAME = '__Secure-next-auth.session-token'
const PLAIN_COOKIE_NAME = 'next-auth.session-token'

export interface DeekSession {
  id: string
  email?: string
  name?: string | null
  role: 'ADMIN' | 'PM' | 'STAFF' | 'READONLY' | 'CLIENT' | string
  clientBusinessId?: string | null
  iat?: number
  exp?: number
}

let _derivedKeyCache: Uint8Array | null = null

async function deriveKey(): Promise<Uint8Array> {
  const secret = process.env.NEXTAUTH_SECRET || ''
  if (!secret) {
    throw new Error(
      'NEXTAUTH_SECRET is not set on the deek-web container — cannot ' +
        'verify CRM session cookies.'
    )
  }
  if (_derivedKeyCache) return _derivedKeyCache
  _derivedKeyCache = await hkdf(
    'sha256',
    secret,
    '',           // no salt (NextAuth v4 default)
    HKDF_INFO,
    32,           // 256-bit key for A256GCM
  )
  return _derivedKeyCache
}

export async function getSessionFromCookie(
  cookieValue: string | undefined,
): Promise<DeekSession | null> {
  if (!cookieValue) return null
  try {
    const key = await deriveKey()
    const { payload } = await jwtDecrypt(cookieValue, key, {
      clockTolerance: 15,
    })
    const p = payload as any
    if (!p.id && !p.sub) return null
    const role = (p.role as string) || 'READONLY'
    return {
      id: (p.id || p.sub) as string,
      email: p.email as string | undefined,
      name: (p.name as string | null) ?? null,
      role,
      clientBusinessId: (p.clientBusinessId as string | null) ?? null,
      iat: p.iat as number | undefined,
      exp: p.exp as number | undefined,
    }
  } catch {
    // Malformed, expired, or signed with a different secret
    return null
  }
}

/** Read the session from the current request's cookies (server components + route handlers). */
export async function getServerSession(): Promise<DeekSession | null> {
  const cookieStore = cookies()
  const cookieValue =
    cookieStore.get(SECURE_COOKIE_NAME)?.value ||
    cookieStore.get(PLAIN_COOKIE_NAME)?.value
  return getSessionFromCookie(cookieValue)
}

// ── Location ACL ────────────────────────────────────────────────────────────
// Which roles can see which location's data.

const LOCATION_ACCESS: Record<string, ReadonlyArray<string>> = {
  workshop: ['ADMIN', 'PM', 'STAFF'],
  office: ['ADMIN', 'PM', 'STAFF', 'READONLY'],
  home: ['ADMIN', 'PM'],  // financial — owners/managers only
}

export function canAccessLocation(
  session: DeekSession | null,
  location: string,
): boolean {
  if (!session) return false
  const allowed = LOCATION_ACCESS[location] || []
  return allowed.includes(session.role)
}

/** Human-readable reason a role cannot access a location, or null if OK. */
export function locationDenyReason(
  session: DeekSession | null,
  location: string,
): string | null {
  if (!session) return 'Not signed in.'
  if (canAccessLocation(session, location)) return null
  if (location === 'home') {
    return 'Home view shows financial data — restricted to ADMIN and PM roles.'
  }
  return `Your role (${session.role}) does not have access to the ${location} view.`
}

export const CRM_LOGIN_URL =
  process.env.CRM_LOGIN_URL || 'https://crm.nbnesigns.co.uk/login'

/** Build a redirect URL to the CRM login with a callback back to here. */
export function buildLoginUrl(callbackUrl: string): string {
  const cb = encodeURIComponent(callbackUrl)
  return `${CRM_LOGIN_URL}?callbackUrl=${cb}`
}
