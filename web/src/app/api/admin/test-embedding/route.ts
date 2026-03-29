import { NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.CLAW_API_KEY || ''

export async function POST() {
  try {
    const r = await fetch(`${CLAW_API}/admin/test-embedding`, {
      method: 'POST',
      headers: { 'X-API-Key': CLAW_KEY },
      signal: AbortSignal.timeout(15000),
    })
    if (!r.ok) return NextResponse.json({ error: `API returned ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
