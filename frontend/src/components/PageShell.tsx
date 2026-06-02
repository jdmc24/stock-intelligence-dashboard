import type { ReactNode } from "react";

type PageShellProps = {
  children: ReactNode;
  /** content = max-w-5xl (most pages); wide = max-w-7xl (Ask home) */
  width?: "content" | "wide";
  className?: string;
  mainClassName?: string;
};

export function PageShell({
  children,
  width = "content",
  className = "",
  mainClassName = "",
}: PageShellProps) {
  const maxClass = width === "wide" ? "max-w-7xl" : "max-w-5xl";
  return (
    <div className={`page-canvas flex min-h-0 flex-1 flex-col ${className}`}>
      <main
        className={`app-shell mx-auto w-full flex-1 ${maxClass} px-4 py-8 sm:px-6 lg:px-8 ${mainClassName}`}
      >
        {children}
      </main>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <header className={`max-w-3xl ${className}`}>
      {eyebrow ? (
        <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
        {title}
      </h1>
      {description ? (
        <p className="mt-3 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{description}</p>
      ) : null}
    </header>
  );
}
