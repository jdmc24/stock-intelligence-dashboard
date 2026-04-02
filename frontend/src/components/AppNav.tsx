"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/regulations", label: "Regulations" },
  { href: "/compare", label: "Compare" },
  { href: "/search", label: "Search" },
];

export function AppNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-zinc-200/90 bg-white/85 backdrop-blur-md dark:border-zinc-800/90 dark:bg-zinc-950/85">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
        <Link href="/" className="group flex min-w-0 items-center gap-3">
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-700 shadow-md shadow-teal-600/25 ring-1 ring-white/25 dark:from-teal-400 dark:to-emerald-700 dark:shadow-teal-900/40"
            aria-hidden
          >
            <span className="font-mono text-xs font-bold tracking-tight text-white">EC</span>
          </span>
          <span className="truncate text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Earnings Call Analyzer
          </span>
        </Link>
        <nav className="flex shrink-0 items-center gap-0.5 sm:gap-1" aria-label="Main">
          {links.map(({ href, label }) => {
            const active =
              href === "/"
                ? pathname === "/"
                : pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={`rounded-lg px-2.5 py-2 text-sm font-medium transition-colors sm:px-3 ${
                  active
                    ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-white"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900/60 dark:hover:text-zinc-100"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
