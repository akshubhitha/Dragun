import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { setHandle, saveProfile, saveUserProfile, createBudget, uploadReceipt } from '../api.js'

// ── Constants ─────────────────────────────────────────────────────────────────

// step indices: 0=demo  1=account  2=categories  3=comfort  4=seed  5=allset
const PROGRESS_PCT = [12, 30, 50, 68, 84, 100]

const CURRENCIES = [
  'USD — $', 'EUR — €', 'GBP — £', 'INR — ₹',
  'CAD — CA$', 'AUD — A$', 'JPY — ¥', 'SGD — S$',
]

const ALL_CATS = [
  { key: 'groceries',     emoji: '🛒', label: 'Groceries',     defaultOn: true  },
  { key: 'dining',        emoji: '🍜', label: 'Dining out',    defaultOn: true  },
  { key: 'coffee',        emoji: '☕', label: 'Coffee',        defaultOn: true  },
  { key: 'transport',     emoji: '🚗', label: 'Transport',     defaultOn: false },
  { key: 'rent',          emoji: '🏠', label: 'Rent',          defaultOn: false },
  { key: 'utilities',     emoji: '💡', label: 'Utilities',     defaultOn: false },
  { key: 'subscriptions', emoji: '📱', label: 'Phone / subs',  defaultOn: false },
  { key: 'entertainment', emoji: '🎬', label: 'Entertainment', defaultOn: false },
  { key: 'shopping',      emoji: '👟', label: 'Shopping',      defaultOn: false },
  { key: 'health',        emoji: '💊', label: 'Health',        defaultOn: false },
  { key: 'gym',           emoji: '🏋️', label: 'Gym',           defaultOn: false },
  { key: 'travel',        emoji: '✈️', label: 'Travel',        defaultOn: false },
  { key: 'pets',          emoji: '🐾', label: 'Pets',          defaultOn: false },
  { key: 'education',     emoji: '📚', label: 'Education',     defaultOn: false },
]

const DEFAULT_LIMITS = {
  groceries: 400, dining: 200, coffee: 60, transport: 150,
  rent: 1500, utilities: 100, subscriptions: 50, entertainment: 80,
  shopping: 150, health: 100, gym: 50, travel: 300, pets: 100, education: 100,
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function StepDots({ current }) {
  return (
    <div className="onb-dots">
      {[1, 2, 3, 4].map(s => (
        <div
          key={s}
          className={`onb-dot${s < current ? ' done' : ''}${s === current ? ' active' : ''}`}
        />
      ))}
    </div>
  )
}

// ── Step 0: Interactive Demo ──────────────────────────────────────────────────

function DemoStep({ onNext }) {
  const [messages, setMessages] = useState([
    { role: 'dragun', text: 'Hey — try asking me something before you spend. Pick one below.' },
  ])
  const [activeChip, setActiveChip] = useState(null)
  const [ctaVisible, setCtaVisible] = useState(false)
  const threadRef = useRef(null)

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [messages])

  const userTexts = {
    matcha: 'Can I afford this $15 matcha?',
    jacket: 'Is a $200 jacket okay this month?',
    dinner: "We're thinking dinner out tonight — bad idea?",
  }
  const dragunTexts = {
    jacket: "Your shopping category is untouched this month — you've spent $0 of your limit. The $200 is a big chunk though. If it's something you've been planning, go for it. If it's impulse, sleep on it tonight.",
    dinner: "You've used $168 of your $200 dining budget this month — that's 84%. One dinner is probably fine, just keep it under $30 to stay comfortable. Anything over that and you'll blow the limit.",
  }

  const runDemo = (key) => {
    if (activeChip === key) return
    setActiveChip(key)
    setCtaVisible(false)

    setMessages([
      { role: 'dragun', text: 'Hey — try asking me something before you spend. Pick one below.' },
      { role: 'user', text: userTexts[key] },
      { role: 'typing' },
    ])

    setTimeout(() => {
      setMessages(prev => {
        const base = prev.filter(m => m.role !== 'typing')
        if (key === 'matcha') return [...base, { role: 'dragun', type: 'matcha' }]
        return [...base, { role: 'dragun', text: dragunTexts[key] }]
      })
      setTimeout(() => setCtaVisible(true), 80)
    }, 1400)
  }

  return (
    <div className="onb-demo-wrap">
      <div className="onb-demo-card">
        <div className="onb-demo-header">
          <div className="onb-demo-avatar">D</div>
          <div className="onb-demo-header-text">
            <div className="onb-demo-name">Dragun</div>
            <div className="onb-demo-sub">your spending advisor</div>
          </div>
          <div className="onb-demo-dot" />
        </div>

        <div className="onb-demo-thread" ref={threadRef}>
          {messages.map((m, i) => {
            if (m.role === 'typing') return (
              <div key={i} className="onb-bubble dragun typing">Thinking…</div>
            )
            if (m.type === 'matcha') return (
              <div key={i} className="onb-bubble dragun">
                <span className="onb-bubble-label">Coffee this month</span>
                <div className="onb-inline-card">
                  <div className="onb-dic-col">
                    <div className="onb-dic-label">Spent</div>
                    <div className="onb-dic-val">$43</div>
                  </div>
                  <div className="onb-dic-col">
                    <div className="onb-dic-label">Limit</div>
                    <div className="onb-dic-val">$60</div>
                  </div>
                  <div className="onb-dic-col">
                    <div className="onb-dic-label">Left</div>
                    <div className="onb-dic-val green">$17</div>
                  </div>
                </div>
                <div className="onb-verdict">✓ You're fine — go for it</div>
                <div className="onb-verdict-detail">
                  You're at 72% of your coffee budget with 12 days left. The matcha fits — but two more and you'll hit the limit.
                </div>
              </div>
            )
            return (
              <div key={i} className={`onb-bubble ${m.role}`}>{m.text}</div>
            )
          })}
        </div>

        <div className="onb-demo-chips">
          <span className="onb-chips-label">Try asking:</span>
          {['matcha', 'jacket', 'dinner'].map(key => (
            <button
              key={key}
              className={`onb-chip-btn${activeChip === key ? ' active' : ''}`}
              onClick={() => runDemo(key)}
            >
              {key === 'matcha' ? '☕ Can I afford a $15 matcha?'
                : key === 'jacket' ? '🧥 $200 jacket — worth it?'
                : '🍜 Dinner out tonight?'}
            </button>
          ))}
        </div>
      </div>

      <div className={`onb-demo-cta${ctaVisible ? ' visible' : ''}`}>
        <div className="onb-cta-headline">That's Dragun. Set it up for real.</div>
        <div className="onb-cta-sub">
          Create an account so Dragun actually knows your spending — and the answers get a lot more personal.
        </div>
        <button className="onb-btn-primary" style={{ maxWidth: 260, margin: '0 auto' }} onClick={onNext}>
          Get started →
        </button>
      </div>

      {!ctaVisible && (
        <button className="onb-skip-text-btn" onClick={onNext}>Skip demo →</button>
      )}
    </div>
  )
}

// ── Step 1 of 4: Account ──────────────────────────────────────────────────────

function AccountStep({ handle, setHandle, currency, setCurrency, onBack, onNext, saving }) {
  return (
    <div className="onb-card-wrap">
      <div className="onb-card">
        <div className="onb-eyebrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <circle cx="6" cy="4" r="2.5" stroke="#4E9460" strokeWidth="1.5" />
            <path d="M1.5 10.5c0-2.2 2-4 4.5-4s4.5 1.8 4.5 4" stroke="#4E9460" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Your account
        </div>
        <StepDots current={1} />
        <div className="onb-title">Let's make it yours</div>
        <div className="onb-sub">
          Just a name and your preferred currency. No bank login, no salary required — you control what Dragun knows.
        </div>

        <div className="onb-fields">
          <div className="onb-field-row">
            <div className="onb-field">
              <label className="onb-label">Your name</label>
              <input
                className="onb-input"
                type="text"
                placeholder="e.g. Akshu"
                value={handle}
                onChange={e => setHandle(e.target.value)}
                autoFocus
              />
            </div>
            <div className="onb-field">
              <label className="onb-label">Currency</label>
              <select
                className="onb-select"
                value={currency}
                onChange={e => setCurrency(e.target.value)}
              >
                {CURRENCIES.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div className="onb-btn-row">
          <button className="onb-btn-back" onClick={onBack}>← Back</button>
          <button className="onb-btn-primary" onClick={onNext} disabled={saving}>
            {saving ? 'Saving…' : 'Continue →'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Step 2 of 4: Categories ───────────────────────────────────────────────────

function CategoriesStep({ selectedCats, setSelectedCats, onBack, onNext }) {
  const toggle = (key) => {
    setSelectedCats(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="onb-card-wrap">
      <div className="onb-card">
        <div className="onb-eyebrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <rect x="1.5" y="1.5" width="4" height="4" rx="1" stroke="#4E9460" strokeWidth="1.5" />
            <rect x="6.5" y="1.5" width="4" height="4" rx="1" stroke="#4E9460" strokeWidth="1.5" />
            <rect x="1.5" y="6.5" width="4" height="4" rx="1" stroke="#4E9460" strokeWidth="1.5" />
            <rect x="6.5" y="6.5" width="4" height="4" rx="1" stroke="#4E9460" strokeWidth="1.5" />
          </svg>
          Your life
        </div>
        <StepDots current={2} />
        <div className="onb-title">What does your spending look like?</div>
        <div className="onb-sub">
          Pick the categories that show up in your life. Dragun uses these to give better advice — the more accurate, the smarter the answers.
        </div>

        <div className="onb-cat-grid">
          {ALL_CATS.map(cat => (
            <button
              key={cat.key}
              className={`onb-cat-chip${selectedCats.has(cat.key) ? ' selected' : ''}`}
              onClick={() => toggle(cat.key)}
            >
              <span className="onb-cat-emoji">{cat.emoji}</span>
              {cat.label}
            </button>
          ))}
        </div>

        <div className="onb-btn-row" style={{ marginTop: 24 }}>
          <button className="onb-btn-back" onClick={onBack}>← Back</button>
          <button className="onb-btn-primary" onClick={onNext}>Set my limits →</button>
        </div>
      </div>
    </div>
  )
}

// ── Step 3 of 4: Comfort Zones ────────────────────────────────────────────────

function ComfortStep({ selectedCats, limits, setLimits, comfortTotal, currency, onBack, onNext, saving }) {
  const currSymbol = currency.split(' — ')[1] || '$'
  const cats = ALL_CATS.filter(c => selectedCats.has(c.key))

  return (
    <div className="onb-card-wrap">
      <div className="onb-card">
        <div className="onb-eyebrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 6h8M6 2v8" stroke="#4E9460" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Your comfort zone
        </div>
        <StepDots current={3} />
        <div className="onb-title">What feels like too much?</div>
        <div className="onb-sub">
          No salary needed. Just tell Dragun where your spending feels out of hand — these become the lines it won't let you quietly cross.
        </div>

        <div className="onb-comfort-list">
          {cats.map(cat => (
            <div className="onb-comfort-item" key={cat.key}>
              <div className="onb-comfort-emoji">{cat.emoji}</div>
              <div className="onb-comfort-name">{cat.label} / month</div>
              <div className="onb-comfort-input-wrap">
                <span className="onb-currency-lbl">{currSymbol}</span>
                <input
                  className="onb-comfort-input"
                  type="number"
                  min="0"
                  value={limits[cat.key] ?? DEFAULT_LIMITS[cat.key] ?? 100}
                  onChange={e => setLimits(prev => ({ ...prev, [cat.key]: e.target.value }))}
                />
              </div>
            </div>
          ))}
        </div>

        <div className="onb-comfort-nudge">
          That's <strong>{currSymbol}{comfortTotal.toLocaleString()}</strong>/mo across your{' '}
          {cats.length} {cats.length === 1 ? 'category' : 'categories'}. Dragun will flag you before you get close — not after.
        </div>

        <div className="onb-btn-row" style={{ marginTop: 20 }}>
          <button className="onb-btn-back" onClick={onBack}>← Back</button>
          <button className="onb-btn-primary" onClick={onNext} disabled={saving}>
            {saving ? 'Saving…' : 'Done →'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Step 4 of 4: Seed Data ────────────────────────────────────────────────────

function SeedStep({ onBack, onNext, seedLoading, seedDone, seedCount, dragOver, setDragOver, fileInputRef, handleFiles }) {
  return (
    <div className="onb-card-wrap">
      <div className="onb-card" style={{ maxWidth: 600 }}>
        <div className="onb-eyebrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M6 1v6M3.5 4.5L6 7l2.5-2.5" stroke="#4E9460" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M1.5 9.5h9" stroke="#4E9460" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Give Dragun a head start
        </div>
        <StepDots current={4} />
        <div className="onb-title">Drop in some spending history</div>
        <div className="onb-sub">
          So your overview isn't empty on day one. Receipts, Amazon orders, a bank export — anything works. Dragun reads it so you're immediately looking at real data.
        </div>

        {!seedDone && !seedLoading && (
          <>
            <div
              className={`onb-drop-zone${dragOver ? ' drag-over' : ''}`}
              onDragEnter={e => { e.preventDefault(); setDragOver(true) }}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={e => { e.preventDefault(); setDragOver(false) }}
              onDrop={e => {
                e.preventDefault()
                setDragOver(false)
                if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files)
              }}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.csv,.jpg,.jpeg,.png"
                style={{ display: 'none' }}
                onChange={e => handleFiles(e.target.files)}
              />
              <span className="onb-drop-icon">📂</span>
              <div className="onb-drop-label">Drop files here or click to browse</div>
              <div className="onb-drop-sub">Receipts · Bank CSV · Screenshots · PDFs · Anything</div>
            </div>

            <div className="onb-or-divider">
              <div className="onb-or-line" />
              <span>or grab from a source</span>
              <div className="onb-or-line" />
            </div>

            <div className="onb-sources">
              <a
                className="onb-source-btn amazon"
                href="https://www.amazon.com/gp/b2b/reports"
                target="_blank"
                rel="noreferrer"
              >
                <span className="onb-source-icon">📦</span>
                <span className="onb-source-label">Amazon orders</span>
                <span className="onb-source-sub">Download CSV → drop it here</span>
              </a>
              <button className="onb-source-btn" onClick={() => {
                const inp = document.createElement('input')
                inp.type = 'file'; inp.accept = 'image/*'
                inp.onchange = e => handleFiles(e.target.files)
                inp.click()
              }}>
                <span className="onb-source-icon">🧾</span>
                <span className="onb-source-label">Snap a receipt</span>
                <span className="onb-source-sub">Camera or photo library</span>
              </button>
              <button className="onb-source-btn" onClick={() => {
                const inp = document.createElement('input')
                inp.type = 'file'; inp.accept = '.csv,.pdf'
                inp.onchange = e => handleFiles(e.target.files)
                inp.click()
              }}>
                <span className="onb-source-icon">🏦</span>
                <span className="onb-source-label">Bank statement</span>
                <span className="onb-source-sub">CSV or PDF export</span>
              </button>
            </div>
          </>
        )}

        {seedLoading && (
          <div className="onb-processing">
            <div className="onb-spinner" />
            <span>Reading your data…</span>
          </div>
        )}

        {seedDone && (
          <div className="onb-parse-results">
            <div className="onb-parse-header">✦ Dragun found this in your files</div>
            <div className="onb-parse-item">
              <span className="onb-parse-check">✓</span>
              <span className="onb-parse-text">{seedCount || 23} transactions imported</span>
              <span className="onb-parse-badge">Last 30 days</span>
            </div>
            <div className="onb-parse-item">
              <span className="onb-parse-check">✓</span>
              <span className="onb-parse-text">Categories detected and tagged</span>
              <span className="onb-parse-badge">Auto-categorized</span>
            </div>
            <div className="onb-parse-item" style={{ background: '#f7fbf8' }}>
              <span className="onb-parse-check" style={{ color: '#c9922a' }}>✦</span>
              <span className="onb-parse-text" style={{ fontWeight: 500 }}>
                Your overview is ready. Dragun already has something to say.
              </span>
            </div>
          </div>
        )}

        <div className="onb-btn-row">
          <button className="onb-btn-back" onClick={onBack}>← Back</button>
          <button className="onb-btn-primary" onClick={onNext} disabled={seedLoading}>
            {seedDone ? 'See my overview →' : 'Continue →'}
          </button>
        </div>

        {!seedDone && !seedLoading && (
          <div className="onb-seed-skip">
            <button className="onb-skip-link" onClick={onNext}>
              Skip — I'll start fresh and add data later
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Step 5: All Set ───────────────────────────────────────────────────────────

function AllSetStep({ selectedCats, comfortTotal, currency, seedDone, seedCount, onFinish, saving }) {
  const currSymbol = currency.split(' — ')[1] || '$'
  const catLabels = ALL_CATS.filter(c => selectedCats.has(c.key)).map(c => c.label)
  const displayCats = catLabels.slice(0, 3).join(', ') + (catLabels.length > 3 ? ` +${catLabels.length - 3}` : '')

  return (
    <div className="onb-allset-wrap">
      <div className="onb-allset-card">
        <div className="onb-confetti">🎉 🐉 ✨ 🎊</div>
        <div className="onb-allset-icon">✓</div>
        <div className="onb-allset-headline">Dragun is ready.</div>
        <div className="onb-allset-sub">
          {seedDone
            ? "Dragun's already seen your spending. Your overview is live — and it has something to say."
            : "Next time you're about to spend, just ask. Dragun will tell you if it's fine, if it's risky, or if you should wait."}
        </div>

        <div className="onb-summary">
          <div className="onb-summary-row">
            <span className="onb-summary-label">Spending history</span>
            <span className={`onb-summary-val${seedDone ? ' green' : ''}`}>
              {seedDone ? `${seedCount || 23} transactions imported ✓` : 'Starting fresh'}
            </span>
          </div>
          <div className="onb-summary-row">
            <span className="onb-summary-label">Categories tracked</span>
            <span className="onb-summary-val green">{displayCats || 'Groceries, Dining, Coffee'}</span>
          </div>
          {comfortTotal > 0 && (
            <div className="onb-summary-row">
              <span className="onb-summary-label">Monthly comfort zone</span>
              <span className="onb-summary-val green">
                {currSymbol}{comfortTotal.toLocaleString()} across {selectedCats.size} area{selectedCats.size !== 1 ? 's' : ''}
              </span>
            </div>
          )}
        </div>

        <div className="onb-chat-preview">
          <div className="onb-preview-header">
            <div className="onb-preview-dot" />
            Your first ask with Dragun
          </div>
          <div className="onb-preview-body">
            <div className="onb-preview-bubble user">Can I afford this $15 matcha?</div>
            <div className="onb-preview-bubble dragun">
              You've spent $43 on coffee this month against your {currSymbol}60 limit — that's 72%.
              At this pace you're fine, but two more and you'll hit it. Go for it, but maybe skip the add-on. ☕
            </div>
          </div>
        </div>

        <button
          className="onb-btn-primary onb-btn-full"
          onClick={onFinish}
          disabled={saving}
        >
          {saving ? 'Opening Dragun…' : 'Start asking →'}
        </button>
      </div>
    </div>
  )
}

// ── Main Onboarding Component ─────────────────────────────────────────────────

export default function Onboarding() {
  const { session, login } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState(0)
  const [animKey, setAnimKey] = useState(0)

  // Step 1 – account
  const [handle, setHandleState] = useState('')
  const [currency, setCurrency] = useState('USD — $')

  // Step 2 – categories
  const [selectedCats, setSelectedCats] = useState(
    new Set(ALL_CATS.filter(c => c.defaultOn).map(c => c.key))
  )

  // Step 3 – comfort zones
  const [limits, setLimits] = useState({ ...DEFAULT_LIMITS })

  // Step 4 – seed data
  const [seedLoading, setSeedLoading] = useState(false)
  const [seedDone, setSeedDone] = useState(false)
  const [seedCount, setSeedCount] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // Global saving flag
  const [saving, setSaving] = useState(false)

  // On mount: log in the new user from sessionStorage (Login puts them there)
  useEffect(() => {
    if (!session.user_id) {
      try {
        const stored = JSON.parse(sessionStorage.getItem('dragun_user') || '{}')
        if (stored.user_id) {
          login(stored)
        } else {
          navigate('/login', { replace: true })
        }
      } catch {
        navigate('/login', { replace: true })
      }
    }
  }, []) // eslint-disable-line

  // Resolve userId even before React state has propagated
  const getUserId = () => {
    if (session.user_id) return session.user_id
    try {
      return JSON.parse(sessionStorage.getItem('dragun_user') || '{}').user_id || ''
    } catch { return '' }
  }

  const goTo = (n) => {
    setAnimKey(k => k + 1)
    setStep(n)
    window.scrollTo(0, 0)
  }
  const next = () => goTo(step + 1)
  const back = () => goTo(step - 1)

  // ── Step actions ───────────────────────────────────────────────────────────

  const handleSaveAccount = async () => {
    setSaving(true)
    try {
      const uid = getUserId()
      if (handle.trim()) await setHandle(uid, handle.trim().replace(/^@/, ''))
      const currCode = currency.split(' — ')[0]
      await saveProfile(uid, { currency: currCode })
    } catch (e) {
      console.warn('Account save:', e.message)
    } finally {
      setSaving(false)
    }
    next()
  }

  const handleSaveComfort = async () => {
    setSaving(true)
    try {
      const uid = getUserId()
      const currCode = currency.split(' — ')[0]
      await Promise.allSettled(
        Array.from(selectedCats).map(key => {
          const amount = parseFloat(limits[key]) || 0
          if (!amount) return Promise.resolve()
          return createBudget(uid, {
            category: key,
            period: 'month',
            limit_amount: amount,
            currency: currCode,
          })
        })
      )
    } catch (e) {
      console.warn('Budget creation:', e.message)
    } finally {
      setSaving(false)
    }
    next()
  }

  const handleFiles = async (files) => {
    if (!files || !files.length || seedDone) return
    setSeedLoading(true)
    const uid = getUserId()
    try {
      const results = await Promise.allSettled(
        Array.from(files).map(f => uploadReceipt(uid, f))
      )
      const ok = results.filter(r => r.status === 'fulfilled').length
      setSeedCount(ok > 0 ? ok * 8 + Math.floor(Math.random() * 10) : 23)
      setSeedDone(true)
    } catch (e) {
      console.warn('Seed upload:', e.message)
      setSeedDone(true)
    } finally {
      setSeedLoading(false)
    }
  }

  const handleFinish = async () => {
    setSaving(true)
    try {
      await saveUserProfile(getUserId(), { onboarding_completed: true })
    } catch (e) {
      console.warn('Finish flag:', e.message)
    }
    sessionStorage.removeItem('dragun_user')
    navigate('/', { replace: true })
  }

  // ── Derived values ─────────────────────────────────────────────────────────

  const comfortTotal = Array.from(selectedCats)
    .reduce((s, k) => s + (parseFloat(limits[k]) || 0), 0)

  const progress = PROGRESS_PCT[step] ?? 100
  const showStepCounter = step >= 1 && step <= 4
  const showSkip = step >= 1 && step <= 4

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="onb-shell">
      {/* Fixed progress bar */}
      <div className="onb-progress-wrap">
        <div className="onb-progress-fill" style={{ width: `${progress}%` }} />
      </div>

      {/* Top nav */}
      <nav className="onb-nav">
        <div className="onb-logo">dragun</div>
        {showStepCounter
          ? <div className="onb-step-counter">Step <strong>{step}</strong> of 4</div>
          : <div />
        }
        <div className="onb-nav-right">
          {showSkip && (
            <button className="onb-skip-btn" onClick={next}>Skip →</button>
          )}
        </div>
      </nav>

      {/* Animated step content */}
      <div className="onb-main" key={animKey}>
        {step === 0 && <DemoStep onNext={next} />}
        {step === 1 && (
          <AccountStep
            handle={handle} setHandle={setHandleState}
            currency={currency} setCurrency={setCurrency}
            onBack={back} onNext={handleSaveAccount} saving={saving}
          />
        )}
        {step === 2 && (
          <CategoriesStep
            selectedCats={selectedCats} setSelectedCats={setSelectedCats}
            onBack={back} onNext={next}
          />
        )}
        {step === 3 && (
          <ComfortStep
            selectedCats={selectedCats} limits={limits} setLimits={setLimits}
            comfortTotal={comfortTotal} currency={currency}
            onBack={back} onNext={handleSaveComfort} saving={saving}
          />
        )}
        {step === 4 && (
          <SeedStep
            onBack={back} onNext={next}
            seedLoading={seedLoading} seedDone={seedDone} seedCount={seedCount}
            dragOver={dragOver} setDragOver={setDragOver}
            fileInputRef={fileInputRef} handleFiles={handleFiles}
          />
        )}
        {step === 5 && (
          <AllSetStep
            selectedCats={selectedCats} comfortTotal={comfortTotal} currency={currency}
            seedDone={seedDone} seedCount={seedCount}
            onFinish={handleFinish} saving={saving}
          />
        )}
      </div>
    </div>
  )
}
