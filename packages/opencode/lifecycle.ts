import { Plugin } from "@opencode/plugin"
import { lifecycleRpc } from "./lifecycle-rpc.ts"

/** Malformed/missing hook executables fail open; an explicit policy block does not. */
export function runHook(event: string, payload: unknown, directory: string) {
  try {
    const process = Bun.spawnSync({
      cmd: ["opencrow-lifecycle-hook", event, "--provider", "opencode", "--workspace", directory],
      cwd: directory, stdin: new TextEncoder().encode(JSON.stringify(payload)), stdout: "pipe", stderr: "pipe",
      timeout: 15_000,
    })
    let response: Record<string, unknown> = {}
    try { response = JSON.parse(new TextDecoder().decode(process.stdout)) } catch { /* fail open */ }
    return { code: process.exitCode, response }
  } catch (error) {
    return { code: 0, response: { warning: `OpenCROW hook unavailable: ${String(error)}` } }
  }
}

function requireAllowed(result: ReturnType<typeof runHook>) {
  if (result.code === 2) throw new Error(String(result.response.reason || "Blocked by OpenCROW lifecycle"))
}

export default Plugin.define({
  id: "opencrow.lifecycle",
  async setup(ctx) {
    const starts = new Map<string, Promise<void>>()
    const directory = async (sessionID: string) => (await ctx.session.get({ sessionID })).location.directory
    await ctx.rpc.register(lifecycleRpc, {
      claim: async ({ sessionID }) => {
        await directory(sessionID)
        await ctx.storage.set(`sdk:${sessionID}`, true)
        return { code: 0, reason: "" }
      },
      complete: async ({ sessionID }) => {
        const result = runHook("idle", { session_id: sessionID }, await directory(sessionID))
        return { code: result.code, reason: String(result.response.reason || "") }
      },
    })
    const initialize = (sessionID: string) => {
      if (!starts.has(sessionID)) starts.set(sessionID, (async () => {
        const key = `started:${sessionID}`
        if (await ctx.storage.get(key)) return
        requireAllowed(runHook("session_start", { session_id: sessionID }, await directory(sessionID)))
        await ctx.storage.set(key, true)
      })().catch(error => { starts.delete(sessionID); throw error }))
      return starts.get(sessionID)!
    }
    await ctx.session.hook("context", async event => {
      await initialize(event.sessionID)
      const result = runHook("context", { session_id: event.sessionID }, await directory(event.sessionID))
      requireAllowed(result)
      const text = result.response.additionalContext
      if (typeof text === "string" && text) event.system.push({ type: "text", text })
    })
    await ctx.session.hook("compaction", async event => {
      await initialize(event.sessionID)
      const result = runHook("compaction", { session_id: event.sessionID }, await directory(event.sessionID))
      requireAllowed(result)
      const text = result.response.additionalContext
      if (typeof text === "string" && text) event.system.push({ type: "text", text })
    })
    await ctx.tool.hook("execute.before", async event => {
      requireAllowed(runHook("pre_tool", { session_id: event.sessionID, tool_name: event.tool, tool_input: event.input }, await directory(event.sessionID)))
    })
    await ctx.tool.hook("execute.after", async event => {
      requireAllowed(runHook("post_tool", { session_id: event.sessionID, tool_name: event.tool, tool_input: event.input,
        tool_output: event.status === "completed" ? event.result : event.error }, await directory(event.sessionID)))
    })
    const abort = new AbortController()
    const task = (async () => {
      for await (const event of ctx.event.subscribe({ signal: abort.signal })) {
        if (event.type !== "session.execution.succeeded") continue
        if (await ctx.storage.get(`sdk:${event.data.sessionID}`)) continue
        const result = runHook("idle", { session_id: event.data.sessionID }, await directory(event.data.sessionID))
        // Event subscriptions observe completed executions. They cannot block
        // native completion; the shared execution adapter enforces this result.
        await ctx.storage.set(`idle:${event.data.sessionID}`, { code: result.code, reason: String(result.response.reason || "") })
      }
    })().catch(error => { if (!abort.signal.aborted) console.error("OpenCROW lifecycle event subscription ended", String(error)) })
    return async () => { abort.abort(); await task; starts.clear() }
  },
})
