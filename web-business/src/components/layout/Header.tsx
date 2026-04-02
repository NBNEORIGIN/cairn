'use client'

import { useAuth } from '@/components/auth/AuthProvider'
import { useRouter } from 'next/navigation'

interface HeaderProps {
  title: string
}

const ROLE_BADGE: Record<string, { label: string; className: string }> = {
  staff: {
    label: 'Staff',
    className: 'bg-blue-100 text-blue-700',
  },
  manager: {
    label: 'Manager',
    className: 'bg-amber-100 text-amber-700',
  },
  owner: {
    label: 'Owner',
    className: 'bg-indigo-100 text-indigo-700',
  },
}

export default function Header({ title }: HeaderProps) {
  const { user, logout } = useAuth()
  const router = useRouter()

  const badge = user?.role ? (ROLE_BADGE[user.role] ?? ROLE_BADGE.staff) : ROLE_BADGE.staff
  const firstName = user?.first_name ?? user?.username ?? ''

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    logout()
    router.push('/login')
  }

  return (
    <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-6 fixed top-0 right-0 left-0 z-10" style={{ left: 240 }}>
      <h1 className="text-base font-semibold text-slate-800">{title}</h1>

      <div className="flex items-center gap-3">
        {firstName && (
          <span className="text-sm text-slate-700 font-medium">{firstName}</span>
        )}
        {user?.role && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${badge.className}`}>
            {badge.label}
          </span>
        )}
        <button
          onClick={handleLogout}
          className="text-sm text-slate-500 hover:text-slate-800 transition-colors px-2 py-1 rounded hover:bg-slate-100"
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
