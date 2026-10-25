import { Rpc } from "@opencode/plugin"

// Standard Schema keeps the native RPC contract typed without a second runtime
// validation dependency. Both sides validate data at the SDK boundary.
function schema<T>(check: (value: unknown) => value is T) {
  return { "~standard": { version: 1 as const, vendor: "opencrow", types: undefined as { input: T; output: T } | undefined, validate: (value: unknown) =>
    check(value) ? { value } : { issues: [{ message: "Invalid OpenCROW lifecycle RPC value" }] } } }
}
const session = schema<{ sessionID: string }>((value): value is { sessionID: string } =>
  typeof value === "object" && value !== null && "sessionID" in value && typeof value.sessionID === "string")
const result = schema<{ code: number; reason: string }>((value): value is { code: number; reason: string } =>
  typeof value === "object" && value !== null && "code" in value && typeof value.code === "number"
    && "reason" in value && typeof value.reason === "string")
export const lifecycleRpc = Rpc.define({
  id: "opencrow.lifecycle",
  methods: { claim: { input: session, output: result }, complete: { input: session, output: result } },
  events: {},
})
