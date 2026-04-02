import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import { CAIRN_API_URL, CAIRN_API_KEY } from '@/lib/api';
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth';

export async function GET(req: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!accessToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  if (isTokenExpired(accessToken)) {
    return NextResponse.json({ error: 'Token expired' }, { status: 401 });
  }

  // Forward all query parameters as-is
  const incomingSearch = req.nextUrl.searchParams.toString();
  const upstreamUrl = `${CAIRN_API_URL}/chat/stream${incomingSearch ? `?${incomingSearch}` : ''}`;

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstreamUrl, {
      headers: {
        'X-API-Key': CAIRN_API_KEY,
        Accept: 'text/event-stream',
      },
      // Disable Next.js fetch cache — SSE must always be live
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json(
      { error: 'Cairn API unavailable' },
      { status: 503 },
    );
  }

  if (!upstreamRes.ok) {
    return NextResponse.json(
      { error: `Upstream error: ${upstreamRes.status}` },
      { status: upstreamRes.status },
    );
  }

  if (!upstreamRes.body) {
    return NextResponse.json(
      { error: 'No response body from upstream' },
      { status: 502 },
    );
  }

  return new NextResponse(upstreamRes.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no', // disable nginx proxy buffering for SSE
    },
  });
}
