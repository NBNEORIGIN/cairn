import { NextRequest, NextResponse } from 'next/server'

const CLAW_API_URL = process.env.CLAW_API_URL || 'http://localhost:8765'
const DEEK_API_KEY = process.env.DEEK_API_KEY || ''

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()

    const res = await fetch(`${CLAW_API_URL}/chat/stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': DEEK_API_KEY,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    })

    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json(
      { error: `Cannot reach DEEK API: ${err}` },
      { status: 502 }
    )
  }
}
