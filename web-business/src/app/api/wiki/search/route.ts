import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get('q') ?? ''
  const topK = req.nextUrl.searchParams.get('top_k') ?? '5'

  try {
    const res = await cairnFetch(
      `/api/wiki/search?q=${encodeURIComponent(q)}&top_k=${topK}`,
      { cache: 'no-store' },
    )
    if (!res.ok) {
      return NextResponse.json({ error: 'Upstream error' }, { status: res.status })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'Deek API unavailable' }, { status: 503 })
  }
}
