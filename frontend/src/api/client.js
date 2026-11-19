// One place that talks to the API. Every page imports from here, never calls fetch itself.
const BASE = '/api/v1'
const TOKEN_KEY = 'ai-service-token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) =>
  token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)

let onUnauthorized = () => {}
export const setUnauthorizedHandler = (fn) => {
  onUnauthorized = fn
}

// The API answers every error as { error: { code, message, request_id, details } }.
export class ApiError extends Error {
  constructor(status, code, message, details, requestId) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

async function toApiError(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    /* not JSON */
  }
  const e = body?.error
  return new ApiError(
    res.status,
    e?.code ?? `HTTP_${res.status}`,
    e?.message ?? res.statusText ?? 'Request failed',
    e?.details,
    e?.request_id,
  )
}

function networkError(err) {
  if (err instanceof ApiError || err?.name === 'AbortError') return err
  return new ApiError(0, 'NETWORK_ERROR', 'Could not reach the API. Is the server running?')
}

async function request(path, { method = 'GET', json, form, signal, auth = true } = {}) {
  const headers = {}
  const token = getToken()
  if (auth && token) headers.Authorization = `Bearer ${token}`
  let body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  } else if (form) {
    body = form // the browser sets the multipart boundary itself
  }
  let res
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body, signal })
  } catch (err) {
    throw networkError(err)
  }
  if (!res.ok) {
    if (res.status === 401 && auth) onUnauthorized()
    throw await toApiError(res)
  }
  return res.status === 204 ? null : res.json()
}

// ---------- auth
export const register = (email, password, tenantName) =>
  request('/auth/register', {
    method: 'POST',
    json: { email, password, tenant_name: tenantName },
    auth: false,
  })
export const login = (email, password) =>
  request('/auth/login', { method: 'POST', json: { email, password }, auth: false })
export const getMe = () => request('/auth/me')

// ---------- documents
export const listDocuments = (limit = 20, offset = 0) =>
  request(`/documents?limit=${limit}&offset=${offset}`)
export const getDocument = (id) => request(`/documents/${id}`)
export const deleteDocument = (id) => request(`/documents/${id}`, { method: 'DELETE' })
export function uploadDocument(file, title) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  return request('/documents/upload', { method: 'POST', form })
}

// ---------- conversations
export const listConversations = (limit = 50, offset = 0) =>
  request(`/chat/conversations?limit=${limit}&offset=${offset}`)
export const getConversation = (id) => request(`/chat/conversations/${id}`)
export const deleteConversation = (id) => request(`/chat/conversations/${id}`, { method: 'DELETE' })

// ---------- one-shot endpoints
export const extract = (text, backend) =>
  request('/extract', { method: 'POST', json: { text, backend } })
export const route = (message, smallBackend, largeBackend) =>
  request('/route', {
    method: 'POST',
    json: {
      message,
      small_backend: smallBackend,
      ...(largeBackend ? { large_backend: largeBackend } : {}),
    },
  })
export const summarise = (documentIds, backend, concurrency) =>
  request('/summarise', {
    method: 'POST',
    json: { document_ids: documentIds, backend, concurrency },
  })

// ---------- chat: Server-Sent Events over a POST
// EventSource cannot send a POST body or an Authorization header, so the stream is read from
// fetch() and split into events by hand. Events: start, token, done, error (see chat_service.py).
export async function streamChat({ message, conversationId, backend, signal, on }) {
  let res
  try {
    res = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({
        message,
        backend,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      }),
      signal,
    })
  } catch (err) {
    throw networkError(err)
  }
  if (!res.ok) {
    if (res.status === 401) onUnauthorized()
    throw await toApiError(res)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (block) => {
    let event = 'message'
    const data = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (data.length) on[event]?.(JSON.parse(data.join('\n')))
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let split
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      dispatch(buffer.slice(0, split))
      buffer = buffer.slice(split + 2)
    }
  }
  if (buffer.trim()) dispatch(buffer)
}
