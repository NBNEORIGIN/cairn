import { NextRequest, NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.DEEK_API_KEY || ''

const apiHeaders = () => ({
  'X-API-Key': CLAW_KEY,
  'Content-Type': 'application/json',
})

// GET /api/subprojects?project=phloe
export async function GET(req: NextRequest) {
  const project = req.nextUrl.searchParams.get('project')
  if (!project) {
    return NextResponse.json({ error: 'project param required' }, { status: 400 })
  }

  try {
    const r = await fetch(
      `${CLAW_API}/projects/${encodeURIComponent(project)}/subprojects`,
      { headers: apiHeaders(), signal: AbortSignal.timeout(5000), cache: 'no-store' },
    )
    if (!r.ok) return NextResponse.json({ error: `API ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}

// POST /api/subprojects
// body: { project, name, display_name, description }
export async function POST(req: NextRequest) {
  const body = await req.json()
  const { project, ...subprojectBody } = body

  if (!project) {
    return NextResponse.json({ error: 'project field required' }, { status: 400 })
  }

  try {
    const r = await fetch(
      `${CLAW_API}/projects/${encodeURIComponent(project)}/subprojects`,
      {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify(subprojectBody),
        signal: AbortSignal.timeout(5000),
      },
    )
    if (!r.ok) return NextResponse.json({ error: `API ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
