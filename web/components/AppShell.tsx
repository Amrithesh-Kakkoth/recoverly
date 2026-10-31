"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { APP_NAME } from "@/lib/brand";
import type { Merchant } from "@/lib/types";

const NAV = [
  { href: "/", label: "Runs", active: (p: string) => p === "/" || p.startsWith("/runs") },
  { href: "/journeys", label: "Journeys", active: (p: string) => p.startsWith("/journeys") },
  { href: "/settings", label: "Settings", active: (p: string) => p.startsWith("/settings") },
  { href: "/try", label: "Try it", active: () => false },
];

/** Every dashboard page sits inside this: no session sends you to sign in. The API enforces it either way. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [merchant, setMerchant] = useState<Merchant | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setMerchant).catch((e) => {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setError(e.message);
    });
  }, [router]);

  async function signOut() {
    await api.logout().catch(() => {});
    router.replace("/login");
  }

  if (error) return <p className="p-8 text-[#7a3410]">Can't reach the server: {error}</p>;
  if (!merchant) return null;

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 bg-ink px-[clamp(1rem,4vw,3rem)] py-3.5 text-on-ink">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
          <Link href="/" className="text-[1.0625rem] font-bold">{APP_NAME}</Link>
          <nav aria-label="Main" className="flex gap-1 text-[0.9375rem]">
            {NAV.map((n) => {
              const active = n.active(pathname);
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3.5 py-2.5 ${active ? "bg-[#2a3631] text-white" : "text-on-ink-muted hover:text-white"}`}>{n.label}</Link>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center gap-4 text-[0.9375rem]">
          <span className="text-on-ink-muted">{merchant.store_name}</span>
          <button onClick={signOut} className="cursor-pointer py-2.5 text-white underline underline-offset-2">Sign out</button>
        </div>
      </header>
      <main className="mx-auto box-border max-w-[84rem] px-[clamp(1rem,4vw,3rem)] pb-12 pt-10">{children}</main>
    </>
  );
}
