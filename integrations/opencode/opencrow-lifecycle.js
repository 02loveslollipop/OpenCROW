// OpenCROW lifecycle adapter for OpenCode's native plugin hooks.

function runHook(event, payload, directory) {
  const process = Bun.spawnSync({
    cmd: ["opencrow-lifecycle-hook", event, "--provider", "opencode", "--workspace", directory],
    cwd: directory,
    stdin: JSON.stringify(payload || {}),
    stdout: "pipe",
    stderr: "pipe",
  })
  const stdout = process.stdout ? new TextDecoder().decode(process.stdout).trim() : ""
  const stderr = process.stderr ? new TextDecoder().decode(process.stderr).trim() : ""
  let response = {}
  try {
    response = stdout ? JSON.parse(stdout) : {}
  } catch (_) {
    response = { warning: stdout }
  }
  return { code: process.exitCode, response, stderr }
}

export const OpenCrowLifecycle = async ({ directory, client }) => {
  let lifecycleContext = ""
  const refresh = () => {
    const result = runHook("session_start", {}, directory)
    lifecycleContext = result.response.additionalContext || result.response?.hookSpecificOutput?.additionalContext || ""
    return result
  }
  refresh()
  return {
    "experimental.chat.system.transform": async (_input, output) => {
      if (!lifecycleContext) refresh()
      if (lifecycleContext) output.system.push(lifecycleContext)
    },
    "experimental.session.compacting": async (input, output) => {
      const result = runHook("compaction", input, directory)
      const context = result.response.additionalContext || ""
      if (context) output.context.push(context)
    },
    "tool.execute.before": async (input, output) => {
      const result = runHook("pre_tool", { tool_name: input.tool, tool_input: output.args }, directory)
      if (result.code === 2) throw new Error(result.response.reason || result.stderr || "Blocked by OpenCROW lifecycle")
    },
    "tool.execute.after": async (input, output) => {
      runHook("post_tool", { tool_name: input.tool, tool_input: input.args, tool_output: output.output }, directory)
    },
    event: async ({ event }) => {
      if (event.type === "session.created") refresh()
      if (event.type === "session.idle") {
        const result = runHook("idle", event, directory)
        if (result.code === 2) {
          await client.app.log({ body: { service: "opencrow", level: "warn", message: result.response.reason || "Lifecycle incomplete" } })
          throw new Error(result.response.reason || "OpenCROW lifecycle is incomplete")
        }
      }
    },
  }
}
