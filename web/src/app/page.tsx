import { ChatWindow } from '@/components/ChatWindow'

export default function Home() {
  return (
    <main className="min-h-screen p-3 md:p-5">
      <div className="mx-auto flex h-[calc(100vh-1.5rem)] max-w-[1800px] overflow-hidden rounded-[28px] border border-white/70 bg-white/80 shadow-[0_35px_90px_-35px_rgba(15,23,42,0.45)] backdrop-blur-xl md:h-[calc(100vh-2.5rem)]">
        <ChatWindow />
      </div>
    </main>
  )
}
