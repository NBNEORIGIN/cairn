import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import { phloeFetch } from '@/lib/api';
import { AUTH_COOKIE_NAME, REFRESH_COOKIE_NAME } from '@/lib/auth';
import type { User, UserRole } from '@/lib/types';

const ALLOWED_ROLES: UserRole[] = ['staff', 'manager', 'owner'];

const COOKIE_BASE = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax' as const,
  path: '/',
};

export async function POST(req: NextRequest) {
  let body: { username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
  }

  const { username, password } = body;
  if (!username || !password) {
    return NextResponse.json(
      { error: 'username and password are required' },
      { status: 400 },
    );
  }

  let phloeRes: Response;
  try {
    phloeRes = await phloeFetch('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    return NextResponse.json(
      { error: 'Authentication service unavailable' },
      { status: 503 },
    );
  }

  if (!phloeRes.ok) {
    const status = phloeRes.status === 401 ? 401 : 502;
    return NextResponse.json({ error: 'Invalid credentials' }, { status });
  }

  let data: { access?: string; refresh?: string; user?: User };
  try {
    data = await phloeRes.json();
  } catch {
    return NextResponse.json(
      { error: 'Unexpected response from auth service' },
      { status: 502 },
    );
  }

  const { access, refresh, user } = data;

  if (!access || !refresh || !user) {
    return NextResponse.json(
      { error: 'Incomplete response from auth service' },
      { status: 502 },
    );
  }

  if (!ALLOWED_ROLES.includes(user.role)) {
    return NextResponse.json(
      { error: 'Access denied: insufficient role' },
      { status: 403 },
    );
  }

  const cookieStore = await cookies();
  cookieStore.set(AUTH_COOKIE_NAME, access, {
    ...COOKIE_BASE,
    maxAge: 60 * 60 * 12, // 12 hours — mirrors Django ACCESS_TOKEN_LIFETIME
  });
  cookieStore.set(REFRESH_COOKIE_NAME, refresh, {
    ...COOKIE_BASE,
    maxAge: 60 * 60 * 24 * 30, // 30 days
  });

  return NextResponse.json({ user });
}
