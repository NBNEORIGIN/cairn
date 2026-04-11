import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { phloeFetch } from '@/lib/api';
import { AUTH_COOKIE_NAME, REFRESH_COOKIE_NAME } from '@/lib/auth';

const COOKIE_BASE = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax' as const,
  path: '/',
};

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_COOKIE_NAME)?.value;

  if (!refreshToken) {
    return NextResponse.json({ error: 'No refresh token' }, { status: 401 });
  }

  let phloeRes: Response;
  try {
    phloeRes = await phloeFetch('/api/auth/token/refresh/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: refreshToken }),
    });
  } catch {
    return NextResponse.json(
      { error: 'Authentication service unavailable' },
      { status: 503 },
    );
  }

  if (!phloeRes.ok) {
    // Refresh token is invalid or expired — clear both cookies
    cookieStore.delete(AUTH_COOKIE_NAME);
    cookieStore.delete(REFRESH_COOKIE_NAME);
    return NextResponse.json(
      { error: 'Session expired, please log in again' },
      { status: 401 },
    );
  }

  let data: { access?: string };
  try {
    data = await phloeRes.json();
  } catch {
    return NextResponse.json(
      { error: 'Unexpected response from auth service' },
      { status: 502 },
    );
  }

  if (!data.access) {
    return NextResponse.json(
      { error: 'No access token in refresh response' },
      { status: 502 },
    );
  }

  cookieStore.set(AUTH_COOKIE_NAME, data.access, {
    ...COOKIE_BASE,
    maxAge: 60 * 60 * 12, // 12 hours — mirrors Django ACCESS_TOKEN_LIFETIME
  });

  return NextResponse.json({ success: true });
}
