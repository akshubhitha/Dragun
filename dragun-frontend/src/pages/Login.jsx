import { useState } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { sendOTP, verifyOTP } from '../api.js'

export default function Login() {
  const { login } = useAuth()
  const [step, setStep] = useState('email') // 'email' | 'otp'
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSendOTP = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await sendOTP(email.trim().toLowerCase())
      setStep('otp')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyOTP = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await verifyOTP(email.trim().toLowerCase(), code.trim())
      if (res.is_new_user) {
        sessionStorage.setItem('dragun_user', JSON.stringify(res))
        window.location.href = '/onboarding'
      } else {
        login(res)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">

        <div className="login-logo">
          <div className="login-logo-text">dra<span>gun</span></div>
        </div>
        <p className="login-tagline">Your dragon knows every coin in the hoard.</p>

        {step === 'email' ? (
          <form onSubmit={handleSendOTP}>
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
                required
              />
            </div>
            <p className="login-error">{error}</p>
            <button className="btn-primary" style={{ width: '100%' }} type="submit" disabled={loading}>
              {loading ? 'Sending…' : 'Send code'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyOTP}>
            <p className="auth-sent-to">
              Code sent to <strong>{email}</strong>
            </p>
            <div className="form-group">
              <label htmlFor="otp">Enter 6-digit code</label>
              <input
                id="otp"
                type="text"
                inputMode="numeric"
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                autoFocus
                required
                style={{ letterSpacing: '0.3em', fontSize: '22px', textAlign: 'center' }}
              />
            </div>
            <p className="login-error">{error}</p>
            <button className="btn-primary" style={{ width: '100%' }} type="submit" disabled={loading}>
              {loading ? 'Verifying…' : 'Sign in'}
            </button>
            <div className="auth-footer-links">
              <button
                className="auth-link-btn"
                type="button"
                onClick={() => { setStep('email'); setCode(''); setError('') }}
              >
                ← Different email
              </button>
            </div>
          </form>
        )}

      </div>
    </div>
  )
}
