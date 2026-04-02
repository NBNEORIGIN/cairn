import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { phloeFetch } from '@/lib/api';
import { AUTH_COOKIE_NAME } from '@/lib/auth';

export async function GET() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!accessToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  let phloeRes: Response;
  try {
    phloeRes = await phloeFetch('/api/auth/me/', {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    return NextResponse.json(
      { error: 'Authentication service unavailable' },
      { status: 503 },
    );
  }

  if (phloeRes.status === 401) {
    return NextResponse.json({ error: 'Token invalid or expired' }, { status: 401 });
  }

  if (!phloeRes.ok) {
    return NextResponse.json(
      { error: 'Failed to fetch user profile' },
      { status: 502 },
    );
  }

  const user = await phloeRes.json();
  return NextResponse.json(user);
}
