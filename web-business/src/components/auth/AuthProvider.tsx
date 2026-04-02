'use client'

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from 'react'
import { useRouter } from 'next/navigation'

export interface AuthUser {
  id: number
  username: string
  first_name?: string
  last_name?: string
  role: 'staff' | 'manager' | 'owner'
  tenant?: string
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  logout: () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    async function checkSession() {
      try {
        const res = await fetch('/api/auth/me', { credentials: 'include' })
        if (res.status === 401) {
          router.push('/login')
          return
        }
        if (!res.ok) {
          router.push('/login')
          return
        }
        const data: AuthUser = await res.json()
        setUser(data)
      } catch {
        router.push('/login')
      } finally {
        setLoading(false)
      }
    }

    checkSession()
  }, [router])

  function logout() {
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout }}>
      {loading ? (
        <div className="min-h-screen bg-slate-50 flex items-center justify-center">
          <p className="text-slate-500 text-sm">Loading…</p>
        </div>
      ) : (
        children
      )}
    </AuthContext.Provider>
  )
}
