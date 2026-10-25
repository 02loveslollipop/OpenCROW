import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { resolve } from "node:path"

test("Python worker MCP, initializer and Constellation share the real SDK host", async () => {
  const root = mkdtempSync(`${tmpdir()}/oc196-python-`)
  const source = resolve(import.meta.dir, "../../..")
  const home = `${root}/home`, config = `${home}/.config/opencode`
  mkdirSync(`${config}/plugins/fixture`, { recursive: true })
  mkdirSync(`${root}/workspace`)
  writeFileSync(`${config}/plugins/fixture/index.ts`, `export { default } from ${JSON.stringify(resolve(import.meta.dir, "fixture-plugin.ts"))}\n`)
  writeFileSync(`${config}/opencode.json`, JSON.stringify({ plugins: [`${config}/plugins/fixture`] }))
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.text()
    if (body.includes("delay-stop")) await Bun.sleep(5000)
    const chunks = [
      { id: "fixture", choices: [{ index: 0, delta: { content: "SDK fixture completed" }, finish_reason: null }] },
      { id: "fixture", choices: [{ index: 0, delta: {}, finish_reason: "stop" }], usage: { prompt_tokens: 10, completion_tokens: 3, total_tokens: 13 } },
    ]
    return new Response(chunks.map(chunk => `data: ${JSON.stringify(chunk)}\n\n`).join("") + "data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } })
  } })
  const python = process.env.OPENCROW_TEST_PYTHON || "python3"
  const code = `
import json,os,pathlib,signal,subprocess,time
from opencrow_worker_runner import Runner
import opencrow_worker_mcp
import opencrow_opencode as sdk
from constellation.providers import OpenCodeAdapter
from opencrow_lifecycle.init_cli import provider_command

def call(name,**arguments):
    result=opencrow_worker_mcp.build_server()._handle_message({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments}})
    value=json.loads(result['result']['content'][0]['text'])
    assert value['ok'],value
    return value
def wait(worker_id,state='completed',active=False):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        value=Runner().status(worker_id)
        if value['state']==state and value['active']==active:return value
        if value['state']=='failed':raise AssertionError(value)
        time.sleep(.05)
    raise AssertionError(Runner().status(worker_id))
workspace=pathlib.Path(os.environ['TEST_WORKSPACE'])
worker_id=None
try:
    first=call('worker_start',task='Complete a deterministic SDK fixture turn',provider='opencode',model='opencrow-test/fixture',workspace=str(workspace))['observations'][0]
    worker_id=first['worker_id']; first=wait(worker_id)
    native=first['native_session_id']; assert native and first['usage'] and 'SDK fixture' in first['response']
    events=call('worker_events',worker_id=worker_id); assert events['observations']
    call('worker_followup',worker_id=worker_id,message='Follow up on the same session')
    second=wait(worker_id); assert second['native_session_id']==native and second['turn']==2
    call('worker_handoff',worker_id=worker_id,provider='opencode',model='opencrow-test/fixture',checkpoint='Verified first turn; continue in the same workspace')
    third=wait(worker_id); assert third['native_session_id']!=native and third['history'][0]['native_session_id']==native
    call('worker_followup',worker_id=worker_id,message='delay-stop')
    wait(worker_id,'running',True); call('worker_stop',worker_id=worker_id); wait(worker_id,'cancelled')
    adapter=OpenCodeAdapter(); assert adapter.availability().available
    turn=adapter.start(prompt='Constellation start',workspace=workspace,model='opencrow-test/fixture')
    events=list(turn.stream()); native=events[0]['session_id']; assert events[-1]['type']=='opencrow.v2.completed'
    assert list(adapter.resume(session_id=native,prompt='Constellation resume',workspace=workspace).stream())[-1]['type']=='opencrow.v2.completed'
    command=provider_command('opencode',prompt='Initializer SDK turn',workspace=workspace,model='opencrow-test/fixture',unsafe=True)
    result=subprocess.run(command,input='Initializer SDK turn',text=True,capture_output=True,timeout=25)
    assert result.returncode==0,result.stdout+result.stderr
    assert any(json.loads(line).get('type')=='opencrow.v2.completed' for line in result.stdout.splitlines())
    health=sdk.ensure_host(); os.kill(health['pid'],signal.SIGKILL); time.sleep(.2)
    restarted=sdk.ensure_host(); assert restarted['pid']!=health['pid']
    restored=list(adapter.resume(session_id=native,prompt='Explicit resume after bridge restart',workspace=workspace).stream())
    assert restored[-1]['type']=='opencrow.v2.completed' and restored[-1]['session_id']==native
    print(json.dumps({'worker_mcp':'start/events/followup/handoff/stop','constellation':'start/resume','initializer':'SDK','native_session':native}))
finally:
    if worker_id:
        try:Runner().stop(worker_id)
        except Exception:pass
    try:sdk.rpc('close')
    except Exception:pass
`
  const child = Bun.spawn([python, "-c", code], { cwd: source, env: {
    ...Bun.env, HOME: home, XDG_CONFIG_HOME: `${home}/.config`, XDG_DATA_HOME: `${root}/data`, XDG_STATE_HOME: `${root}/state`,
    OPENCROW_OPENCODE_STATE_DIR: `${root}/sdk`, OPENCROW_WORKER_STATE_DIR: `${root}/workers`,
    OPENCROW_TEST_MODEL_URL: `${server.url}v1`, TEST_WORKSPACE: `${root}/workspace`,
    PYTHONPATH: ["packages/mcp/core", "packages/mcp/servers", "packages/opencode", "packages/lifecycle", "services/constellation"].map(path => `${source}/${path}`).join(":"),
  }, stdout: "pipe", stderr: "pipe" })
  try {
    const [out, err, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited])
    if (code) console.error(out, err, `Diagnostics: ${root}`)
    expect(code).toBe(0)
    expect(JSON.parse(out.trim()).initializer).toBe("SDK")
  } finally {
    if (child.exitCode === null) { child.kill("SIGTERM"); await child.exited }
    await server.stop(true)
    if (child.exitCode === 0) rmSync(root, { recursive: true, force: true })
  }
}, 90000)
