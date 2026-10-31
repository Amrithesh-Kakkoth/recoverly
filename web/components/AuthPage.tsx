"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { APP_NAME } from "@/lib/brand";

const input = "h-[2.875rem] rounded-lg border border-line-strong bg-white px-3.5 text-base font-normal text-ink";

export function Field({ label, hint, ...props }: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium">
      {label}
      <input required className={input} {...props} />
      {hint && <span className="text-[0.8125rem] font-normal text-muted">{hint}</span>}
    </label>
  );
}

/** Shared by sign in and sign up: the form on one side, the product's defining moment on the other. */
export function AuthPage({ title, intro, submit, onSubmit, children, footer }: {
  title: string;
  intro: string;
  submit: string;
  onSubmit: (form: FormData) => Promise<unknown>;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handle(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(new FormData(e.currentTarget));
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-wrap">
      <main className="box-border flex flex-[1_1_26rem] flex-col justify-center px-[clamp(1.5rem,7vw,6.5rem)] py-12">
        <p className="mb-16 text-lg font-bold tracking-tight">{APP_NAME}</p>
        <h1 className="mb-2 text-[2.5rem] font-semibold leading-tight tracking-[-0.025em]">{title}</h1>
        <p className="mb-9 text-[1.0625rem] text-muted">{intro}</p>
        <form onSubmit={handle} className="flex max-w-[26rem] flex-col gap-5">
          {children}
          {error && <p role="alert" className="text-sm text-[#7a3410]">{error}</p>}
          <button disabled={busy} className="h-[2.875rem] cursor-pointer rounded-lg bg-ink font-semibold text-on-ink disabled:opacity-60">{submit}</button>
        </form>
        <div className="mt-6 space-y-2 text-[0.9375rem] text-muted">{footer}</div>
      </main>
      <aside aria-label="What a recovery call looks like" className="box-border flex flex-[1_1_26rem] flex-col justify-center bg-ink px-[clamp(1.5rem,5vw,5rem)] py-12 text-on-ink">
        <p className="mb-6 font-mono text-[0.8125rem] text-[#a6b3ac]">Live call · abandoned checkout</p>
        <div className="flex max-w-[32rem] flex-col gap-6 text-[1.375rem] leading-snug">
          <p className="text-on-ink-muted">“I got distracted at the payment page. Can you send it again?”</p>
          <p>“Of course. I've sent the link to your WhatsApp, and I'll stay on the line.”</p>
          <p className="self-start rounded-lg bg-paypal px-3.5 py-2.5 font-mono text-sm text-white">PayPal · payment captured · $49.00</p>
          <p>“Your payment of $49 just came through. Thank you!”</p>
        </div>
      </aside>
    </div>
  );
}
