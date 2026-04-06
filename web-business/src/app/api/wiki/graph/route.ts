import { NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const res = await cairnFetch('/api/wiki/graph', { cache: 'no-store' })
    if (!res.ok) {
      return NextResponse.json({ error: 'Upstream error' }, { status: res.status })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'Cairn API unavailable' }, { status: 503 })
  }
}
