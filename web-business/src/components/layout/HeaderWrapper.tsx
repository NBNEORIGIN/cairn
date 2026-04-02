'use client'

import { usePathname } from 'next/navigation'
import Header from './Header'

const PATH_TITLES: Record<string, string> = {
  '/dashboard': "Today's Priorities",
  '/ask': 'Ask',
  '/processes': 'How We Do Things',
  '/voice': 'Voice Memos',
  '/documents': 'Documents',
  '/notes': 'Notes',
}

export default function HeaderWrapper() {
  const pathname = usePathname()
  const title = PATH_TITLES[pathname] ?? 'NBNE'
  return <Header title={title} />
}
