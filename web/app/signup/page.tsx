"use client";
import Link from "next/link";
import { AuthPage, Field } from "@/components/AuthPage";
import { api } from "@/lib/api";

export default function SignupPage() {
  return (
    <AuthPage title="Create your store's account" intro="You'll start with a working recovery journey you can change later." submit="Create account"
      onSubmit={(f) => api.signup(String(f.get("email")), String(f.get("password")), String(f.get("store")))}
      footer={<p>Already have an account? <Link className="link" href="/login">Sign in</Link></p>}>
      <Field label="Store name" name="store" autoComplete="organization" maxLength={120} hint="The agent says this name when it calls your customers." />
      <Field label="Work email" name="email" type="email" autoComplete="email" placeholder="you@yourstore.com" />
      <Field label="Password" name="password" type="password" autoComplete="new-password" minLength={10} hint="At least 10 characters. There's no password reset yet, so keep it safe." />
    </AuthPage>
  );
}
