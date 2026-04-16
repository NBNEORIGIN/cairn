import { NextRequest, NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.DEEK_API_KEY || ''

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ project: string }> },
) {
  const { project } = await params
  try {
    const body = await request.json().catch(() => ({}))
    const r = await fetch(`${CLAW_API}/projects/${project}/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': CLAW_KEY },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    })
    if (!r.ok) return NextResponse.json({ error: `API returned ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ project: string }> },
) {
  const { project } = await params
  try {
    const r = await fetch(`${CLAW_API}/projects/${project}/index`, {
      headers: { 'X-API-Key': CLAW_KEY },
      signal: AbortSignal.timeout(5000),
      cache: 'no-store',
    })
    if (!r.ok) return NextResponse.json({ error: `API returned ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
