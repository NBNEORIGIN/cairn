import AuthProvider from '@/components/auth/AuthProvider'
import Sidebar from '@/components/layout/Sidebar'
import HeaderWrapper from '@/components/layout/HeaderWrapper'

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <AuthProvider>
      <div className="min-h-screen bg-slate-50">
        <Sidebar />
        <HeaderWrapper />
        {/* Main content offset by sidebar width (240px) and header height (56px) */}
        <main
          className="flex-1 overflow-y-auto p-6 bg-slate-50"
          style={{ marginLeft: 240, marginTop: 56 }}
        >
          {children}
        </main>
      </div>
    </AuthProvider>
  )
}
