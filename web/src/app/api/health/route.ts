import { NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'

export async function GET() {
  try {
    const r = await fetch(`${CLAW_API}/health`, {
      signal: AbortSignal.timeout(5000),
      cache: 'no-store',
    })
    if (!r.ok) return NextResponse.json({ error: `API returned ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
