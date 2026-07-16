import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import styles from './MarkdownContent.module.css'

interface MarkdownContentProps {
  content: string
}

/**
 * Renders assistant replies as GitHub-flavored Markdown
 * (bold, lists, headings, links, code, tables).
 */
export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className={styles.markdown}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
