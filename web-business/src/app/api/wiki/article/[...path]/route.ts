import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'

export const dynamic = 'force-dynamic'

export async function GET(
  _req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  const articlePath = params.path.join('/')

  try {
    const res = await cairnFetch(
      `/api/wiki/article/${articlePath}`,
      { cache: 'no-store' },
    )
    if (!res.ok) {
      return NextResponse.json({ error: 'Article not found' }, { status: res.status })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'Deek API unavailable' }, { status: 503 })
  }
}
