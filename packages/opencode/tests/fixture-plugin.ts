/** Deterministic local model/tool fixture; never registered by production code. */
import { Plugin, Provider, Model } from "@opencode/plugin"

export function fixturePlugin(baseURL: string) {
  return Plugin.define({
    id: "opencrow.test-provider",
    async setup(ctx) {
      const providerID = Provider.ID.make("opencrow-test")
      await ctx.provider.transform(editor => editor.add({
        info: { ...Provider.Info.empty(providerID), name: "Local fixture", activation: "enabled",
          package: "@opencode/ai/providers/openai-compatible", settings: { baseURL, apiKey: "fixture-only" } },
        models: [Model.Info.default(providerID, Model.ID.make("fixture"))],
      }))
      await ctx.tool.transform(editor => editor.add({
        name: "probe", description: "Return a deterministic test result", input: { type: "object", properties: {}, additionalProperties: false },
        options: { codemode: false },
        execute: async () => ({ content: "tool-ok" }),
      }))
    },
  })
}
export default fixturePlugin(process.env.OPENCROW_TEST_MODEL_URL || "http://127.0.0.1:1/v1")
