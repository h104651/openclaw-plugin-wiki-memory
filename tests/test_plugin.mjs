import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import plugin from "../index.js";

const registered = new Map();
const fakeApi = {
  pluginConfig: { cliPath: "/definitely/missing/astor-wiki-memory", timeoutMs: 500 },
  logger: { info: () => {} },
  registerTool: (factory, options) => {
    registered.set(options.name, factory());
  }
};

plugin.register(fakeApi);

test("all eleven declared OpenClaw tools are registered", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf8")
  );
  assert.equal(registered.size, 11);
  assert.deepEqual(
    [...registered.keys()].sort(),
    [...manifest.contracts.tools].sort()
  );
});

test("memory_update refuses implicit destructive updates", async () => {
  const result = await registered.get("memory_update").execute(
    "call-id", { title: "Example", body: "A revised claim" }
  );
  assert.equal(result.details.error, "missing_supersedes");
  assert.match(result.content[0].text, /supersedes/);
});

test("recall API supports opting into historical revisions", () => {
  const recall = registered.get("memory_recall");
  assert.equal(recall.parameters.properties.includeHistory.type, "boolean");
  const update = registered.get("memory_update");
  assert.equal(update.parameters.properties.supersedes.type, "string");
  assert.equal(update.parameters.properties.source_repo.type, "string");
});

test("unavailable CLI is fail-open for wiki_lint", async () => {
  const result = await registered.get("wiki_lint").execute("call-id", {});
  assert.equal(result.details.error, "lint_unavailable");
  assert.match(result.content[0].text, /unavailable/);
});
