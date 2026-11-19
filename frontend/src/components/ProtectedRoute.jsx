import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import { Spinner } from './common.jsx'

export default function ProtectedRoute({ children }) {
  const { me, loading } = useAuth()
  if (loading) return <div className="center"><Spinner label="Loading…" /></div>
  return me ? children : <Navigate to="/login" replace />
}
