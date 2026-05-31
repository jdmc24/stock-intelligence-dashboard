"use client";

import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  h1: ({ children }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold text-zinc-900 first:mt-0 dark:text-zinc-100">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-2 mt-4 text-base font-semibold text-zinc-900 first:mt-0 dark:text-zinc-100">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-2 mt-3 text-sm font-semibold text-zinc-900 first:mt-0 dark:text-zinc-100">{children}</h4>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-zinc-900 dark:text-zinc-100">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => (
    <a href={href} className="text-teal-700 underline underline-offset-2 dark:text-teal-300">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-zinc-200/90 dark:border-zinc-700">
      <table className="w-full min-w-[420px] border-collapse text-left text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-zinc-200/60 dark:bg-zinc-800">{children}</thead>,
  tbody: ({ children }) => <tbody className="divide-y divide-zinc-200/80 dark:divide-zinc-800">{children}</tbody>,
  tr: ({ children }) => <tr className="even:bg-zinc-50/80 dark:even:bg-zinc-900/40">{children}</tr>,
  th: ({ children }) => (
    <th className="px-3 py-2 font-semibold text-zinc-800 dark:text-zinc-200">{children}</th>
  ),
  td: ({ children }) => <td className="px-3 py-2 align-top text-zinc-700 dark:text-zinc-300">{children}</td>,
  hr: () => <hr className="my-3 border-zinc-200 dark:border-zinc-700" />,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-teal-500/40 pl-3 text-zinc-600 dark:text-zinc-400">
      {children}
    </blockquote>
  ),
};

export function AskAnswerMarkdown({ content }: { content: string }) {
  return (
    <div className="ask-answer-markdown text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
