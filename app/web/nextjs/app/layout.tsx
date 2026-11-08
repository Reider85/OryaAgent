import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { SessionSidebar } from '@/components/SessionSidebar'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'OryaAgent - Chat Interface',
  description: 'Modern chat interface for OryaAgent',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="flex h-screen bg-gray-50">
          <SessionSidebar />
          <main className="flex-1">
            {children}
          </main>
        </div>
      </body>
    </html>
  )
}