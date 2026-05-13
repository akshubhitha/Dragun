/**
 * api.js — all calls to the Dragun FastAPI backend.
 *
 * Every function throws an Error with a human-readable message on failure,
 * so callers only need a single try/catch.
 */

function getToken() {
  try {
    const session = JSON.parse(localStorage.getItem('dragun_session') || '{}')
    return session.session_token || ''
  } catch {
    return ''
  }
}

async function request(path, opts = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts.headers || {}),
  }
  const res = await fetch(path, { ...opts, headers })
  const body = await res.json()
  if (!res.ok) {
    const detail = body.detail
    if (Array.isArray(detail)) throw new Error(detail.map(e => e.msg).join('; '))
    throw new Error(typeof detail === 'string' ? detail : 'The dragon coughed smoke.')
  }
  return body
}

// ── Auth ──────────────────────────────────────────────────────────────────
export const sendOTP = (email) =>
  request('/api/auth/send-otp', { method: 'POST', body: JSON.stringify({ email }) })

export const verifyOTP = (email, code) =>
  request('/api/auth/verify-otp', { method: 'POST', body: JSON.stringify({ email, code }) })

// ── Users & session ───────────────────────────────────────────────────────
export const getMe = (userId) => request(`/api/users/${userId}/me`)
export const logout = (userId) => request(`/api/users/${userId}/logout`, { method: 'POST' })
export const deleteAccount = (userId) => request(`/api/users/${userId}`, { method: 'DELETE' })
export const hardDeleteAccount = (userId) => request(`/api/users/${userId}/hard-delete`, { method: 'DELETE' })
export const exportData = (userId) => request(`/api/users/${userId}/export`)
export const setHandle = (userId, handle) =>
  request(`/api/users/${userId}/handle`, { method: 'PATCH', body: JSON.stringify({ handle }) })
export const saveProfile = (userId, fields) =>
  request(`/api/users/${userId}/profile`, { method: 'PATCH', body: JSON.stringify(fields) })
export const getUserProfile = (userId) => request(`/api/users/${userId}/user-profile`)
export const saveUserProfile = (userId, fields) =>
  request(`/api/users/${userId}/user-profile`, { method: 'PATCH', body: JSON.stringify(fields) })

// ── Chat ───────────────────────────────────────────────────────────────────
export const chat = (userId, message, inputSource = 'text') =>
  request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, message, input_source: inputSource }),
  })

// ── Inventory ──────────────────────────────────────────────────────────────
export const getInventory = (userId) => request(`/api/users/${userId}/inventory`)
export const getRecentEvents = (userId, limit = 25) =>
  request(`/api/users/${userId}/events/recent?limit=${limit}`)

// ── Budgets ───────────────────────────────────────────────────────────────
export const getBudgets = (userId) => request(`/api/users/${userId}/budgets/status`)
export const createBudget = (userId, payload) =>
  request(`/api/users/${userId}/budgets`, { method: 'POST', body: JSON.stringify(payload) })
export const updateBudget = (userId, budgetId, fields) =>
  request(`/api/users/${userId}/budgets/${budgetId}`, { method: 'PATCH', body: JSON.stringify(fields) })
export const deleteBudget = (userId, budgetId) =>
  request(`/api/users/${userId}/budgets/${budgetId}`, { method: 'DELETE' })

// ── Constraints ───────────────────────────────────────────────────────────
export const getConstraints = (userId) => request(`/api/users/${userId}/constraints`)
export const createConstraint = (userId, payload) =>
  request(`/api/users/${userId}/constraints`, { method: 'POST', body: JSON.stringify(payload) })
export const updateConstraint = (userId, constraintId, fields) =>
  request(`/api/users/${userId}/constraints/${constraintId}`, { method: 'PATCH', body: JSON.stringify(fields) })
export const deleteConstraint = (userId, constraintId) =>
  request(`/api/users/${userId}/constraints/${constraintId}`, { method: 'DELETE' })

// ── Goals ─────────────────────────────────────────────────────────────────
export const getGoals = (userId) => request(`/api/users/${userId}/goals`)
export const createGoal = (userId, payload) =>
  request(`/api/users/${userId}/goals`, { method: 'POST', body: JSON.stringify(payload) })
export const updateGoal = (userId, goalId, fields) =>
  request(`/api/users/${userId}/goals/${goalId}`, { method: 'PATCH', body: JSON.stringify(fields) })
export const deleteGoal = (userId, goalId) =>
  request(`/api/users/${userId}/goals/${goalId}`, { method: 'DELETE' })

// ── Spending analytics ────────────────────────────────────────────────────
export const getSpendingSummary = (userId, period = 'month') =>
  request(`/api/users/${userId}/spending/summary?period=${period}`)
export const getSpendingDaily = (userId, period = 'month') =>
  request(`/api/users/${userId}/spending/daily?period=${period}`)

// ── Receipt & barcode ─────────────────────────────────────────────────────
export async function uploadReceipt(userId, file) {
  const token = getToken()
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`/api/users/${userId}/receipt`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })
  const body = await res.json()
  if (!res.ok) throw new Error(body.detail || 'Receipt processing failed.')
  return body
}

export const lookupBarcode = (userId, barcode) =>
  request(`/api/users/${userId}/barcode`, { method: 'POST', body: JSON.stringify({ barcode }) })
