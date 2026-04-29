/**
 * Deek web — self-contained authentication.
 *
 * Design choices:
 * - Tiny user list from env (DEEK_USERS) rather than a database. Current
 *   user count is 2 (Toby + Jo); a DB is overkill.
 * - Session cookie `deek.session` is a HS256 JWT signed with DEEK_JWT_SECRET.
 *   30-day sliding expiry.
 * - Passwords stored as bcrypt hashes in env (not plaintext).
 * - Role-based Location ACL reuses the same shape the earlier CRM-auth
 *   prototype used — ADMIN/PM see everything, STAFF/READONLY/CLIENT have
 *   progressively less access.
 *
 * DEEK_USERS format (semicolon-separated records, pipe-separated fields):
 *
 *   email|bcrypt_hash|NAME|ROLE
 *
 * Example (with a fake hash):
 *   DEEK_USERS='toby@nbnesigns.com|$2a$10$AbC...|Toby|ADMIN;jo@nbnesigns.com|$2a$10$XyZ...|Jo|ADMIN'
 */
import { cookies } from 'next/headers'
import { SignJWT, jwtVerify } from 'jose'
import bcrypt from 'bcryptjs'

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

interface UserRecord {
  email: string
  passwordHash: string
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

function loadUsers(): UserRecord[] {
  const raw = process.env.DEEK_USERS || ''
  if (!raw.trim()) return []
  return raw
    .split(';')
    .map(r => r.trim())
    .filter(Boolean)
    .map(record => {
      const parts = record.split('|')
      if (parts.length < 4) {
        console.warn('[deek-auth] skipping malformed DEEK_USERS record')
        return null
      }
      const [email, passwordHash, name, role] = parts
      return {
        email: email.trim().toLowerCase(),
        passwordHash: passwordHash.trim(),
        name: name.trim(),
        role: role.trim().toUpperCase() as Role,
      }
    })
    .filter((u): u is UserRecord => u !== null)
}

// ── Login / credentials check ───────────────────────────────────────────────

export async function verifyCredentials(
  email: string,
  password: string,
): Promise<Omit<UserRecord, 'passwordHash'> | null> {
  const lookup = email.trim().toLowerCase()
  const users = loadUsers()
  const user = users.find(u => u.email === lookup)
  if (!user) {
    // Constant-time-ish: still run a bcrypt compare to avoid timing oracle
    await bcrypt.compare(password, '$2a$10$' + '.'.repeat(53))
    return null
  }
  const ok = await bcrypt.compare(password, user.passwordHash)
  if (!ok) return null
  return { email: user.email, name: user.name, role: user.role }
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
