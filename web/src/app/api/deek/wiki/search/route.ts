/**
 * Proxy: GET /api/deek/wiki/search?q=...&top_k=10
 *   → GET ${DEEK_API}/api/wiki/search?q=...&top_k=N
 *
 * Used by the brief surface's "Memory search" panel. The backend
 * /api/wiki/search hits the canonical hybrid retriever (full-text +
 * embedding) over the wiki/memory chunks.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  const url = new URL(req.url)
  const q = (url.searchParams.get('q') || '').trim()
  if (!q) {
    return NextResponse.json({ results: [], query: '' }, { status: 200 })
  }
  const topK = Math.min(
    Math.max(parseInt(url.searchParams.get('top_k') || '10', 10) || 10, 1),
    50,
  )
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/wiki/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ results: [], query: q }, { status: 502 })
  }
}
