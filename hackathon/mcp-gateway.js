import path from "node:path";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { evaluatePolicy } from "./policy.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const registryPath = path.join(__dirname, "mcp", "tool-registry.json");
const serverPath = path.join(__dirname, "mcp", "mock-server.js");

export class McpAssuranceGateway {
  constructor() {
    this.client = null;
    this.transport = null;
    this.tools = new Map();
    this.registry = {};
  }

  async connect() {
    if (this.client) return this;

    this.registry = JSON.parse(await fs.readFile(registryPath, "utf8"));
    this.client = new Client({
      name: "logon-assurance-gate",
      version: "0.2.0"
    });
    this.transport = new StdioClientTransport({
      command: process.execPath,
      args: [serverPath]
    });

    await this.client.connect(this.transport);
    const listed = await this.client.listTools();

    for (const tool of listed.tools || []) {
      const control = this.registry[tool.name];
      if (control) {
        this.tools.set(tool.name, { ...tool, control });
      }
    }

    return this;
  }

  async close() {
    if (this.client) {
      await this.client.close();
      this.client = null;
      this.transport = null;
      this.tools.clear();
    }
  }

  listTools() {
    return [...this.tools.values()].map(
      ({ name, title, description, annotations, control }) => ({
        name,
        title,
        description,
        annotations,
        control
      })
    );
  }

  async governAndCall({ agent_id, tool_name, arguments: args = {} }) {
    await this.connect();

    const entry = this.tools.get(tool_name);
    if (!entry) {
      return {
        executed: false,
        tool_name,
        policy: {
          decision: "BLOCK",
          reasons: ["Tool is not registered in the LOG_ON MCP tool registry."],
          controls: {
            identity: Boolean(agent_id),
            permissions: false,
            tools: false,
            data_access: false,
            runtime: false,
            approval: true,
            audit: true
          }
        }
      };
    }

    const { control } = entry;
    const policy = evaluatePolicy({
      agent_id,
      action: control.action,
      tool: tool_name,
      resource: control.resource,
      data_class: control.data_class,
      environment: control.environment,
      external_side_effect: control.external_side_effect
    });

    if (policy.decision !== "PASS") {
      return {
        executed: false,
        tool: {
          name: entry.name,
          title: entry.title,
          annotations: entry.annotations
        },
        control,
        policy
      };
    }

    const result = await this.client.callTool({
      name: tool_name,
      arguments: args
    });

    return {
      executed: true,
      tool: {
        name: entry.name,
        title: entry.title,
        annotations: entry.annotations
      },
      control,
      policy,
      result
    };
  }
}
