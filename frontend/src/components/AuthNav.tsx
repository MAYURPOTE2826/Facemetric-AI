"use client";

import Link from "next/link";
import { useUser } from "@/lib/auth";

export function AuthNav() {
  const user = useUser();
  if (user === undefined) return null;
  return user ? (
    <Link href="/account" className="text-sm font-medium hover:text-accent">My progress</Link>
  ) : (
    <Link href="/login" className="text-sm font-medium hover:text-accent">Sign in</Link>
  );
}
