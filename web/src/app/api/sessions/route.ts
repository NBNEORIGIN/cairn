import { NextRequest, NextResponse } from 'next/server'

const CLAW_API = process.env.CLAW_API_URL || 'http://localhost:8765'
const CLAW_KEY = process.env.CLAW_API_KEY || ''

const headers = () => ({
  'X-API-Key': CLAW_KEY,
  'Content-Type': 'application/json',
})

// GET /api/sessions?project=phloe&subproject=phloe%3Ademnurse.nbne.uk
export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl
  const project = searchParams.get('project')
  const subproject = searchParams.get('subproject')

  if (!project) {
    return NextResponse.json({ error: 'project param required' }, { status: 400 })
  }

  const qs = subproject ? `?subproject=${encodeURIComponent(subproject)}` : ''
  try {
    const r = await fetch(
      `${CLAW_API}/projects/${encodeURIComponent(project)}/sessions${qs}`,
      { headers: headers(), signal: AbortSignal.timeout(5000), cache: 'no-store' },
    )
    if (!r.ok) return NextResponse.json({ error: `API ${r.status}` }, { status: r.status })
    return NextResponse.json(await r.json())
  } catch {
    return NextResponse.json({ error: 'API offline' }, { status: 503 })
  }
}
