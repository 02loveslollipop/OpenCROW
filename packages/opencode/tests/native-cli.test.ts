import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, symlinkSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { Adapter, type Output } from "../adapter.ts"

const cli = process.env.OPENCROW_TEST_CLI || Bun.which("opencode")
test.skipIf(!cli)("real V2 CLI loads native plugin, skills, MCP and connected-client sessions", async () => {
  const root = mkdtempSync(`${tmpdir()}/oc196-native-`)
  const home = `${root}/home`, config = `${home}/.config/opencode`, workspace = `${root}/workspace`
  const source = resolve(import.meta.dir, "../../..")
  for (const path of [config, workspace, `${root}/bin`, `${config}/skills`, `${config}/plugins`]) mkdirSync(path, { recursive: true })
  symlinkSync(`${source}/skills/opencrow-utility-toolbox`, `${config}/skills/opencrow-utility-toolbox`, "dir")
  writeFileSync(`${root}/bin/opencrow-lifecycle-hook`, `#!/bin/sh\nprintf '%s\\n' "$1" >> '${root}/hooks.log'\ncat >/dev/null\nif [ "$1" = idle ] && [ -f '${root}/block' ]; then printf '%s\\n' '{"reason":"fixture lifecycle block"}'; exit 2; fi\nprintf '%s\\n' '{"continue":true,"additionalContext":"test lifecycle context"}'\n`)
  chmodSync(`${root}/bin/opencrow-lifecycle-hook`, 0o755)
  const model = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json() as { messages: Array<{ role: string; content: unknown }>; tools?: Array<{ function: { name: string } }> }
    const hasTool = body.messages.some(message => message.role === "tool")
    const tool = body.tools?.find(tool => tool.function.name === "probe")
    const delta = !hasTool && tool ? { tool_calls: [{ index: 0, id: "call-fixture", type: "function", function: { name: "probe", arguments: "{}" } }] } : { content: "native fixture response" }
    const chunks = [
      { id: "fixture", choices: [{ index: 0, delta, finish_reason: null }] },
      { id: "fixture", choices: [{ index: 0, delta: {}, finish_reason: !hasTool && tool ? "tool_calls" : "stop" }], usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 } },
    ]
    return new Response(chunks.map(chunk => `data: ${JSON.stringify(chunk)}\n\n`).join("") + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } })
  } })
  writeFileSync(`${config}/opencode.json`, JSON.stringify({
    plugins: [resolve(import.meta.dir, "fixture-plugin.ts"), resolve(import.meta.dir, "../plugin")],
    mcp: { servers: { "opencrow-lifecycle": { type: "local", command: [process.env.OPENCROW_TEST_PYTHON || "python3", "-m", "opencrow_lifecycle.mcp_server"],
      environment: { PYTHONPATH: `${source}/packages/lifecycle` }, codemode: false } } },
  }))
  // V2 configured plugin paths must be directories, not individual .ts files.
  mkdirSync(`${config}/plugins/fixture`, { recursive: true })
  writeFileSync(`${config}/plugins/fixture/index.ts`, `export { default } from ${JSON.stringify(resolve(import.meta.dir, "fixture-plugin.ts"))}\n`)
  const value = JSON.parse(readFileSync(`${config}/opencode.json`, "utf8"))
  value.plugins[0] = `${config}/plugins/fixture`
  writeFileSync(`${config}/opencode.json`, JSON.stringify(value))
  const reserve = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response() })
  const port = reserve.port!
  await reserve.stop(true)
  const child = Bun.spawn([cli!, "serve", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: workspace, env: { ...Bun.env, HOME: home, XDG_CONFIG_HOME: `${home}/.config`, XDG_DATA_HOME: `${root}/data`, XDG_STATE_HOME: `${root}/state`,
      OPENCROW_TEST_MODEL_URL: `${model.url}v1`, PATH: `${root}/bin:${Bun.env.PATH}` }, stdout: Bun.file(`${root}/stdout.log`), stderr: Bun.file(`${root}/stderr.log`),
  })
  let password = ""
  for (let i = 0; i < 100; i++) {
    try { password = readFileSync(`${root}/stdout.log`, "utf8").match(/server password (\S+)/)?.[1] || "" } catch { /* starting */ }
    if (password) break
    await Bun.sleep(100)
  }
  const adapter = Adapter.connect(`http://127.0.0.1:${port}`, undefined, { authorization: `Basic ${Buffer.from(`opencode:${password}`).toString("base64")}` })
  let success = false
  try {
    let started = false
    for (let i = 0; i < 100; i++) {
      try { await adapter.client.server.info({ signal: AbortSignal.timeout(1000) }); started = true; break } catch { await Bun.sleep(100) }
    }
    expect(started).toBe(true)
    const location = { directory: workspace }
    let skillFound = false
    for (let i = 0; i < 50; i++) {
      const skills = await adapter.client.skill.list({ location })
      skillFound = skills.data.some(skill => skill.id === "opencrow-utility-toolbox")
      if (skillFound) break
      if (i === 49) console.error("Discovered isolated skill IDs", skills.data.map(skill => skill.id))
      await Bun.sleep(100)
    }
    expect(skillFound).toBe(true)
    const plugins = await adapter.client.plugin.list({ location })
    expect(plugins.data.some(plugin => plugin.id === "opencrow.lifecycle")).toBe(true)
    let connected = false
    for (let i = 0; i < 50; i++) {
      const mcps = await adapter.client.mcp.list({ location })
      connected = mcps.data.some(server => server.name === "opencrow-lifecycle" && server.status.status === "connected")
      if (connected) break
      await Bun.sleep(100)
    }
    expect(connected).toBe(true)
    const events: Output[] = []
    await adapter.turn({ workspace, prompt: "call the probe tool then finish", model: "opencrow-test/fixture", full_auto: true, timeout_sec: 30 }, event => events.push(event))
    expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
    const id = events[0].session_id
    await adapter.turn({ workspace, prompt: "follow up", session_id: id, full_auto: true, timeout_sec: 30 }, () => {})
    await adapter.client.session.compact({ sessionID: id })
    await adapter.client.session.wait({ sessionID: id })
    await Bun.sleep(200)
    const hooks = readFileSync(`${root}/hooks.log`, "utf8").trim().split("\n")
    expect(hooks.filter(hook => hook === "session_start").length).toBe(1)
    for (const hook of ["context", "pre_tool", "post_tool", "compaction", "idle"]) expect(hooks).toContain(hook)
    // This marker exists only on the external host: completion enforcement
    // must execute there through plugin RPC, not through a local hook process.
    writeFileSync(`${root}/block`, "block")
    const blocked: Output[] = []
    await expect(adapter.turn({ workspace, prompt: "blocked completion", session_id: id, full_auto: true }, event => blocked.push(event))).rejects.toThrow("fixture lifecycle block")
    expect(blocked.some(event => event.type === "opencrow.v2.completed")).toBe(false)
    success = true
  } finally {
    await adapter.close()
    child.kill("SIGTERM")
    await Promise.race([child.exited, Bun.sleep(5000).then(() => child.kill("SIGKILL"))])
    await model.stop(true)
    if (success) rmSync(root, { recursive: true, force: true })
    else console.error(`Native CLI diagnostic files retained at ${root}`)
  }
}, 60000)
