import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppNav } from "@/components/AppNav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://stock-intelligence.io"),
  title: "Stock Intelligence Dashboard",
  description:
    "Earnings call transcripts and Federal Register regulatory monitoring with AI summaries — Stock Intelligence Dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans antialiased">
        <AppNav />
        {children}
        <footer className="mt-auto border-t border-zinc-200/80 px-4 py-3 text-center text-[11px] leading-relaxed text-zinc-500 dark:border-zinc-800 dark:text-zinc-500">
          Built by Jake · Questions about this project?{" "}
          <a
            href="mailto:jakedmccorkle@gmail.com"
            className="text-teal-700 underline decoration-teal-700/30 underline-offset-2 hover:text-teal-600 dark:text-teal-400 dark:decoration-teal-400/40 dark:hover:text-teal-300"
          >
            jakedmccorkle@gmail.com
          </a>
        </footer>
      </body>
    </html>
  );
}
