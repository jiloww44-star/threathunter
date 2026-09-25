import test from "node:test";
import assert from "node:assert/strict";
import { McpAssuranceGateway } from "../mcp-gateway.js";

test("MCP read tool executes only after LOG_ON allows it", async () => {
  const gateway = new McpAssuranceGateway();
  try {
    const tools = await gateway.connect().then(() => gateway.listTools());
    assert.equal(tools.length, 4);

    const read = await gateway.governAndCall({
      agent_id: "demo-agent",
      tool_name: "market_data_read",
      arguments: { query: "AI infrastructure" }
    });

    assert.equal(read.policy.decision, "PASS");
    assert.equal(read.executed, true);
    assert.match(read.result.content[0].text, /SIMULATED_PUBLIC_MARKET_DATA/);
  } finally {
    await gateway.close();
  }
});

test("MCP production write is stopped before execution", async () => {
  const gateway = new McpAssuranceGateway();
  try {
    const result = await gateway.governAndCall({
      agent_id: "demo-agent",
      tool_name: "production_crm_update",
      arguments: {
        customerId: "C-1",
        field: "status",
        value: "approved"
      }
    });

    assert.equal(result.policy.decision, "ESCALATE");
    assert.equal(result.executed, false);
    assert.equal(result.result, undefined);
  } finally {
    await gateway.close();
  }
});

test("MCP admin grant is blocked before execution", async () => {
  const gateway = new McpAssuranceGateway();
  try {
    const result = await gateway.governAndCall({
      agent_id: "demo-agent",
      tool_name: "grant_admin_access",
      arguments: { principal: "demo-agent" }
    });

    assert.equal(result.policy.decision, "BLOCK");
    assert.equal(result.executed, false);
    assert.equal(result.result, undefined);
  } finally {
    await gateway.close();
  }
});
