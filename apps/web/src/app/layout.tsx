import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";

import "./globals.css";
import { AuthSessionProvider } from "@/components/auth-session-provider";
import { QueryProvider } from "@/components/query-provider";
import { SessionErrorWatcher } from "@/components/session-error-watcher";

const bodyFont = Inter({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

const displayFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const monoFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OfferLeaks — Verify offer letters before you act on them",
  description: "Know if that offer letter is real before you act on it.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${bodyFont.variable} ${displayFont.variable} ${monoFont.variable}`}>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <AuthSessionProvider>
          <QueryProvider>
            <SessionErrorWatcher />
            {children}
          </QueryProvider>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
