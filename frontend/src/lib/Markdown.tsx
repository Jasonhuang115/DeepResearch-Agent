import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="md prose-sm [&_h1]:text-base [&_h1]:font-medium [&_h2]:text-[13px] [&_h2]:font-medium [&_h3]:text-[13px] [&_p]:my-2 [&_ul]:my-2 [&_ol]:my-2 [&_li]:my-0.5 [&_table]:w-full [&_th]:text-left [&_th]:border-b [&_th]:border-[#2a2a2a] [&_td]:py-1 [&_td]:pr-3 [&_code]:font-mono [&_pre]:bg-[#0a0a0a] [&_pre]:p-3 [&_pre]:overflow-auto [&_pre]:border [&_pre]:border-[#2a2a2a] [&_a]:underline">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
})
