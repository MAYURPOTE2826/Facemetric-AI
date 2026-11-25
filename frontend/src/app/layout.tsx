import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import Link from "next/link";
import { AuthNav } from "@/components/AuthNav";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Facemetric-AI — Facial Analysis",
  description: "Measured facial analysis and a personal, non-surgical improvement plan.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${fraunces.variable} font-sans antialiased`}>
        <header className="no-print border-b border-line">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
            <Link href="/" className="font-serif text-2xl tracking-tight">
              Facemetric-AI
            </Link>
            <div className="flex items-center gap-5">
              <AuthNav />
              <Link
                href="/analyze"
                className="rounded-full bg-foreground px-5 py-2 text-sm font-medium text-background hover:opacity-90"
              >
                Start analysis
              </Link>
            </div>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
