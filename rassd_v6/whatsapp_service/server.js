/**
 * ATLAS PRO — WhatsApp Service via Baileys
 * Expose HTTP API for Python FastAPI to send WhatsApp messages
 *
 * Endpoints:
 *   GET  /health          → status
 *   GET  /qr              → QR code page (scan once to connect)
 *   GET  /status          → connection status
 *   POST /send            → { phone, message } → send WA message
 */

const express = require('express')
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys')
const { Boom } = require('@hapi/boom')
const pino   = require('pino')
const QRCode = require('qrcode')
const path   = require('path')
const fs     = require('fs')

const app  = express()
const PORT = process.env.WA_PORT || 3001
const TOKEN = process.env.WA_SECRET || 'atlas_wa_secret_2024'
const AUTH_DIR = path.join(__dirname, 'auth_info')

app.use(express.json())

// ── State ──────────────────────────────────────────
let sock         = null
let qrCode       = null
let isConnected  = false
let isConnecting = false
let lastQR       = null

// ── Logger ─────────────────────────────────────────
const logger = pino({ level: 'silent' })

// ── Auth middleware ─────────────────────────────────
function auth(req, res, next) {
  const token = req.headers['x-wa-token'] || req.query.token
  if (token !== TOKEN) return res.status(401).json({ ok: false, msg: 'Unauthorized' })
  next()
}

// ── Start WhatsApp ─────────────────────────────────
async function startSock() {
  if (isConnecting) return
  isConnecting = true

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version }           = await fetchLatestBaileysVersion()

  sock = makeWASocket({
    version,
    logger,
    auth: state,
    browser: ['ATLAS PRO', 'Chrome', '120.0'],
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrCode = qr
      lastQR = new Date().toISOString()
      isConnected = false
      console.log('[WA] QR Code updated — scan at /qr')
    }
    if (connection === 'open') {
      isConnected  = true
      qrCode       = null
      isConnecting = false
      console.log('[WA] ✅ Connected to WhatsApp')
    }
    if (connection === 'close') {
      isConnected  = false
      isConnecting = false
      const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut
      console.log('[WA] Connection closed. Reconnect:', shouldReconnect)
      if (shouldReconnect) setTimeout(startSock, 5000)
    }
  })
}

// ── Routes ─────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ ok: true, connected: isConnected, hasQR: !!qrCode, service: 'ATLAS PRO WhatsApp' })
})

app.get('/status', auth, (req, res) => {
  res.json({ ok: true, connected: isConnected, hasQR: !!qrCode, lastQR })
})

app.get('/qr', async (req, res) => {
  if (isConnected) {
    return res.send('<html><body style="font-family:sans-serif;text-align:center;padding:40px;background:#07070c;color:#d4a843"><h2>✅ WhatsApp connecté!</h2><p style="color:#8a8680">ATLAS PRO est connecté à WhatsApp.</p></body></html>')
  }
  if (!qrCode) {
    return res.send('<html><body style="font-family:sans-serif;text-align:center;padding:40px;background:#07070c;color:#d4a843"><h2>⏳ Génération du QR...</h2><p style="color:#8a8680">Rafraîchissez dans quelques secondes.</p><script>setTimeout(()=>location.reload(),3000)</script></body></html>')
  }
  try {
    const qrImg = await QRCode.toDataURL(qrCode)
    res.send(`<html><head><title>ATLAS PRO — Scan WhatsApp</title></head>
<body style="font-family:sans-serif;text-align:center;padding:40px;background:#07070c;color:#f0ede8">
  <h2 style="color:#d4a843">📱 Scannez ce QR avec WhatsApp</h2>
  <p style="color:#8a8680">WhatsApp → Menu → Appareils connectés → Connecter un appareil</p>
  <img src="${qrImg}" style="border:4px solid #d4a843;border-radius:12px;max-width:300px">
  <p style="color:#4a4740;font-size:12px">Le QR se rafraîchit automatiquement</p>
  <script>setTimeout(()=>location.reload(),30000)</script>
</body></html>`)
  } catch(e) {
    res.status(500).json({ ok: false, msg: e.message })
  }
})

app.post('/send', auth, async (req, res) => {
  const { phone, message } = req.body
  if (!phone || !message) return res.status(400).json({ ok: false, msg: 'phone and message required' })
  if (!isConnected || !sock) return res.status(503).json({ ok: false, msg: 'WhatsApp not connected' })

  try {
    // Format phone: remove + and spaces, add @s.whatsapp.net
    const jid = phone.replace(/[^0-9]/g, '') + '@s.whatsapp.net'
    await sock.sendMessage(jid, { text: message })
    res.json({ ok: true, msg: 'Message sent', to: phone })
  } catch(e) {
    res.status(500).json({ ok: false, msg: e.message })
  }
})

// ── Start ───────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`[WA] ATLAS PRO WhatsApp Service on port ${PORT}`)
  startSock()
})
