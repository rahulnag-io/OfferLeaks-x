import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OfferLeaks",
  description: "Know if that offer letter is real before you act on it.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        {children}
      </body>
    </html>
  );
}
