import { NextRequest, NextResponse } from 'next/server'
import {
  getServerSession,
  canAccessLocation,
  locationDenyReason,
} from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

export async function GET(req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json(
      { error: 'not_authenticated' },
      { status: 401 },
    )
  }

  const { searchParams } = new URL(req.url)
  const location = searchParams.get('location') || 'workshop'
  const deny = locationDenyReason(session, location)
  if (deny) {
    return NextResponse.json(
      { error: 'forbidden', reason: deny },
      { status: 403 },
    )
  }

  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/deek/ambient?location=${encodeURIComponent(location)}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        signal: AbortSignal.timeout(10_000),
        cache: 'no-store',
      },
    )
    const data = await res.json()
    return NextResponse.json(data, {
      status: res.status,
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (err) {
    return NextResponse.json(
      { error: 'Deek offline', offline: true },
      { status: 502 },
    )
  }
}
