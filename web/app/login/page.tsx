"use client";
import Link from "next/link";
import { AuthPage, Field } from "@/components/AuthPage";
import { api } from "@/lib/api";

export default function LoginPage() {
  return (
    <AuthPage title="Sign in to your store" intro="See what your recovery calls brought back." submit="Sign in"
      onSubmit={(f) => api.login(String(f.get("email")), String(f.get("password")))}
      footer={<>
        <p>New here? <Link className="link" href="/signup">Create a merchant account</Link></p>
        <p>Just looking? <Link className="link" href="/try">Try the demo without an account</Link></p>
      </>}>
      <Field label="Work email" name="email" type="email" autoComplete="email" placeholder="you@yourstore.com" />
      <Field label="Password" name="password" type="password" autoComplete="current-password" />
    </AuthPage>
  );
}
