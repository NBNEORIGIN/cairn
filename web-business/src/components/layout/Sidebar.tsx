'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const PRIMARY_NAV = [
  { label: 'Priorities', href: '/dashboard', icon: '📋' },
  { label: 'Ask', href: '/ask', icon: '💬' },
  { label: 'How We Do Things', href: '/processes', icon: '📖' },
]

const SECONDARY_NAV = [
  { label: 'Voice Memos', href: '/voice', icon: '🎙️' },
  { label: 'Documents', href: '/documents', icon: '📄' },
  { label: 'Notes', href: '/notes', icon: '📝' },
]

function NavItem({ item, isActive }: { item: { label: string; href: string; icon: string }; isActive: boolean }) {
  return (
    <li>
      <Link
        href={item.href}
        className={
          'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ' +
          (isActive
            ? 'bg-indigo-50 text-indigo-700'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900')
        }
      >
        <span className="text-base leading-none">{item.icon}</span>
        <span>{item.label}</span>
      </Link>
    </li>
  )
}

export default function Sidebar() {
  const pathname = usePathname()

  return (
    <aside
      className="fixed top-0 left-0 h-full bg-white border-r border-slate-200 flex flex-col"
      style={{ width: 240 }}
    >
      {/* Logo */}
      <div className="h-14 flex items-center px-6 border-b border-slate-200">
        <span className="text-xl font-bold text-slate-900 tracking-tight">NBNE</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3">
        <ul className="space-y-1">
          {PRIMARY_NAV.map((item) => (
            <NavItem
              key={item.href}
              item={item}
              isActive={pathname === item.href || pathname.startsWith(item.href + '/')}
            />
          ))}
        </ul>

        <div className="my-3 border-t border-slate-100" />

        <ul className="space-y-1">
          {SECONDARY_NAV.map((item) => (
            <NavItem
              key={item.href}
              item={item}
              isActive={pathname === item.href || pathname.startsWith(item.href + '/')}
            />
          ))}
        </ul>
      </nav>
    </aside>
  )
}
