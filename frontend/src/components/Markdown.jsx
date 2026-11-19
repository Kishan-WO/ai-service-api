import { Children, isValidElement, memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import remarkGfm from 'remark-gfm'

// The model answers in Markdown (headings, lists, **bold**, tables, fenced code). This turns it
// into real elements. Text is never injected as HTML, so a reply cannot add scripts or styles.

// The text inside a React element tree (the highlighter wraps tokens in nested <span>s).
function toText(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(toText).join('')
  if (isValidElement(node)) return toText(node.props.children)
  return ''
}

function CodeBlock({ children }) {
  const [copied, setCopied] = useState(false)
  const code = Children.toArray(children)[0]
  const className = isValidElement(code) ? (code.props.className ?? '') : ''
  const language = /language-([\w+#-]+)/.exec(className)?.[1]
  const text = toText(code).replace(/\n$/, '')

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* the clipboard can be blocked (an insecure page); nothing else to do */
    }
  }

  return (
    <div className="codeblock">
      <div className="codeblock-bar">
        <span>{language ?? 'text'}</span>
        <button type="button" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  )
}

const components = {
  pre: CodeBlock,
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: ({ node: _node, ...props }) => (
    <div className="table-scroll">
      <table {...props} />
    </div>
  ),
}

const plugins = [remarkGfm]
const rehype = [[rehypeHighlight, { detect: false, ignoreMissing: true }]]

function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={plugins} rehypePlugins={rehype} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}

// Re-render only when the text changes (a streaming answer re-renders on every token).
export default memo(Markdown)
