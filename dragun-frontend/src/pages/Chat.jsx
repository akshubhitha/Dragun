import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../AuthContext.jsx'
import { chat, uploadReceipt } from '../api.js'

function fmtTime(date) {
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

const SUGGESTED_PROMPTS = [
  'What did I spend this week?',
  'Am I on track with groceries?',
  'Log $4.50 coffee ☕',
  'Show my budgets',
  'How do I cut dining costs?',
  "What's my biggest expense?",
  'Set a savings goal 🎯',
]

const INITIAL_MESSAGES = [
  {
    id: 1,
    role: 'bot',
    text: "Hey! Ready to track your spending? What did you buy today?",
    time: '9:14 AM',
  },
]

export default function Chat() {
  const { session }  = useAuth()
  const location     = useLocation()
  const [messages, setMessages]               = useState(INITIAL_MESSAGES)
  const [input, setInput]                     = useState(location.state?.prefill || '')
  const [loading, setLoading]                 = useState(false)
  const [showVoice, setShowVoice]             = useState(false)
  const [voiceTranscript, setVoiceTranscript] = useState('')
  const [isListening, setIsListening]         = useState(false)
  const [showCameraMenu, setShowCameraMenu]   = useState(false)

  const threadRef       = useRef(null)
  const inputRef        = useRef(null)
  const fileInputRef    = useRef(null)
  const captureInputRef = useRef(null)
  const cameraWrapRef   = useRef(null)
  const recognitionRef  = useRef(null)

  // Scroll thread to bottom on new messages / loading change
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages, loading])

  // Close camera menu on outside click
  useEffect(() => {
    if (!showCameraMenu) return
    const handle = (e) => {
      if (cameraWrapRef.current && !cameraWrapRef.current.contains(e.target)) {
        setShowCameraMenu(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [showCameraMenu])

  // ── Send message ──────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text) => {
    const trimmed = (text || '').trim()
    if (!trimmed || loading) return

    const userMsg = {
      id: Date.now(),
      role: 'user',
      text: trimmed,
      time: fmtTime(new Date()),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await chat(session.user_id, trimmed)
      const botText = res.reply || res.message || res.response || 'Got it!'
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'bot',
        text: botText,
        time: fmtTime(new Date()),
      }])
    } catch {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'bot',
        text: "Something went sideways — try again?",
        time: fmtTime(new Date()),
        error: true,
      }])
    } finally {
      setLoading(false)
    }
  }, [loading, session?.user_id])

  // ── Voice input ───────────────────────────────────────────────────────────
  const startVoice = useCallback(() => {
    setShowVoice(true)
    setVoiceTranscript('')

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      setIsListening(false)
      return
    }

    const recognition      = new SR()
    recognition.continuous     = false
    recognition.interimResults = true
    recognition.lang           = 'en-US'
    recognitionRef.current     = recognition

    recognition.onstart  = () => setIsListening(true)
    recognition.onresult = (e) => {
      const t = Array.from(e.results).map(r => r[0].transcript).join('')
      setVoiceTranscript(t)
    }
    recognition.onend = () => {
      setIsListening(false)
      setTimeout(() => {
        setVoiceTranscript(prev => {
          if (prev) {
            setInput(prev)
            setTimeout(() => inputRef.current?.focus(), 50)
          }
          setShowVoice(false)
          return ''
        })
      }, 500)
    }
    recognition.onerror = () => {
      setIsListening(false)
      setShowVoice(false)
    }

    try { recognition.start() } catch {}
  }, [])

  const stopVoice = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const cancelVoice = useCallback(() => {
    recognitionRef.current?.abort()
    setIsListening(false)
    setShowVoice(false)
    setVoiceTranscript('')
  }, [])

  const sendVoice = useCallback(() => {
    const t = voiceTranscript
    recognitionRef.current?.abort()
    setShowVoice(false)
    setVoiceTranscript('')
    setIsListening(false)
    sendMessage(t)
  }, [voiceTranscript, sendMessage])

  // ── Image / receipt upload ────────────────────────────────────────────────
  const handleFileChange = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setMessages(prev => [...prev, {
      id: Date.now(),
      role: 'user',
      text: '📷 Uploaded a receipt',
      time: fmtTime(new Date()),
    }])
    setLoading(true)

    try {
      const res = await uploadReceipt(session.user_id, file)
      const botText = res.reply || res.message || res.response || 'Receipt processed!'
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'bot',
        text: botText,
        time: fmtTime(new Date()),
      }])
    } catch {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'bot',
        text: "Couldn't read that receipt — try a clearer photo?",
        time: fmtTime(new Date()),
      }])
    } finally {
      setLoading(false)
      e.target.value = ''
    }
  }, [session?.user_id])

  const userInitial = session?.handle?.[0]?.toUpperCase() || 'A'

  return (
    <div className="chat-wrap">

      {/* ── Header ── */}
      <div className="chat-hd">
        <div className="chat-hd-id">
          <div className="chat-d-avatar">D</div>
          <div>
            <div className="chat-hd-name">Dragun</div>
            <div className="chat-hd-status">
              <span className="chat-dot-live" />
              Active now
            </div>
          </div>
        </div>
        <span className="chat-hd-hint">Your personal finance companion</span>
      </div>

      {/* ── Thread ── */}
      <div className="chat-thread" ref={threadRef}>
        {messages.map((msg, i) => {
          const isBot    = msg.role === 'bot'
          const prev     = messages[i - 1]
          const showTime = i === 0 || (prev && prev.time !== msg.time)

          return (
            <div key={msg.id}>
              {showTime && <div className="chat-ts">{msg.time}</div>}
              <div className={`chat-msg-group ${isBot ? 'bot' : 'me'}`}>
                <div className="chat-msg-row">
                  {isBot  && <div className="chat-av bot-av">D</div>}
                  {!isBot && <div className="chat-av me-av">{userInitial}</div>}
                  <div className="chat-bubbles">
                    <div className={`chat-bbl${msg.error ? ' chat-bbl--error' : ''}`}>
                      {msg.text}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )
        })}

        {/* Typing indicator */}
        {loading && (
          <div className="chat-msg-group bot">
            <div className="chat-msg-row">
              <div className="chat-av bot-av">D</div>
              <div className="chat-bubbles">
                <div className="chat-bbl chat-bbl--typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            </div>
          </div>
        )}

        <div style={{ height: 8, flexShrink: 0 }} />
      </div>

      {/* ── Suggested prompts strip ── */}
      <div className="chat-prompts">
        <span className="chat-prompts-label">✦ Try:</span>
        {SUGGESTED_PROMPTS.map(p => (
          <button
            key={p}
            className="chat-prompt-chip"
            onClick={() => {
              setInput(p.replace(/[☕🎯]/g, '').trim())
              inputRef.current?.focus()
            }}
          >
            {p}
          </button>
        ))}
      </div>

      {/* ── Input bar ── */}
      <div className="chat-input-bar">

        {/* Mic button */}
        <button className="chat-inp-icon" title="Voice input" onClick={startVoice}>
          🎙️
        </button>

        {/* Camera button + popover */}
        <div className="chat-camera-wrap" ref={cameraWrapRef}>
          <button
            className="chat-inp-icon"
            title="Upload or capture receipt"
            onClick={() => setShowCameraMenu(v => !v)}
          >
            📷
          </button>

          {showCameraMenu && (
            <div className="chat-camera-menu">
              <button
                className="chat-camera-item"
                onClick={() => { captureInputRef.current?.click(); setShowCameraMenu(false) }}
              >
                <span className="chat-camera-item-icon">📸</span>
                <span className="chat-camera-item-text">
                  <span className="chat-camera-item-title">Take photo</span>
                  <span className="chat-camera-item-sub">Use your camera</span>
                </span>
              </button>
              <div className="chat-camera-divider" />
              <button
                className="chat-camera-item"
                onClick={() => { fileInputRef.current?.click(); setShowCameraMenu(false) }}
              >
                <span className="chat-camera-item-icon">🖼️</span>
                <span className="chat-camera-item-text">
                  <span className="chat-camera-item-title">Upload image</span>
                  <span className="chat-camera-item-sub">From your device</span>
                </span>
              </button>
            </div>
          )}
        </div>

        <input
          ref={inputRef}
          className="chat-text-input"
          type="text"
          placeholder="Ask Dragun or log a purchase…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              sendMessage(input)
            }
          }}
        />

        <button
          className="chat-send-btn"
          onClick={() => sendMessage(input)}
          disabled={!input.trim() || loading}
        >
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
            <path
              d="M13 7.5L1.5 1.5L4.5 7.5L1.5 13.5L13 7.5Z"
              fill="white" stroke="white" strokeWidth="0.5" strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>

      {/* ── Voice panel overlay ── */}
      {showVoice && (
        <div
          className="voice-overlay"
          onClick={e => { if (e.target === e.currentTarget) cancelVoice() }}
        >
          <div className="voice-panel">
            <div className="voice-panel-header">
              <span className="voice-panel-title">
                {isListening ? 'Listening…' : voiceTranscript ? 'Got it' : 'Starting…'}
              </span>
              {voiceTranscript && (
                <p className="voice-transcript">"{voiceTranscript}"</p>
              )}
            </div>

            {/* Animated waveform */}
            <div className="voice-wave">
              {Array.from({ length: 28 }).map((_, i) => (
                <div
                  key={i}
                  className={`voice-wave-bar${isListening ? ' voice-wave-bar--active' : ''}`}
                  style={{ animationDelay: `${((i * 73) % 800) / 1000}s` }}
                />
              ))}
            </div>

            {/* Controls */}
            <div className="voice-controls">
              <button className="voice-cancel-btn" onClick={cancelVoice}>
                Cancel
              </button>
              <button
                className="voice-stop-btn"
                onClick={isListening ? stopVoice : cancelVoice}
                title={isListening ? 'Stop recording' : 'Close'}
              >
                <div className="voice-stop-icon" />
              </button>
              {voiceTranscript && (
                <button className="voice-send-btn" onClick={sendVoice}>
                  Send ↑
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Hidden file inputs ── */}
      <input
        ref={captureInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

    </div>
  )
}
