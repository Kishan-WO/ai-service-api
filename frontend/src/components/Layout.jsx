import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import { useTheme } from '../theme.js'
import Icon from './Icon.jsx'

const LINKS = [
  { to: '/chat', label: 'Chat', icon: 'chat' },
  { to: '/documents', label: 'Documents', icon: 'docs' },
  { to: '/summarise', label: 'Summarise', icon: 'summarise' },
  { to: '/extract', label: 'Extract', icon: 'extract' },
  { to: '/route', label: 'Router', icon: 'route' },
]

const THEME_LABEL = { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' }

export default function Layout() {
  const { me, logout } = useAuth()
  const { mode, cycle } = useTheme()
  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <span className="logo">
            <Icon name="sparkle" size={18} />
          </span>
          AI Service
        </div>
        {LINKS.map((l) => (
          <NavLink key={l.to} to={l.to} className={({ isActive }) => `nav${isActive ? ' active' : ''}`}>
            <Icon name={l.icon} />
            <span>{l.label}</span>
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="who">
          <div className="avatar">{me.user.email[0].toUpperCase()}</div>
          <div className="who-text">
            <div>{me.user.email}</div>
            <div className="muted small">{me.tenant.name}</div>
          </div>
          <button className="icon" onClick={cycle} title={THEME_LABEL[mode]} aria-label={THEME_LABEL[mode]}>
            <Icon name={mode === 'dark' ? 'moon' : 'sun'} />
          </button>
          <button className="icon" onClick={logout} title="Sign out" aria-label="Sign out">
            <Icon name="logout" />
          </button>
        </div>
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
