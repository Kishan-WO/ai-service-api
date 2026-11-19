import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import { ErrorBox } from '../components/common.jsx'
import Icon from '../components/Icon.jsx'
import Button from '../components/ui/Button.jsx'

export default function Login() {
  const { me, signIn, signUp } = useAuth()
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [tenantName, setTenantName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (me) return <Navigate to="/chat" replace />

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await signIn(email, password)
      else await signUp(email, password, tenantName)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center">
      <form className="card auth" onSubmit={submit}>
        <div className="auth-brand">
          <span className="logo">
            <Icon name="sparkle" size={18} />
          </span>
          <h1>AI Service</h1>
        </div>
        <p className="muted">Chat, summarise and extract with your own documents.</p>
        <div className="tabs">
          <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>
            Sign in
          </button>
          <button type="button" className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>
            Create account
          </button>
        </div>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={mode === 'register' ? 8 : undefined}
            required
          />
        </label>
        {mode === 'register' && (
          <label>
            Organisation name
            <input value={tenantName} onChange={(e) => setTenantName(e.target.value)} required maxLength={255} />
            <span className="hint">A new account creates its own organisation. Documents and chats are private to it.</span>
          </label>
        )}
        <ErrorBox error={error} />
        <Button type="submit" variant="primary" className="block" loading={busy}>
          {mode === 'login' ? 'Sign in' : 'Create account'}
        </Button>
      </form>
    </div>
  )
}
