import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Cairn — Sovereign AI Agent',
  description: 'Sovereign AI agent for NBNE',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  )
}
