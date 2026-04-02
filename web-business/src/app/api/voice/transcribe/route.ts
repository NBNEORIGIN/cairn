import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

export async function POST(req: NextRequest) {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value

  if (!accessToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })
  }
  if (isTokenExpired(accessToken)) {
    return NextResponse.json({ error: 'Token expired' }, { status: 401 })
  }

  const openaiKey = process.env.OPENAI_API_KEY
  if (!openaiKey) {
    return NextResponse.json({ error: 'Transcription not configured' }, { status: 503 })
  }

  let formData: FormData
  try {
    formData = await req.formData()
  } catch {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 })
  }

  const audioFile = formData.get('audio')
  if (!audioFile || !(audioFile instanceof Blob)) {
    return NextResponse.json({ error: 'No audio file provided' }, { status: 400 })
  }

  // Forward to OpenAI Whisper
  const whisperForm = new FormData()
  whisperForm.append('file', audioFile, 'recording.webm')
  whisperForm.append('model', 'whisper-1')

  let whisperRes: Response
  try {
    whisperRes = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${openaiKey}`,
      },
      body: whisperForm,
    })
  } catch {
    return NextResponse.json({ error: 'Transcription service unavailable' }, { status: 503 })
  }

  if (!whisperRes.ok) {
    const errBody = await whisperRes.text().catch(() => '')
    console.error('Whisper error:', whisperRes.status, errBody)
    return NextResponse.json({ error: 'Transcription failed' }, { status: 502 })
  }

  const data = await whisperRes.json()
  return NextResponse.json({ text: data.text ?? '' })
}
