import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Onboarding from './pages/Onboarding.jsx'
import Overview from './pages/Overview.jsx'
import Spending from './pages/Spending.jsx'
import Budgets from './pages/Budgets.jsx'
import Goals from './pages/Goals.jsx'
import Guards from './pages/Guards.jsx'
import Inventory from './pages/Inventory.jsx'
import Settings from './pages/Settings.jsx'
import Chat from './pages/Chat.jsx'

function RequireAuth({ children }) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <Login />}
      />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Overview />} />
        <Route path="spending" element={<Spending />} />
        <Route path="budgets" element={<Budgets />} />
        <Route path="goals" element={<Goals />} />
        <Route path="guards" element={<Guards />} />
        <Route path="inventory" element={<Inventory />} />
        <Route path="settings" element={<Settings />} />
        <Route path="chat" element={<Chat />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
