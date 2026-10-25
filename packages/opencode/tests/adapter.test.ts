import { afterAll, beforeAll, expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { fixturePlugin } from "./fixture-plugin.ts"
import { Plugin } from "@opencode/plugin"
import { Adapter, type Output } from "../adapter.ts"

const root = mkdtempSync(`${tmpdir()}/oc196-real-`)
for (const name of ["config", "one", "two"]) mkdirSync(`${root}/${name}`)
let fail = false
let delay = 0
let requests = 0
let deny = false
let askPermission: (sessionID: string) => Promise<void>
const permissions = Plugin.define({ id: "opencrow.test-permissions", async setup(ctx) {
  await ctx.permission.hook("evaluate", event => {
    if (event.action === "opencrow.fixture") event.effect = deny ? "deny" : "ask"
  })
  askPermission = sessionID => ctx.permission.assert({ sessionID: sessionID as Parameters<typeof ctx.permission.assert>[0]["sessionID"], action: "opencrow.fixture", resources: ["fixture"] })
} })
const server = Bun.serve({
  hostname: "127.0.0.1", port: 0,
  async fetch(request) {
    requests++
    if (delay) await Bun.sleep(delay)
    if (fail) return Response.json({ error: { message: "fixture failure", type: "invalid_request_error" } }, { status: 400 })
    const body = await request.json() as { messages?: Array<{ content: unknown }> }
    const prompt = JSON.stringify(body.messages?.at(-1)?.content || "fixture")
    const chunks = [
      { id: "fixture", object: "chat.completion.chunk", choices: [{ index: 0, delta: { role: "assistant", content: `reply:${prompt}` }, finish_reason: null }] },
      { id: "fixture", object: "chat.completion.chunk", choices: [{ index: 0, delta: {}, finish_reason: "stop" }], usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } },
    ]
    return new Response(chunks.map(value => `data: ${JSON.stringify(value)}\n\n`).join("") + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } })
  },
})
const fixture = fixturePlugin(`${server.url}v1`)
let adapter: Adapter
beforeAll(async () => {
  adapter = await Adapter.create({
    database: { path: `${root}/test.sqlite` }, config: { directory: `${root}/config`, project: false, claude: false },
    models: { fetch: false, snapshot: false }, fs: { filewatcher: false, fff: false }, plugins: [fixture, permissions],
  })
})
afterAll(async () => { await adapter?.close(); await server.stop(true); rmSync(root, { recursive: true, force: true }) })

test("real SDK creates, prompts, streams, waits, and resumes one native session", async () => {
  const events: Output[] = []
  await adapter.turn({ workspace: `${root}/one`, prompt: "first turn", model: "opencrow-test/fixture", full_auto: true }, event => events.push(event))
  const id = events[0].session_id
  expect(events.some(event => event.type === "opencrow.v2.response")).toBe(true)
  expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
  expect((events.at(-1)?.usage as { output: number }).output).toBeGreaterThan(0)
  const again: Output[] = []
  await adapter.turn({ workspace: `${root}/one`, session_id: id, prompt: "follow up" }, event => again.push(event))
  expect(again.every(event => event.session_id === id)).toBe(true)
  expect(again.at(-1)?.type).toBe("opencrow.v2.completed")
  expect(requests).toBeGreaterThanOrEqual(2)
}, 30000)

test("real SDK isolates simultaneous sessions and workspace identity", async () => {
  const a: Output[] = [], b: Output[] = []
  await Promise.all([
    adapter.turn({ workspace: `${root}/one`, prompt: "parallel A", model: "opencrow-test/fixture" }, event => a.push(event)),
    adapter.turn({ workspace: `${root}/two`, prompt: "parallel B", model: "opencrow-test/fixture" }, event => b.push(event)),
  ])
  expect(a[0].session_id).not.toBe(b[0].session_id)
  expect(a.every(event => event.session_id === a[0].session_id)).toBe(true)
  await expect(adapter.turn({ workspace: `${root}/two`, session_id: a[0].session_id, prompt: "wrong directory" }, () => {})).rejects.toThrow("different workspace")
}, 30000)

test("real SDK interruption ends only the selected native execution", async () => {
  delay = 3000
  let id = ""
  const turning = adapter.turn({ workspace: `${root}/one`, prompt: "interrupt me", model: "opencrow-test/fixture" }, event => { id = event.session_id })
  while (!id) await Bun.sleep(10)
  await Bun.sleep(100)
  await adapter.interrupt(id)
  await expect(turning).rejects.toThrow()
  delay = 0
  const events: Output[] = []
  await adapter.turn({ workspace: `${root}/two`, prompt: "still usable", model: "opencrow-test/fixture" }, event => events.push(event))
  expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
}, 30000)

test("real SDK provider errors are failures, never prompt-admission success", async () => {
  fail = true
  try { await expect(adapter.turn({ workspace: `${root}/one`, prompt: "fail", model: "opencrow-test/fixture" }, () => {})).rejects.toThrow() }
  finally { fail = false }
}, 30000)

test("real native form events and replies stay correlated to an active turn", async () => {
  delay = 800
  const events: Output[] = []
  const turning = adapter.turn({ workspace: `${root}/one`, prompt: "form", model: "opencrow-test/fixture" }, event => events.push(event))
  try {
    while (!events.length) await Bun.sleep(10)
    const sessionID = events[0].session_id
    const form = await adapter.client.session.form.create({ sessionID, title: "Choose", fields: [{ key: "answer", type: "string", required: true }] })
    for (let i = 0; i < 100 && !events.some(event => event.type === "opencrow.v2.question"); i++) await Bun.sleep(10)
    expect(events.some(event => event.type === "opencrow.v2.question" && event.session_id === sessionID)).toBe(true)
    await adapter.client.session.form.reply({ sessionID, formID: form.id, answer: { answer: "yes" } })
    await turning
    expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
  } finally { delay = 0 }
}, 30000)

test("full-auto grants asked permissions once and preserves explicit native denies", async () => {
  delay = 800
  const events: Output[] = []
  const turning = adapter.turn({ workspace: `${root}/two`, prompt: "permission", model: "opencrow-test/fixture", full_auto: true }, event => events.push(event))
  try {
    while (!events.length) await Bun.sleep(10)
    await askPermission(events[0].session_id)
    expect(events.some(event => event.type === "opencrow.v2.permission")).toBe(true)
    deny = true
    await expect(askPermission(events[0].session_id)).rejects.toThrow()
    expect(events.filter(event => event.type === "opencrow.v2.permission")).toHaveLength(1)
    await turning
  } finally { deny = false; delay = 0 }
}, 30000)

test("real SDK timeout cleans up its native execution and job", async () => {
  delay = 3000
  try { await expect(adapter.turn({ workspace: `${root}/one`, prompt: "timeout", model: "opencrow-test/fixture", timeout_sec: 1 }, () => {})).rejects.toThrow() }
  finally { delay = 0 }
  expect(adapter.jobs.size).toBe(0)
  expect(Object.keys(await adapter.client.session.active())).toHaveLength(0)
}, 30000)

test("event disconnect fails admitted work and reconnects only for an explicit later turn", async () => {
  let disconnect!: () => void
  let subscriptions = 0
  const flaky = new Adapter({ ...adapter.client, event: { ...adapter.client.event,
    subscribe(options) {
      subscriptions++
      const abort = new AbortController()
      disconnect = () => abort.abort()
      return adapter.client.event.subscribe({ ...options, signal: options?.signal ? AbortSignal.any([abort.signal, options.signal]) : abort.signal })
    },
  } })
  delay = 3000
  let native = ""
  const turning = flaky.turn({ workspace: `${root}/one`, prompt: "lost stream", model: "opencrow-test/fixture" }, event => { native = event.session_id })
  try {
    while (!native) await Bun.sleep(10)
    await Bun.sleep(100)
    disconnect()
    await expect(turning).rejects.toThrow()
    expect(subscriptions).toBe(1)
    expect(flaky.jobs.size).toBe(0)
    delay = 0
    const events: Output[] = []
    await flaky.turn({ workspace: `${root}/two`, prompt: "explicit new turn", model: "opencrow-test/fixture" }, event => events.push(event))
    expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
    expect(subscriptions).toBe(2)
  } finally { delay = 0; await flaky.close() }
}, 30000)
