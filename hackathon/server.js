import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { reasonWithSERV } from "./serv.js";
import { evaluatePolicy } from "./policy.js";
import { McpAssuranceGateway } from "./mcp-gateway.js";


const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");
const port = Number(process.env.PORT || 3000);
const auditEvents = [];
const mcpGateway = new McpAssuranceGateway();

function canonicalEvent(event) {
  const { event_hash, ...unsigned } = event;
  return unsigned;
}

function hashEvent(event) {
  return crypto.createHash("sha256")
    .update(JSON.stringify(canonicalEvent(event)))
    .digest("hex");
}

function recordAudit(event) {
  const previousHash = auditEvents.at(-1)?.event_hash || "GENESIS";
  const enriched = {
    event_id: "evt-" + String(auditEvents.length + 1).padStart(5, "0"),
    timestamp: new Date().toISOString(),
    ...event,
    previous_hash: previousHash
  };
  enriched.event_hash = hashEvent(enriched);
  auditEvents.push(enriched);
  return enriched;
}

function verifyAuditChain() {
  let previousHash = "GENESIS";
  for (const event of auditEvents) {
    if (event.previous_hash !== previousHash) {
      return {
        verified: false,
        count: auditEvents.length,
        invalid_event_id: event.event_id,
        reason: "Previous-hash link mismatch."
      };
    }
    if (hashEvent(event) !== event.event_hash) {
      return {
        verified: false,
        count: auditEvents.length,
        invalid_event_id: event.event_id,
        reason: "Event hash mismatch."
      };
    }
    previousHash = event.event_hash;
  }
  return {
    verified: true,
    count: auditEvents.length,
    head_hash: previousHash
  };
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body)
  });
  res.end(body);
}

async function readJson(req) {
  return await new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
      if (data.length > 100000) reject(new Error("Request too large."));
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(data || "{}"));
      } catch {
        reject(new Error("Invalid JSON."));
      }
    });
    req.on("error", reject);
  });
}

function sendFile(res, filePath) {
  fs.readFile(filePath, (error, data) => {
    if (error) {
      res.writeHead(404);
      return res.end("Not found");
    }
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store"
    });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/api/health") {
      return sendJson(res, 200, {
        product: "LOG_ON Assurance Gate",
        serv_configured: Boolean(process.env.SERV_API_KEY),
        model: process.env.SERV_MODEL || "SERV-Standard",
        mcp_gateway: true
      });
    }
    if (req.method === "GET" && req.url === "/api/mcp/tools") {
      const tools = await mcpGateway.connect().then(() => mcpGateway.listTools());
      return sendJson(res, 200, { count: tools.length, tools });
    }
    if (req.method === "POST" && req.url === "/api/mcp/call") {
      const body = await readJson(req);
      const agent_id = String(body.agent_id || "demo-agent").trim();
      const tool_name = String(body.tool_name || "").trim();
      if (!tool_name) return sendJson(res, 400, { error: "tool_name is required" });

      const result = await mcpGateway.governAndCall({
        agent_id,
        tool_name,
        arguments: body.arguments && typeof body.arguments === "object" ? body.arguments : {}
      });

      const audit = recordAudit({
        product: "LOG_ON Assurance Gate",
        agent_id,
        action: result.control?.action || "UNKNOWN",
        tool: tool_name,
        resource: result.control?.resource || "UNKNOWN",
        decision: result.policy.decision,
        executed: result.executed,
        source: "MCP -> LOG_ON AAGATE -> deterministic policy engine"
      });

      return sendJson(res, 200, { ...result, audit, audit_verification: verifyAuditChain() });
    }
    if (req.method === "GET" && req.url === "/api/audit") {
      return sendJson(res, 200, {
        count: auditEvents.length,
        events: auditEvents,
        verification: verifyAuditChain()
      });
    }
    if (req.method === "GET" && req.url === "/api/audit/verify") {
      const verification = verifyAuditChain();
      return sendJson(res, verification.verified ? 200 : 409, verification);
    }
    if (req.method === "POST" && req.url === "/api/govern") {
      const body = await readJson(req);
      const userRequest = String(body.request || "").trim();
      if (!userRequest) return sendJson(res, 400, { error: "request is required" });

      const serv = await reasonWithSERV(userRequest);
      const policy = evaluatePolicy(serv);
      const audit = recordAudit({
        product: "LOG_ON Assurance Gate",
        agent_id: serv.agent_id,
        action: serv.action,
        tool: serv.tool,
        resource: serv.resource,
        decision: policy.decision,
        source: "SERV -> deterministic policy engine"
      });

      return sendJson(res, 200, {
        serv,
        policy,
        audit,
        audit_verification: verifyAuditChain(),
        principle: "The model may propose. The policy plane decides. The gateway enforces. The assurance plane records."
      });
    }
    return sendFile(res, path.join(publicDir, "index.html"));
  } catch (error) {
    return sendJson(res, 500, {
      error: error instanceof Error ? error.message : "Unknown error"
    });
  }
});

server.listen(port, () => console.log("LOG_ON Assurance Gate running on http://localhost:" + port));
process.on("SIGINT", async () => { await mcpGateway.close(); process.exit(0); });
process.on("SIGTERM", async () => { await mcpGateway.close(); process.exit(0); });
