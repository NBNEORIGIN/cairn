import { NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.CLAW_API_KEY || ''
let lastGoodStatus: Record<string, unknown> | null = null

export async function GET() {
  try {
    const r = await fetch(`${CLAW_API}/status/summary`, {
      headers: { 'X-API-Key': CLAW_KEY },
      signal: AbortSignal.timeout(12000),
      cache: 'no-store',
    })
    if (!r.ok) {
      if (lastGoodStatus) {
        return NextResponse.json({
          ...lastGoodStatus,
          api_status: 'stale',
          stale: true,
        })
      }
      return NextResponse.json({ error: `API returned ${r.status}` }, { status: r.status })
    }
    const data = await r.json()
    lastGoodStatus = data
    return NextResponse.json(data)
  } catch {
    if (lastGoodStatus) {
      return NextResponse.json({
        ...lastGoodStatus,
        api_status: 'stale',
        stale: true,
      })
    }
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
