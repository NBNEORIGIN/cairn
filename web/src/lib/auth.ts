/**
 * Deek web — self-contained authentication.
 *
 * Design choices:
 * - Credentials live in the deek_users table on the API side
 *   (migrated from DEEK_USERS env on 2026-04-30 so password changes
 *   + admin resets can mutate state at runtime). The Next.js layer
 *   POSTs to /api/deek/users/verify and trusts the response — the
 *   API's bcrypt check is the source of truth.
 * - DEEK_USERS env still exists as a SEED fallback: on the API's first
 *   boot after the migration, if deek_users is empty the env is
 *   parsed and the table populated. Subsequent boots ignore the env.
 * - Session cookie `deek.session` is a HS256 JWT signed with DEEK_JWT_SECRET.
 *   30-day sliding expiry.
 * - Role-based Location ACL stays here unchanged — ADMIN/PM see
 *   everything, STAFF/READONLY/CLIENT have progressively less access.
 */
import { cookies } from 'next/headers'
import { SignJWT, jwtVerify } from 'jose'

const COOKIE_NAME = 'deek.session'
const COOKIE_MAX_AGE_SEC = 60 * 60 * 24 * 30 // 30 days
const JWT_ISSUER = 'deek.nbnesigns.co.uk'
const JWT_AUDIENCE = 'deek-voice-pwa'

export type Role = 'ADMIN' | 'PM' | 'STAFF' | 'READONLY' | 'CLIENT'

export interface DeekSession {
  email: string
  name: string
  role: Role
  iat?: number
  exp?: number
}

interface VerifiedUser {
  email: string
  name: string
  role: Role
}

// ── Config loading ──────────────────────────────────────────────────────────

function jwtKey(): Uint8Array {
  const s = process.env.DEEK_JWT_SECRET || process.env.NEXTAUTH_SECRET || ''
  if (!s) {
    throw new Error(
      'DEEK_JWT_SECRET (or NEXTAUTH_SECRET fallback) is not set — cannot ' +
        'sign or verify session cookies.'
    )
  }
  return new TextEncoder().encode(s)
}

function deekApiUrl(): string {
  return (
    process.env.DEEK_API_URL ||
    process.env.CLAW_API_URL ||
    'http://localhost:8765'
  )
}

function deekApiKey(): string {
  return process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''
}

// ── Login / credentials check ───────────────────────────────────────────────
//
// Credentials live in the API's deek_users table. We POST to
// /api/deek/users/verify and trust the API's bcrypt result. The API
// also seeds itself from DEEK_USERS env on first boot so the migration
// from env-as-source to DB-as-source is invisible to operators.

export async function verifyCredentials(
  email: string,
  password: string,
): Promise<VerifiedUser | null> {
  const lookup = email.trim().toLowerCase()
  if (!lookup || !password) return null
  try {
    const res = await fetch(`${deekApiUrl()}/api/deek/users/verify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': deekApiKey(),
      },
      body: JSON.stringify({ email: lookup, password }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    })
    if (res.status === 401) return null
    if (!res.ok) {
      console.warn('[deek-auth] verify upstream HTTP', res.status)
      return null
    }
    const data = (await res.json()) as {
      ok?: boolean
      email?: string
      name?: string
      role?: string
    }
    if (!data?.ok || !data.email) return null
    return {
      email: data.email,
      name: data.name || data.email,
      role: ((data.role || 'READONLY').toUpperCase() as Role),
    }
  } catch (err) {
    console.warn('[deek-auth] verify call failed:', err)
    return null
  }
}

export async function issueSessionToken(user: {
  email: string
  name: string
  role: Role
}): Promise<string> {
  const key = jwtKey()
  return await new SignJWT({
    email: user.email,
    name: user.name,
    role: user.role,
  })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setIssuer(JWT_ISSUER)
    .setAudience(JWT_AUDIENCE)
    .setExpirationTime(`${COOKIE_MAX_AGE_SEC}s`)
    .sign(key)
}

// ── Session verification (called from route handlers & server components) ──

export async function getSessionFromCookie(
  cookieValue: string | undefined,
): Promise<DeekSession | null> {
  if (!cookieValue) return null
  try {
    const { payload } = await jwtVerify(cookieValue, jwtKey(), {
      issuer: JWT_ISSUER,
      audience: JWT_AUDIENCE,
      clockTolerance: 15,
    })
    const p = payload as any
    if (!p.email) return null
    return {
      email: String(p.email),
      name: String(p.name || p.email),
      role: (p.role as Role) || 'READONLY',
      iat: p.iat as number | undefined,
      exp: p.exp as number | undefined,
    }
  } catch {
    return null
  }
}

export async function getServerSession(): Promise<DeekSession | null> {
  const cookieStore = cookies()
  const value = cookieStore.get(COOKIE_NAME)?.value
  return getSessionFromCookie(value)
}

// Cookie options used by /api/voice/login and /api/voice/logout.
export function sessionCookieOptions(maxAge = COOKIE_MAX_AGE_SEC) {
  // Default: Secure cookies in production (browsers drop them on HTTP).
  // Opt-out via DEEK_COOKIE_SECURE=false for tailnet-only HTTP deployments
  // like Rex on jo-pip — traffic is already encrypted by Tailscale, but
  // the application layer is HTTP so Secure cookies would be dropped and
  // login would silently fail on the redirect-back step.
  const optOut = (process.env.DEEK_COOKIE_SECURE || '').toLowerCase() === 'false'
  const secure = optOut ? false : process.env.NODE_ENV === 'production'
  return {
    name: COOKIE_NAME,
    httpOnly: true,
    sameSite: 'lax' as const,
    path: '/',
    secure,
    maxAge,
  }
}

export function clearedCookieOptions() {
  return sessionCookieOptions(0)
}

export const SESSION_COOKIE_NAME = COOKIE_NAME

// ── Location ACL ────────────────────────────────────────────────────────────

const LOCATION_ACCESS: Record<string, ReadonlyArray<Role>> = {
  workshop: ['ADMIN', 'PM', 'STAFF'],
  office: ['ADMIN', 'PM', 'STAFF', 'READONLY'],
  home: ['ADMIN', 'PM'],
}

export function canAccessLocation(
  session: DeekSession | null,
  location: string,
): boolean {
  if (!session) return false
  const allowed = LOCATION_ACCESS[location] || []
  return (allowed as ReadonlyArray<string>).includes(session.role)
}

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

export const LOGIN_PATH = '/voice/login'
