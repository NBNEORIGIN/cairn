import { NextRequest, NextResponse } from 'next/server'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const res = await fetch(`${DEEK_API_URL}/api/deek/chat/voice`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': DEEK_API_KEY,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(60_000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json(
      {
        response:
          'Deek is offline. Check your connection and try again in a moment.',
        model_used: '',
        cost_usd: 0,
        latency_ms: 0,
        outcome: 'backend_error',
      },
      { status: 502 }
    )
  }
}
