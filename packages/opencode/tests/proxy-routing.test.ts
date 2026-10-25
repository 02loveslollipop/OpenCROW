/** Real SDK native shell + owned Python proxy. No external provider calls. */
import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, rmSync } from "node:fs"
import { resolve } from "node:path"
import { Adapter, type Output } from "../adapter.ts"
import { Plugin } from "@opencode/plugin"
import { fixturePlugin } from "./fixture-plugin.ts"

test("real SDK tool environment routes target traffic without proxying model requests", async () => {
  const root = mkdtempSync("/tmp/oc-proxy-sdk-")
  for (const name of ["workspace", "config"]) mkdirSync(`${root}/${name}`)
  const source = resolve(import.meta.dir, "../../..")
  const python = process.env.OPENCROW_TEST_PYTHON || "python3"
  async function control(code: string) {
    const child = Bun.spawn([python, "-c", code], { env: { ...Bun.env, PYTHONPATH: `${source}/packages/mcp/core`, OPENCROW_WEB_PROXY_STATE_DIR: `${root}/state` }, stdout: "pipe", stderr: "pipe" })
    const [out, err, codeValue] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited])
    if (codeValue) throw new Error(`Proxy control fixture failed: ${err.slice(0, 500)}`)
    return JSON.parse(out)
  }
  const target = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("target-ok") })
  let modelRequests = 0
  const model = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    modelRequests++
    const body = await request.json() as { messages: Array<{ role: string }>; tools?: Array<{ function: { name: string } }> }
    const tool = body.tools?.find(t => t.function.name === "proxy_probe")
    const call = tool && !body.messages.some(m => m.role === "tool")
    const delta = call ? { tool_calls: [{ index: 0, id: "proxy-fixture", type: "function", function: { name: "proxy_probe", arguments: "{}" } }] } : { content: "Proxy SDK turn done" }
    return new Response(`data: ${JSON.stringify({ id: "fixture", choices: [{ index: 0, delta, finish_reason: null }] })}\n\ndata: ${JSON.stringify({ id: "fixture", choices: [{ index: 0, delta: {}, finish_reason: call ? "tool_calls" : "stop" }] })}\n\ndata: [DONE]\n\n`, { headers: { "content-type": "text/event-stream" } })
  } })
  let adapter: Adapter | undefined
  let sessionID = ""
  try {
    const state = await control(`import json;import opencrow_web_proxy as p; s=p.start({'workspace':${JSON.stringify(`${root}/workspace`)},'targets':[{'host':'127.0.0.1','port':${target.port},'allow_private':True}]}); print(json.dumps({'session_id':s['session_id'],'environment':p.environment(s['session_id'],{'worker_id':'sdk-worker','provider':'opencode'})}))`)
    sessionID = state.session_id
    const commandCode = `import os,urllib.request; assert os.environ.get('http_proxy'); assert urllib.request.urlopen('http://127.0.0.1:${target.port}/sdk-tool').read()==b'target-ok'`
    const quote = (value: string) => "'" + value.replaceAll("'", "'\\''") + "'"
    const probe = Plugin.define({ id: "opencrow.proxy-test", async setup(ctx) {
      await ctx.tool.transform(editor => editor.add({ name: "proxy_probe", description: "Exercise native session shell environment", input: { type: "object", properties: {} }, options: { codemode: false }, async execute(_input, context) {
        await adapter!.client.session.shell({ sessionID: context.sessionID, command: `${quote(python)} -c ${quote(commandCode)}` })
        return { content: "proxy native shell completed" }
      } }))
    } })
    adapter = await Adapter.create({ database: { path: `${root}/sdk.sqlite` }, config: { directory: `${root}/config`, project: false, claude: false }, models: { fetch: false, snapshot: false }, fs: { filewatcher: false, fff: false }, plugins: [fixturePlugin(`${model.url}v1`), probe] })
    const events: Output[] = []
    await adapter.turn({ workspace: `${root}/workspace`, prompt: "Call proxy_probe then finish", model: "opencrow-test/fixture", environment: state.environment, timeout_sec: 20, full_auto: true }, event => events.push(event))
    expect(events.at(-1)?.type).toBe("opencrow.v2.completed")
    const history = await control(`import json;import opencrow_web_proxy as p;print(json.dumps(p.rpc('${sessionID}','history')))`)
    expect(history.requests.length).toBe(1)
    expect(history.requests[0].correlation.worker_id).toBe("sdk-worker")
    expect(history.requests[0].state).toBe("completed")
    expect(modelRequests).toBeGreaterThan(0)
    // Parent host environment never acquired the per-session route.
    expect(process.env.http_proxy === state.environment.http_proxy).toBe(false)
  } finally {
    await adapter?.close()
    if (sessionID) await control(`import json;import opencrow_web_proxy as p;p.stop('${sessionID}');p.delete('${sessionID}');print('{}')`)
    await target.stop(true); await model.stop(true)
    rmSync(root, { recursive: true, force: true })
  }
}, 45000)
