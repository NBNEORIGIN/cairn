import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'NBNE',
  description: 'NBNE Business Brain',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-slate-50 antialiased">{children}</body>
    </html>
  )
}
