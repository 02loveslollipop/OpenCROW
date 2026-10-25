import { OpenCode as Embedded } from "@opencode/sdk"
import { OpenCode as Remote, type OpenCodeClient, type OpenCodeEvent } from "@opencode/client"
import { Service } from "@opencode/client/service"
import lifecycle from "./lifecycle.ts"
import { lifecycleRpc } from "./lifecycle-rpc.ts"

export const VERSION = "2.1.4"
export type TurnInput = {
  workspace: string; prompt: string; session_id?: string; model?: string; effort?: string;
  agent?: string; full_auto?: boolean; timeout_sec?: number
  environment?: Record<string, string>
}
export type Output = { type: string; session_id: string; [key: string]: unknown }
type Job = { emit: (event: Output) => void; text: string; error?: string; started: boolean; full_auto: boolean; abort: AbortController; terminal: () => void }

export class Adapter {
  readonly jobs = new Map<string, Job>()
  private abort = new AbortController()
  private source?: Promise<void>
  private connected!: () => void
  private ready = new Promise<void>(resolve => { this.connected = resolve })
  private streamError?: Error
  constructor(readonly client: OpenCodeClient, readonly dispose: () => Promise<void> = async () => {}, readonly embedded = false) {
    this.source = this.events()
  }
  static async create(options: Embedded.CreateOptions = {}) {
    const host = await Embedded.create({ app: { name: "OpenCROW", version: VERSION }, ...options, plugins: [lifecycle, ...(options.plugins || [])] })
    return new Adapter(host, () => host.close(), true)
  }
  static connect(baseUrl: string, token?: string, headers?: Record<string, string>) {
    const url = new URL(baseUrl)
    if (url.username || url.password || url.search || url.hash) throw new Error("Put service credentials in OPENCROW_OPENCODE_TOKEN, not the URL")
    if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) {
      throw new Error("External OpenCode services require HTTPS (HTTP is allowed only on loopback)")
    }
    if (!token && !Object.keys(headers || {}).some(name => name.toLowerCase() === "authorization") && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) throw new Error("External service authentication is required")
    return new Adapter(Remote.make({ baseUrl, headers: token ? { authorization: `Bearer ${token}` } : headers }))
  }
  static async discover() {
    const endpoint = await Service.discover({ version: version => /(?:^|\s)v?2\./.test(version) })
    if (!endpoint) throw new Error("No healthy OpenCode V2 service is registered; start it explicitly or use embedded mode")
    return Adapter.connect(endpoint.url, undefined, Service.headers(endpoint))
  }
  async ensureReady() {
    // Reconnect only before a new request, never replay an admitted prompt.
    if (this.streamError) {
      if (this.jobs.size) throw this.streamError
      await this.source
      this.abort = new AbortController()
      this.streamError = undefined
      this.ready = new Promise<void>(resolve => { this.connected = resolve })
      this.source = this.events()
    }
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      await Promise.race([this.ready, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("OpenCode events did not connect")), 15000) })])
      if (this.streamError) throw this.streamError
    } finally { clearTimeout(timer) }
  }
  private async events() {
    try {
      for await (const event of this.client.event.subscribe({ signal: this.abort.signal })) {
        if (event.type === "server.connected") { this.connected(); continue }
        try { this.accept(event) } catch (error) {
          const id = "sessionID" in event.data ? event.data.sessionID : event.type === "form.created" ? event.data.form.sessionID : undefined
          if (typeof id === "string") { const job = this.jobs.get(id); if (job) job.error = String(error); void this.interrupt(id) }
        }
      }
      if (!this.abort.signal.aborted) throw new Error("OpenCode event stream closed")
    } catch (error) {
      if (!this.abort.signal.aborted) this.streamError = new Error(`OpenCode event stream failed: ${String(error)}`)
      if (this.streamError) for (const job of this.jobs.values()) { job.error = this.streamError.message; job.abort.abort() }
      this.connected()
    }
  }
  private accept(event: OpenCodeEvent) {
    const sessionID = "sessionID" in event.data ? event.data.sessionID : event.type === "form.created" ? event.data.form.sessionID : undefined
    if (typeof sessionID !== "string") return
    const job = this.jobs.get(sessionID)
    if (!job) return
    if (event.type === "session.execution.started") job.started = true
    if (["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"].includes(event.type)) job.terminal()
    if (event.type === "session.text.delta") {
      job.text = (job.text + event.data.delta).slice(-32768)
      job.emit({ type: "opencrow.v2.response", session_id: sessionID, text: event.data.delta })
    } else if (event.type === "session.execution.failed") {
      job.error = event.data.error.message
    } else if (event.type === "form.created") {
      job.emit({ type: "opencrow.v2.question", session_id: sessionID, form: event.data.form })
    } else if (event.type === "permission.asked") {
      job.emit({ type: "opencrow.v2.permission", session_id: sessionID, request: event.data })
      if (job.full_auto) void this.client.permission.reply({ sessionID, requestID: event.data.id, decision: "once" })
        .catch(error => { job.error = String(error); void this.interrupt(sessionID) })
    } else {
      job.emit({ type: "opencrow.v2.event", session_id: sessionID, event })
    }
  }
  async turn(input: TurnInput, emit: (event: Output) => void) {
    await this.ensureReady()
    const timeout = Math.min(86400, Math.max(1, input.timeout_sec || 300))
    const abort = new AbortController()
    const signal = AbortSignal.any([AbortSignal.timeout(timeout * 1000), abort.signal])
    let model
    if (input.model) {
      const separator = input.model.indexOf("/")
      if (separator < 0) {
        const catalog = await this.client.model.list({ location: { directory: input.workspace } }, { signal })
        const matches = catalog.data.filter(model => model.id === input.model)
        if (matches.length !== 1) throw new Error("OpenCode model is missing or ambiguous; specify provider/model")
        model = { providerID: matches[0].providerID, id: matches[0].id, variant: input.effort }
      } else {
        if (!separator || separator === input.model.length - 1) throw new Error("OpenCode model must be provider/model")
        model = { providerID: input.model.slice(0, separator), id: input.model.slice(separator + 1), variant: input.effort }
      }
    }
    const info = input.session_id ? await this.client.session.get({ sessionID: input.session_id }, { signal }) : await this.client.session.create({
      location: { directory: input.workspace }, model, agent: input.agent,
    }, { signal })
    const id = info.id
    if (info.location.directory !== input.workspace) throw new Error("Native OpenCode session belongs to a different workspace")
    const active = await this.client.session.active({ signal })
    if (this.jobs.has(id) || active[id]) throw new Error("Native OpenCode session already has an active execution")
    let terminal!: () => void
    const terminalEvent = new Promise<void>(resolve => { terminal = resolve })
    const job: Job = { emit, text: "", started: false, full_auto: input.full_auto === true, abort, terminal }
    this.jobs.set(id, job)
    try {
      emit({ type: "opencrow.v2.session", session_id: id })
      const rpcOptions = { location: { directory: input.workspace }, signal }
      // Also verifies the required connector is loaded before admitting work.
      await this.client.rpc(lifecycleRpc).claim({ sessionID: id }, rpcOptions)
      if (input.environment) {
        // V2's session environment replaces the shell's base environment; it
        // does not merge it. Never send local provider credentials remotely.
        const remote = JSON.parse(process.env.OPENCROW_OPENCODE_REMOTE_ENV || "{}")
        if (!remote || typeof remote !== "object" || Array.isArray(remote) || Object.values(remote).some(value => typeof value !== "string")) throw new Error("OPENCROW_OPENCODE_REMOTE_ENV must be a JSON object of strings")
        const base = this.embedded ? Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined))
          : { PATH: "/usr/local/bin:/usr/bin:/bin", ...remote }
        for (const key of Object.keys(base)) if (key.startsWith("OPENCROW_WORKER_") || ["OPENCROW_OPENCODE_TOKEN", "OPENCROW_OPENCODE_PASSWORD"].includes(key)) delete base[key]
        await this.client.session.environment({ sessionID: id, variables: { ...base, ...input.environment } }, { signal })
      }
      if (input.session_id && model) await this.client.session.switchModel({ sessionID: id, model }, { signal })
      if (input.session_id && input.agent) await this.client.session.switchAgent({ sessionID: id, agent: input.agent }, { signal })
      if (!model && input.effort) {
        const fallback = info.model ? null : (await this.client.model.default({ location: { directory: input.workspace } }, { signal })).data
        const selected = info.model || fallback
        if (!selected) throw new Error("Specify a provider/model when selecting an effort variant without a saved model")
        await this.client.session.switchModel({ sessionID: id, model: { ...selected, variant: input.effort } }, { signal })
      }
      if (this.streamError) throw this.streamError
      await this.client.session.prompt({ sessionID: id, text: input.prompt }, { signal })
      // prompt() acknowledges inbox admission. wait() waits for execution.
      const waiting = this.client.session.wait({ sessionID: id }, { signal })
      await Promise.race([
        Promise.all([waiting, terminalEvent]),
        new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error(job.error || "OpenCode turn interrupted or timed out")), { once: true })),
      ])
      if (this.streamError) throw this.streamError
      if (job.error) throw new Error(job.error)
      const result = await this.client.session.get({ sessionID: id }, { signal })
      if (result.outcome !== "succeeded") throw new Error(job.error || `OpenCode execution ${result.outcome || "has no terminal outcome"}`)
      const completion = await this.client.rpc(lifecycleRpc).complete({ sessionID: id }, rpcOptions)
      if (completion.code === 2) throw new Error(completion.reason || "OpenCROW lifecycle is incomplete")
      const delta = (a: typeof result.tokens, b: typeof info.tokens) => ({
        input: a.input - b.input, output: a.output - b.output, reasoning: a.reasoning - b.reasoning,
        cache: { read: a.cache.read - b.cache.read, write: a.cache.write - b.cache.write },
      })
      emit({ type: "opencrow.v2.completed", session_id: id, usage: delta(result.tokens, info.tokens), cost: result.cost - info.cost,
        model: result.model ? `${result.model.providerID}/${result.model.id}` : undefined, final_response: job.text })
    } catch (error) {
      await this.client.session.interrupt({ sessionID: id }, { signal: AbortSignal.timeout(5000) }).catch(() => {})
      throw error
    } finally {
      if (input.environment) await this.client.session.environment({ sessionID: id, variables: {} }, { signal: AbortSignal.timeout(5000) }).catch(() => {})
      this.jobs.delete(id)
    }
  }
  async interrupt(sessionID: string) {
    this.jobs.get(sessionID)?.abort.abort()
    return this.client.session.interrupt({ sessionID }, { signal: AbortSignal.timeout(5000) })
  }
  async close() {
    await Promise.all([...this.jobs.keys()].map(id => this.interrupt(id).catch(() => {})))
    this.abort.abort(); await this.source; await this.dispose()
  }
}
