import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import plugin, { formatLintSummary } from "../index.js";

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

test("Wiki lint FAIL message exposes missing root and ok=false", () => {
  const text = formatLintSummary({
    ok: false, total_files: 0,
    errors: ["Wiki root not found or not a directory"],
    broken_links: [], ambiguous_links: [], supersession_errors: []
  });
  assert.match(text, /Lint: FAIL \(ok=false\)/);
  assert.match(text, /System errors: 1/);
  assert.match(text, /Wiki root not found/);
});

test("Wiki lint FAIL message exposes invalid supersession even without broken links", () => {
  const text = formatLintSummary({
    ok: false, total_files: 3,
    broken_links: [], ambiguous_links: [],
    supersession_errors: [{ file: "wiki/topics/v2.md", reason: "missing_or_ambiguous_predecessor", target: "v1" }]
  });
  assert.match(text, /Lint: FAIL/);
  assert.match(text, /Supersession errors: 1/);
  assert.match(text, /missing_or_ambiguous_predecessor/);
});

test("Wiki lint distinguishes clean PASS from orphan and provenance WARN", () => {
  const clean = formatLintSummary({
    ok: true, total_files: 2,
    errors: [], broken_links: [], ambiguous_links: [], supersession_errors: [],
    orphan_topics: [], provenance_warnings: [], active_topic_conflicts: []
  });
  assert.match(clean, /Lint: PASS \(ok=true\)/);
  const warnings = formatLintSummary({
    ok: true, total_files: 2,
    orphan_topics: ["wiki/topics/orphan.md"],
    provenance_warnings: [{ file: "a.md", reason: "missing_source_repo" }]
  });
  assert.match(warnings, /Lint: WARN \(ok=true\)/);
  assert.match(warnings, /Orphan topics: 1/);
  assert.match(warnings, /missing_source_repo/);
});

test("Wiki lint rejects missing or malformed health result", () => {
  assert.match(formatLintSummary({ total_files: 0 }), /Lint: FAIL/);
  assert.match(formatLintSummary(null), /Lint: FAIL/);
});
