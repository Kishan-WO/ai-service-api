import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import Chat from './pages/Chat.jsx'
import Documents from './pages/Documents.jsx'
import Extract from './pages/Extract.jsx'
import Login from './pages/Login.jsx'
import RouterPlayground from './pages/RouterPlayground.jsx'
import Summarise from './pages/Summarise.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/chat" element={<Chat />} />
        <Route path="/chat/:conversationId" element={<Chat />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/summarise" element={<Summarise />} />
        <Route path="/extract" element={<Extract />} />
        <Route path="/route" element={<RouterPlayground />} />
      </Route>
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  )
}
