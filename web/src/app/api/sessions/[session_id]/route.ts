import { NextRequest, NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.CLAW_API_KEY || ''

// GET /api/sessions/{session_id}?project=phloe
export async function GET(
  req: NextRequest,
  { params }: { params: { session_id: string } },
) {
  const project = req.nextUrl.searchParams.get('project')
  if (!project) {
    return NextResponse.json({ error: 'project param required' }, { status: 400 })
  }

  try {
    const r = await fetch(
      `${CLAW_API}/projects/${encodeURIComponent(project)}/sessions/${encodeURIComponent(params.session_id)}`,
      {
        headers: { 'X-API-Key': CLAW_KEY },
        signal: AbortSignal.timeout(5000),
        cache: 'no-store',
      },
    )
    if (!r.ok) return NextResponse.json({ error: `API ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
