import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  deleteConversation,
  getConversation,
  listConversations,
  streamChat,
} from '../api/client.js'
import { BackendSelect, ErrorBox, Spinner, formatDate } from '../components/common.jsx'
import Icon from '../components/Icon.jsx'
import Button from '../components/ui/Button.jsx'
import { useConfirm } from '../components/ui/Confirm.jsx'
import Markdown from '../components/Markdown.jsx'

const SUGGESTIONS = [
  'Explain streaming in Python with a short code example.',
  'What is the fee for the Python course?',
  'Can I pay in instalments? Give me a short table of options.',
  'Write a checklist for preparing for a data science interview.',
]

export default function Chat() {
  const { conversationId } = useParams() // undefined = a new conversation
  const navigate = useNavigate()
  const confirm = useConfirm()

  const [conversations, setConversations] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [backend, setBackend] = useState('hosted')
  const [streaming, setStreaming] = useState(false)
  const [loadingChat, setLoadingChat] = useState(false)
  const [error, setError] = useState(null)

  const abortRef = useRef(null)
  const skipLoadFor = useRef(null) // the id of a conversation this page is itself streaming into
  const bottomRef = useRef(null)
  const stickRef = useRef(true) // follow new text only while the reader is at the bottom
  const textareaRef = useRef(null)

  const refreshList = useCallback(() => {
    listConversations()
      .then((d) => setConversations(d.items))
      .catch(setError)
  }, [])
  useEffect(refreshList, [refreshList])

  // Open a stored conversation. A conversation that was just created by streaming already has
  // its messages on screen, so it is not loaded again.
  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      return
    }
    if (skipLoadFor.current === conversationId) {
      skipLoadFor.current = null
      return
    }
    let cancelled = false
    setLoadingChat(true)
    setError(null)
    getConversation(conversationId)
      .then((d) => !cancelled && setMessages(d.messages))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoadingChat(false))
    return () => {
      cancelled = true
    }
  }, [conversationId])

  // Leaving the page stops a running answer: the API then also stops the call to the model.
  // (Only on unmount: a new conversation changes the URL while its own answer is streaming.)
  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    if (stickRef.current) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  function onScroll(e) {
    const el = e.currentTarget
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  function grow(el) {
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  async function send(override) {
    const text = (typeof override === 'string' ? override : input).trim()
    if (!text || streaming) return
    stickRef.current = true
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setError(null)
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let started = false

    setMessages((m) => [
      ...m,
      { role: 'user', content: text, status: 'complete' },
      { role: 'assistant', content: '', status: 'streaming' },
    ])
    const patchLast = (fn) =>
      setMessages((m) => {
        const copy = m.slice()
        copy[copy.length - 1] = fn(copy[copy.length - 1])
        return copy
      })

    try {
      await streamChat({
        message: text,
        conversationId,
        backend,
        signal: controller.signal,
        on: {
          start: (d) => {
            started = true
            if (!conversationId) {
              skipLoadFor.current = d.conversation_id
              navigate(`/chat/${d.conversation_id}`, { replace: true })
            }
            patchLast((a) => ({ ...a, model: d.model }))
          },
          token: (d) => patchLast((a) => ({ ...a, content: a.content + d.text })),
          done: (d) =>
            patchLast((a) => ({
              ...a,
              status: 'complete',
              stop_reason: d.stop_reason,
              input_tokens: d.input_tokens,
              output_tokens: d.output_tokens,
            })),
          error: (d) => patchLast((a) => ({ ...a, status: 'error', errorMessage: d.message })),
        },
      })
    } catch (err) {
      if (err.name === 'AbortError') {
        patchLast((a) => ({ ...a, status: 'cancelled' }))
      } else {
        setError(err)
        if (!started) {
          // Nothing was stored by the server: take the two placeholder messages back.
          setMessages((m) => m.slice(0, -2))
          setInput(text)
        } else {
          patchLast((a) => ({ ...a, status: 'error', errorMessage: err.message }))
        }
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      refreshList()
    }
  }

  async function remove(id) {
    const ok = await confirm({
      title: 'Delete this conversation?',
      message: 'The messages are removed for good.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteConversation(id)
      if (id === conversationId) navigate('/chat')
      refreshList()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="chat">
      <aside className="chat-list">
        <Button variant="primary" icon="plus" onClick={() => navigate('/chat')} disabled={streaming}>
          New chat
        </Button>
        <ul>
          {conversations.map((c) => (
            <li key={c.id} className={c.id === conversationId ? 'active' : ''}>
              <button className="item" onClick={() => navigate(`/chat/${c.id}`)} disabled={streaming}>
                <span className="title">{c.title || 'Untitled'}</span>
                <span className="muted small">{formatDate(c.updated_at)}</span>
              </button>
              <button className="icon" title="Delete" aria-label="Delete conversation" onClick={() => remove(c.id)} disabled={streaming}>
                <Icon name="trash" size={16} />
              </button>
            </li>
          ))}
          {conversations.length === 0 && <li className="muted pad">No conversations yet.</li>}
        </ul>
      </aside>

      <section className="chat-main">
        <div className="messages" onScroll={onScroll}>
          <div className="thread">
            {loadingChat && <Spinner label="Loading conversation…" />}
            {!loadingChat && messages.length === 0 && (
              <div className="empty">
                <div className="logo">
                  <Icon name="sparkle" size={28} />
                </div>
                <h2>How can I help?</h2>
                <p className="muted">Ask a question. The answer streams in as it is written.</p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => send(s)} disabled={streaming}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <Message key={m.id ?? i} message={m} />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="chat-error">
          <ErrorBox error={error} />
        </div>

        <div className="composer-wrap">
          <div className="composer">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                grow(e.target)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder="Message the assistant…"
              rows={1}
              maxLength={8000}
            />
            <div className="composer-row">
              <BackendSelect value={backend} onChange={setBackend} direction="up" size="sm" />
              {streaming ? (
                <button className="danger send" onClick={() => abortRef.current?.abort()} title="Stop" aria-label="Stop">
                  <Icon name="stop" size={16} />
                </button>
              ) : (
                <button className="primary send" onClick={() => send()} disabled={!input.trim()} title="Send" aria-label="Send">
                  <Icon name="send" size={18} />
                </button>
              )}
            </div>
          </div>
          <div className="composer-hint">Enter sends · Shift+Enter adds a line</div>
        </div>
      </section>
    </div>
  )
}

function Message({ message: m }) {
  const [copied, setCopied] = useState(false)
  if (m.role === 'user') {
    return (
      <div className="message mine">
        <div className="bubble">{m.content}</div>
      </div>
    )
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(m.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked */
    }
  }
  const waiting = m.status === 'streaming' && !m.content
  return (
    <div className="message theirs">
      <div className="avatar-ai">
        <Icon name="sparkle" size={16} />
      </div>
      <div className="body">
        {waiting ? (
          <div className="typing" aria-label="The assistant is thinking">
            <span />
            <span />
            <span />
          </div>
        ) : (
          <>
            <Markdown>{m.content}</Markdown>
            {m.status === 'streaming' && <span className="caret" />}
          </>
        )}
        <div className="meta muted small">
          {m.status === 'cancelled' && <span className="badge warn">stopped</span>}
          {m.status === 'error' && <span className="badge bad">{m.errorMessage || 'the answer failed'}</span>}
          {m.content && m.status !== 'streaming' && (
            <button className="icon" onClick={copy} title="Copy the answer">
              <Icon name="copy" size={14} /> {copied ? 'Copied' : 'Copy'}
            </button>
          )}
          {m.model && <span>{m.model}</span>}
          {m.output_tokens != null && (
            <span>
              {m.input_tokens ?? '?'} in / {m.output_tokens} out tokens
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
