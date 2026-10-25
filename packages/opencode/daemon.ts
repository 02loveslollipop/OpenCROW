/** Private per-user Unix socket. The embedded SDK itself opens no HTTP listener. */
import { chmodSync, unlinkSync, readFileSync } from "node:fs"
import { Adapter, VERSION, type TurnInput } from "./adapter.ts"
import type { Socket } from "bun"

type Connection = { buffer: string; decoder: TextDecoder; output: Buffer; closed: boolean; sessions: Set<string>; pending: Set<string | number> }
type Request = { id: string | number; method: string; params?: Record<string, unknown> }
const socketPath = process.argv[2]
const databasePath = process.argv[3]
if (!socketPath || !databasePath) throw new Error("Private socket and persistent database paths are required")
if (Bun.version !== "1.4.4") throw new Error("OpenCode bridge requires pinned Bun 1.4.4")
const mode = process.env.OPENCROW_OPENCODE_MODE || (process.env.OPENCROW_OPENCODE_URL ? "connected" : "embedded")
if (!["embedded", "connected", "service"].includes(mode) || (mode === "connected" && !process.env.OPENCROW_OPENCODE_URL)
    || (mode !== "connected" && process.env.OPENCROW_OPENCODE_URL)) throw new Error("Choose embedded, connected with URL, or registered-service mode explicitly")
for (const name of ["sdk", "client", "plugin"]) {
  const metadata = JSON.parse(readFileSync(new URL(`./node_modules/@opencode/${name}/package.json`, import.meta.url), "utf8"))
  if (metadata.version !== VERSION) throw new Error(`OpenCode ${name} package must be pinned to ${VERSION}`)
}
const serviceToken = process.env.OPENCROW_OPENCODE_TOKEN
const servicePassword = process.env.OPENCROW_OPENCODE_PASSWORD
const headers = servicePassword ? { authorization: `Basic ${Buffer.from(`${process.env.OPENCROW_OPENCODE_USERNAME || "opencode"}:${servicePassword}`).toString("base64")}` } : undefined
const adapter = process.env.OPENCROW_OPENCODE_URL
  ? Adapter.connect(process.env.OPENCROW_OPENCODE_URL, serviceToken, headers)
  : mode === "service" ? await Adapter.discover() : await Adapter.create({ database: { path: databasePath } })
delete process.env.OPENCROW_OPENCODE_TOKEN
delete process.env.OPENCROW_OPENCODE_PASSWORD
const serverInfo = await adapter.client.server.info({ signal: AbortSignal.timeout(15000) })
if (!/(?:^|\s)v?2\./.test(serverInfo.version)) throw new Error("Connected OpenCode service must be version 2.x")
let lastActivity = Date.now()
let closing = false
let admitted = 0
function flush(socket: Socket<Connection>) {
  while (socket.data.output.length) {
    const count = socket.write(socket.data.output)
    if (count < 0) { socket.data.closed = true; return }
    socket.data.output = socket.data.output.subarray(count)
    if (!count) return
  }
}
const send = (socket: Socket<Connection>, value: unknown) => {
  if (socket.data.closed) return false
  const text = Buffer.from(JSON.stringify(value) + "\n")
  if (socket.data.output.length + text.length > 4 * 1024 * 1024) { socket.end(); socket.data.closed = true; return false }
  socket.data.output = Buffer.concat([socket.data.output, text])
  flush(socket)
  return !socket.data.closed
}
async function request(socket: Socket<Connection>, input: Request) {
  if (socket.data.pending.size) { socket.end(); return }
  socket.data.pending.add(input.id)
  lastActivity = Date.now()
  let isTurn = false
  try {
    const p = input.params || {}
    let result: unknown
    if (input.method === "health") {
      await adapter.ensureReady()
      result = { version: VERSION, server_version: serverInfo.version, mode: adapter.embedded ? "embedded" : "connected", pid: process.pid }
    }
    else if (input.method === "turn") {
      if (admitted >= 16) throw new Error("OpenCode bridge has reached its 16 concurrent-turn limit")
      admitted++; isTurn = true
      if (typeof p.workspace !== "string" || typeof p.prompt !== "string" || !p.prompt.trim()) throw new Error("workspace and prompt are required")
      if (Buffer.byteLength(p.prompt, "utf8") > 1024 * 1024) throw new Error("Prompt exceeds the 1 MiB bridge limit")
      for (const key of ["session_id", "model", "effort", "agent"]) {
        if (p[key] === null) delete p[key]
        else if (p[key] !== undefined && typeof p[key] !== "string") throw new Error(`${key} must be a string`)
      }
      if (p.environment && (typeof p.environment !== "object" || Array.isArray(p.environment) || Object.entries(p.environment).some(([key, value]) => typeof value !== "string" || !["OPENCROW_WORKER_STATE_DIR", "OPENCROW_WORKER_ID", "OPENCROW_WORKER_TURN_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "OPENCROW_WEB_PROXY_SESSION", "OPENCROW_WEB_PROXY_TOOL_ENV"].includes(key)))) {
        throw new Error("Only per-turn worker reporting and proxy tool variables may be passed through the bridge")
      }
      await adapter.turn(p as TurnInput, event => {
        socket.data.sessions.add(event.session_id)
        if (!send(socket, { id: input.id, event })) throw new Error("OpenCROW consumer disconnected or exceeded its buffer")
      })
      result = { complete: true }
    } else if (input.method === "interrupt") result = await adapter.interrupt(String(p.session_id))
    else if (input.method === "form.reply") result = await adapter.client.session.form.reply({ sessionID: String(p.session_id), formID: String(p.form_id), answer: p.answer as Record<string, string> })
    else if (input.method === "permission.reply") result = await adapter.client.permission.reply({ sessionID: String(p.session_id), requestID: String(p.request_id), decision: p.decision === "once" ? "once" : "reject" })
    else if (input.method === "close") { result = { closing: true }; setTimeout(() => void shutdown(), 20) }
    else throw new Error("Unknown OpenCode bridge method")
    send(socket, { id: input.id, result: result ?? null })
  } catch (error) {
    let message = error instanceof Error ? error.message : String(error)
    const secret = serviceToken
    if (secret) message = message.replaceAll(secret, "[redacted]")
    if (servicePassword) message = message.replaceAll(servicePassword, "[redacted]")
    if (headers?.authorization) message = message.replaceAll(headers.authorization, "[redacted]")
    send(socket, { id: input.id, error: { message: message.slice(0, 4096) } })
  } finally {
    socket.data.pending.delete(input.id)
    if (isTurn) admitted--
    // A completed connection must not retain ownership of resumed sessions.
    socket.data.sessions.clear()
    lastActivity = Date.now()
  }
}
const listener = Bun.listen<Connection>({
  unix: socketPath,
  socket: {
    open(socket) { socket.data = { buffer: "", decoder: new TextDecoder(), output: Buffer.alloc(0), closed: false, sessions: new Set(), pending: new Set() } },
    data(socket, bytes) {
      socket.data.buffer += socket.data.decoder.decode(bytes, { stream: true })
      if (socket.data.buffer.length > 2 * 1024 * 1024) { socket.end(); return }
      while (socket.data.buffer.includes("\n")) {
        const index = socket.data.buffer.indexOf("\n")
        const line = socket.data.buffer.slice(0, index)
        socket.data.buffer = socket.data.buffer.slice(index + 1)
        try { void request(socket, JSON.parse(line)) } catch { socket.end() }
      }
    },
    drain(socket) { flush(socket) },
    close(socket) { socket.data.closed = true; for (const id of socket.data.sessions) void adapter.interrupt(id).catch(() => {}) },
    error() { /* connection loss is handled by close */ },
  },
})
chmodSync(socketPath, 0o600)
async function shutdown() {
  if (closing) return
  closing = true
  listener.stop(true)
  await adapter.close()
  try { unlinkSync(socketPath) } catch { /* already removed */ }
  process.exit(0)
}
const idle = setInterval(() => {
  const timeout = Number(process.env.OPENCROW_OPENCODE_IDLE_SEC || 120) * 1000
  if (!admitted && !adapter.jobs.size && Date.now() - lastActivity > timeout) void shutdown()
}, 1000)
idle.unref()
process.on("SIGTERM", () => void shutdown())
process.on("SIGINT", () => void shutdown())
