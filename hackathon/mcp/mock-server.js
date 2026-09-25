import { McpServer } from "@modelcontextprotocol/server";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import * as z from "zod";

const server = new McpServer({ name: "logon-demo-tools", version: "0.1.0" });

server.registerTool(
  "market_data_read",
  {
    title: "Read public market data",
    description: "Read simulated public market intelligence.",
    inputSchema: z.object({ query: z.string().default("market") }),
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true
    }
  },
  async ({ query }) => ({
    content: [{
      type: "text",
      text: JSON.stringify({
        tool: "market_data_read",
        query,
        result: "SIMULATED_PUBLIC_MARKET_DATA"
      })
    }]
  })
);

server.registerTool(
  "production_crm_update",
  {
    title: "Update production CRM",
    description: "Update a simulated production customer record.",
    inputSchema: z.object({
      customerId: z.string(),
      field: z.string(),
      value: z.string()
    }),
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  },
  async ({ customerId, field, value }) => ({
    content: [{
      type: "text",
      text: JSON.stringify({
        tool: "production_crm_update",
        customerId,
        field,
        value,
        result: "SIMULATED_PRODUCTION_UPDATE"
      })
    }]
  })
);

server.registerTool(
  "vendor_payment_transfer",
  {
    title: "Transfer vendor payment",
    description: "Transfer a simulated payment to a vendor.",
    inputSchema: z.object({
      vendorId: z.string(),
      amount: z.number()
    }),
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true
    }
  },
  async ({ vendorId, amount }) => ({
    content: [{
      type: "text",
      text: JSON.stringify({
        tool: "vendor_payment_transfer",
        vendorId,
        amount,
        result: "SIMULATED_PAYMENT_EXECUTED"
      })
    }]
  })
);

server.registerTool(
  "grant_admin_access",
  {
    title: "Grant administrator access",
    description: "Grant simulated administrator access.",
    inputSchema: z.object({ principal: z.string() }),
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false
    }
  },
  async ({ principal }) => ({
    content: [{
      type: "text",
      text: JSON.stringify({
        tool: "grant_admin_access",
        principal,
        result: "SIMULATED_ADMIN_GRANTED"
      })
    }]
  })
);

await server.connect(new StdioServerTransport());
