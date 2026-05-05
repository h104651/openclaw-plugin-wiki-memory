import { execFile, spawn } from "node:child_process";

const DEFAULT_CLI_PATH = "/usr/local/bin/astor-wiki-memory";
const DEFAULT_TIMEOUT_MS = 5000;
const DEFAULT_RECALL_LIMIT = 5;
const DEFAULT_RECALL_MAX_TOKENS = 1200;
const DEFAULT_GET_MAX_TOKENS = 800;

function asConfig(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeConfig(raw) {
  const cfg = asConfig(raw);
  return {
    cliPath: typeof cfg.cliPath === "string" && cfg.cliPath.trim() ? cfg.cliPath.trim() : DEFAULT_CLI_PATH,
    timeoutMs: Number.isFinite(cfg.timeoutMs) ? Math.max(500, Math.min(30000, Math.floor(cfg.timeoutMs))) : DEFAULT_TIMEOUT_MS,
    recallLimit: Number.isFinite(cfg.recallLimit) ? Math.max(1, Math.min(10, Math.floor(cfg.recallLimit))) : DEFAULT_RECALL_LIMIT,
    recallMaxTokens: Number.isFinite(cfg.recallMaxTokens) ? Math.max(200, Math.min(4000, Math.floor(cfg.recallMaxTokens))) : DEFAULT_RECALL_MAX_TOKENS,
    getMaxTokens: Number.isFinite(cfg.getMaxTokens) ? Math.max(100, Math.min(4000, Math.floor(cfg.getMaxTokens))) : DEFAULT_GET_MAX_TOKENS,
    storeTags: Array.isArray(cfg.storeTags) ? cfg.storeTags.filter((tag) => typeof tag === "string" && tag.trim()).map((tag) => tag.trim()) : ["openclaw", "memory"],
    autoIndexAfterWrite: cfg.autoIndexAfterWrite !== false
  };
}

function clampInt(value, fallback, min, max) {
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(parsed)));
}

function truncateText(text, maxChars) {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

function safeSlugTitle(text, fallback) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return truncateText(clean, 48);
}

function runCli(config, args) {
  return new Promise((resolve) => {
    execFile(config.cliPath, args, {
      timeout: config.timeoutMs,
      maxBuffer: 1024 * 1024,
      windowsHide: true
    }, (error, stdout, stderr) => {
      if (error) {
        resolve({
          ok: false,
          stdout: stdout || "",
          stderr: stderr || "",
          message: error.message || String(error)
        });
        return;
      }
      resolve({ ok: true, stdout: stdout || "", stderr: stderr || "" });
    });
  });
}

function runCliWithInput(config, args, input) {
  return new Promise((resolve) => {
    const child = spawn(config.cliPath, args, {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      resolve({ ok: false, stdout, stderr, message: `timeout after ${config.timeoutMs}ms` });
    }, config.timeoutMs);

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, stdout, stderr, message: error.message });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        ok: code === 0,
        stdout,
        stderr,
        message: code === 0 ? undefined : `exit code ${code}`
      });
    });
    child.stdin.end(input);
  });
}

function parseJsonResult(result) {
  if (!result.ok) {
    return { ok: false, error: result.message || result.stderr || "cli_failed", raw: result };
  }
  try {
    return { ok: true, value: JSON.parse(result.stdout) };
  } catch (error) {
    return { ok: false, error: `invalid JSON: ${error instanceof Error ? error.message : String(error)}`, raw: result };
  }
}

function failOpenText(action, parsed) {
  return `LLM Wiki Memory ${action} unavailable; continuing without blocking OpenClaw. ${parsed.error}`;
}

function renderRecallPayload(payload, includeFullText, maxCharsPerItem) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  if (results.length === 0) return "No relevant wiki memories found.";
  const rows = results.map((item, index) => {
    const id = item.id ?? "";
    const title = item.title ?? "Untitled";
    const heading = item.heading ?? "";
    const relPath = item.rel_path ?? item.path ?? "";
    const score = typeof item.score === "number" ? item.score.toFixed(3) : String(item.score ?? "");
    const body = includeFullText ? (item.text ?? item.summary ?? "") : (item.summary ?? "");
    return `${index + 1}. [${id}] [score:${score}] ${title}${heading ? ` :: ${heading}` : ""}\nPath: ${relPath}\n${truncateText(String(body), maxCharsPerItem)}`;
  });
  return `<relevant-memories source="astor-wiki-memory" mode="${includeFullText ? "full" : "summary"}">\nFound ${results.length} wiki memories, estimated_tokens=${payload.estimated_tokens ?? "unknown"}.\n\n${rows.join("\n\n")}\n</relevant-memories>`;
}

async function recall(config, params) {
  const query = String(params.query ?? "").trim();
  if (!query) {
    return {
      content: [{ type: "text", text: "memory_recall requires a non-empty query." }],
      details: { error: "empty_query" }
    };
  }

  const includeFullText = params.includeFullText === true;
  const limit = clampInt(params.limit, config.recallLimit, 1, includeFullText ? 10 : 6);
  const maxTokens = clampInt(params.maxTokens, config.recallMaxTokens, 200, 4000);
  const maxCharsPerItem = clampInt(params.maxCharsPerItem, includeFullText ? 1200 : 220, 60, 4000);
  const args = ["recall", query, "--limit", String(limit), "--max-tokens", String(maxTokens), "--json"];
  if (typeof params.scope === "string" && params.scope.trim()) args.push("--scope", params.scope.trim());

  const parsed = parseJsonResult(await runCli(config, args));
  if (!parsed.ok) {
    return {
      content: [{ type: "text", text: failOpenText("recall", parsed) }],
      details: { error: "recall_unavailable", message: parsed.error }
    };
  }

  let payload = parsed.value;
  if (includeFullText && Array.isArray(payload.results)) {
    const hydrated = [];
    for (const item of payload.results) {
      if (!item?.id) {
        hydrated.push(item);
        continue;
      }
      const got = parseJsonResult(await runCli(config, ["get", String(item.id), "--max-tokens", String(config.getMaxTokens), "--json"]));
      hydrated.push(got.ok ? { ...item, text: got.value.text } : item);
    }
    payload = { ...payload, results: hydrated };
  }

  return {
    content: [{ type: "text", text: renderRecallPayload(payload, includeFullText, maxCharsPerItem) }],
    details: {
      ...payload,
      source: "astor-wiki-memory",
      recallMode: includeFullText ? "full" : "summary"
    }
  };
}

async function get(config, params) {
  const id = String(params.id ?? params.lookup ?? "").trim();
  if (!id) {
    return {
      content: [{ type: "text", text: "wiki_get requires id or lookup." }],
      details: { error: "empty_id" }
    };
  }
  const maxTokens = clampInt(params.maxTokens, config.getMaxTokens, 100, 4000);
  const parsed = parseJsonResult(await runCli(config, ["get", id, "--max-tokens", String(maxTokens), "--json"]));
  if (!parsed.ok) {
    return {
      content: [{ type: "text", text: failOpenText("get", parsed) }],
      details: { error: "get_unavailable", message: parsed.error, id }
    };
  }
  const value = parsed.value;
  return {
    content: [{ type: "text", text: value.text ?? "" }],
    details: { ...value, source: "astor-wiki-memory" }
  };
}

async function stats(config) {
  const parsed = parseJsonResult(await runCli(config, ["stats"]));
  if (!parsed.ok) {
    return {
      content: [{ type: "text", text: failOpenText("stats", parsed) }],
      details: { error: "stats_unavailable", message: parsed.error }
    };
  }
  return {
    content: [{ type: "text", text: `LLM Wiki Memory: ${parsed.value.total_chunks ?? 0} chunks\nDB: ${parsed.value.db_path ?? ""}` }],
    details: { ...parsed.value, source: "astor-wiki-memory" }
  };
}

async function indexUpdate(config) {
  const parsed = parseJsonResult(await runCli(config, ["index", "--rebuild"]));
  if (!parsed.ok) {
    return {
      content: [{ type: "text", text: failOpenText("index update", parsed) }],
      details: { error: "index_unavailable", message: parsed.error }
    };
  }
  return {
    content: [{ type: "text", text: `LLM Wiki Memory index rebuilt: ${parsed.value.indexed_chunks ?? 0} chunks.` }],
    details: { ...parsed.value, source: "astor-wiki-memory" }
  };
}

async function crystallize(config, params, fallbackTitle) {
  const body = String(params.body ?? params.text ?? "").trim();
  if (!body) {
    return {
      content: [{ type: "text", text: "memory_store/wiki_crystallize requires text or body." }],
      details: { error: "empty_body" }
    };
  }
  const category = typeof params.category === "string" && params.category.trim() ? params.category.trim() : "memory";
  const scope = typeof params.scope === "string" && params.scope.trim() ? params.scope.trim() : "global";
  const title = safeSlugTitle(params.title, fallbackTitle ?? `OpenClaw memory ${new Date().toISOString().slice(0, 10)}`);
  const tags = [...new Set([...config.storeTags, category, scope].filter(Boolean))].join(",");
  const content = [
    `# ${title}`,
    "",
    "## Source",
    "",
    "- Source: OpenClaw LLM Wiki plugin",
    `- Category: ${category}`,
    `- Scope: ${scope}`,
    `- Created: ${new Date().toISOString()}`,
    "",
    "## Memory",
    "",
    body
  ].join("\n");

  const parsed = parseJsonResult(await runCliWithInput(config, ["crystallize", "--title", title, "--tags", tags, "--log"], content));
  if (!parsed.ok) {
    return {
      content: [{ type: "text", text: failOpenText("store", parsed) }],
      details: { error: "store_unavailable", message: parsed.error }
    };
  }

  let indexResult;
  if (config.autoIndexAfterWrite) {
    indexResult = parseJsonResult(await runCli(config, ["index", "--rebuild"]));
  }

  return {
    content: [{
      type: "text",
      text: `Stored in LLM Wiki: ${parsed.value.wiki_link ?? parsed.value.path}${indexResult?.ok ? `\nIndex rebuilt: ${indexResult.value.indexed_chunks ?? 0} chunks.` : ""}`
    }],
    details: {
      action: "stored",
      source: "astor-wiki-memory",
      ...parsed.value,
      index: indexResult?.ok ? indexResult.value : undefined
    }
  };
}

function recallSchema() {
  return {
    type: "object",
    additionalProperties: false,
    properties: {
      query: { type: "string", description: "Search query for LLM Wiki memory recall." },
      limit: { type: "number", description: "Max results to return." },
      includeFullText: { type: "boolean", description: "Return chunk text when true; default summary only." },
      maxCharsPerItem: { type: "number", description: "Maximum rendered characters per result." },
      maxTokens: { type: "number", description: "Total recall token budget." },
      scope: { type: "string", description: "Optional wiki scope, e.g. wiki:topics or wiki:synthesis." }
    },
    required: ["query"]
  };
}

const getSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    id: { type: "string" },
    lookup: { type: "string" },
    maxTokens: { type: "number" }
  }
};

const storeSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    text: { type: "string" },
    body: { type: "string" },
    title: { type: "string" },
    category: { type: "string" },
    scope: { type: "string" },
    importance: { type: "number" }
  }
};

const emptySchema = { type: "object", additionalProperties: false, properties: {} };

function registerTool(api, factory, options) {
  api.registerTool(factory, options);
}

const plugin = {
  id: "astor-wiki-memory",
  name: "LLM Wiki Memory",
  description: "OpenClaw thin adapter for the shared LLM Wiki hybrid semantic index.",
  kind: "memory",
  register(api) {
    const config = normalizeConfig(api.pluginConfig);

    registerTool(api, () => ({
      name: "memory_recall",
      label: "Memory Recall",
      description: "Mandatory recall step: search the LLM Wiki hybrid semantic index before answering questions about prior work, decisions, fixes, preferences, OpenClaw/Hermes state, or repeated problems. Fail-open if unavailable.",
      parameters: recallSchema(),
      execute: async (_toolCallId, params) => recall(config, params ?? {})
    }), { name: "memory_recall" });

    registerTool(api, () => ({
      name: "wiki_recall",
      label: "Wiki Recall",
      description: "Search the shared LLM Wiki memory index with a strict token budget.",
      parameters: recallSchema(),
      execute: async (_toolCallId, params) => recall(config, params ?? {})
    }), { name: "wiki_recall" });

    registerTool(api, () => ({
      name: "wiki_get",
      label: "Wiki Get",
      description: "Read one exact recalled wiki chunk by id. Use only after memory_recall/wiki_recall.",
      parameters: getSchema,
      execute: async (_toolCallId, params) => get(config, params ?? {})
    }), { name: "wiki_get" });

    registerTool(api, () => ({
      name: "memory_store",
      label: "Memory Store",
      description: "Crystallize important root causes, decisions, SOPs, and pitfalls into the LLM Wiki. Do not store raw chat logs.",
      parameters: storeSchema,
      execute: async (_toolCallId, params) => crystallize(config, params ?? {}, "OpenClaw memory")
    }), { name: "memory_store" });

    registerTool(api, () => ({
      name: "wiki_crystallize",
      label: "Wiki Crystallize",
      description: "Write a high-quality crystallized memory page into the LLM Wiki and rebuild the local index.",
      parameters: storeSchema,
      execute: async (_toolCallId, params) => crystallize(config, params ?? {}, "OpenClaw crystallized memory")
    }), { name: "wiki_crystallize" });

    registerTool(api, () => ({
      name: "memory_update",
      label: "Memory Update",
      description: "Append a superseding crystallized update to the LLM Wiki. Prefer explicit title/body with the corrected state.",
      parameters: storeSchema,
      execute: async (_toolCallId, params) => crystallize(config, params ?? {}, "OpenClaw memory update")
    }), { name: "memory_update" });

    registerTool(api, () => ({
      name: "memory_forget",
      label: "Memory Forget",
      description: "Safe forget guard for the Markdown source of truth. It does not delete automatically.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          memoryId: { type: "string" },
          reason: { type: "string" }
        }
      },
      execute: async () => ({
        content: [{ type: "text", text: "LLM Wiki Memory does not automatically delete Markdown source-of-truth pages. Edit the relevant wiki page manually, then run wiki_index_update." }],
        details: { action: "forget_requires_manual_edit", source: "astor-wiki-memory" }
      })
    }), { name: "memory_forget" });

    registerTool(api, () => ({
      name: "wiki_index_update",
      label: "Wiki Index Update",
      description: "Rebuild the LLM Wiki memory index from Markdown source.",
      parameters: emptySchema,
      execute: async () => indexUpdate(config)
    }), { name: "wiki_index_update" });

    registerTool(api, () => ({
      name: "memory_stats",
      label: "Memory Stats",
      description: "Show LLM Wiki Memory index status.",
      parameters: emptySchema,
      execute: async () => stats(config)
    }), { name: "memory_stats" });

    registerTool(api, () => ({
      name: "wiki_stats",
      label: "Wiki Stats",
      description: "Show LLM Wiki Memory index status.",
      parameters: emptySchema,
      execute: async () => stats(config)
    }), { name: "wiki_stats" });

    api.logger.info?.("astor-wiki-memory: registered LLM Wiki memory tools (fail-open CLI adapter)");
  }
};

export default plugin;
