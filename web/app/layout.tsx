import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Recoverly";

export const metadata: Metadata = { title: APP_NAME, description: "Voice callbacks that recover abandoned checkouts" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3">
            <Link href="/" className="font-semibold tracking-tight">{APP_NAME}</Link>
            <nav className="flex gap-4 text-sm text-muted"><Link href="/" className="hover:text-ink">Dashboard</Link><Link href="/try" className="hover:text-ink">Try it</Link></nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-5 py-8">{children}</main>
      </body>
    </html>
  );
}
