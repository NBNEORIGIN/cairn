import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'

export default async function RootPage() {
  // Check for an auth session cookie server-side.
  // Cookie name should match whatever the API sets — adjust as needed.
  const cookieStore = await cookies()
  const sessionCookie =
    cookieStore.get('sessionid') ??
    cookieStore.get('session') ??
    cookieStore.get('auth_token')

  if (sessionCookie) {
    redirect('/dashboard')
  } else {
    redirect('/login')
  }
}
