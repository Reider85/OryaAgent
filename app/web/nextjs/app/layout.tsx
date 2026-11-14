import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { Navigation } from '@/components/Navigation';
import './globals.css';
import './skills.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'OryaAgent B-19 Skills UI',
  description: 'Skills management interface for OryaAgent',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Navigation />
        {children}
      </body>
    </html>
  );
}