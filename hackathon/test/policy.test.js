import test from "node:test";
import assert from "node:assert/strict";
import { evaluatePolicy } from "../policy.js";

test("public read passes", () => {
  assert.equal(
    evaluatePolicy({
      agent_id: "a1",
      action: "READ",
      tool: "web",
      resource: "public:web",
      data_class: "PUBLIC",
      environment: "DEVELOPMENT",
      external_side_effect: false
    }).decision,
    "PASS"
  );
});

test("production update escalates", () => {
  assert.equal(
    evaluatePolicy({
      agent_id: "a1",
      action: "UPDATE",
      tool: "crm",
      resource: "customer:123",
      data_class: "INTERNAL",
      environment: "PRODUCTION",
      external_side_effect: false
    }).decision,
    "ESCALATE"
  );
});

test("admin grant blocks", () => {
  assert.equal(
    evaluatePolicy({
      agent_id: "a1",
      action: "GRANT",
      tool: "iam",
      resource: "role:admin",
      data_class: "INTERNAL",
      environment: "PRODUCTION",
      external_side_effect: false
    }).decision,
    "BLOCK"
  );
});

test("restricted data mutation blocks", () => {
  assert.equal(
    evaluatePolicy({
      agent_id: "a1",
      action: "UPDATE",
      tool: "db",
      resource: "vault:secrets",
      data_class: "RESTRICTED",
      environment: "DEVELOPMENT",
      external_side_effect: false
    }).decision,
    "BLOCK"
  );
});

test("missing tool is not authorized", () => {
  assert.equal(
    evaluatePolicy({
      agent_id: "a1",
      action: "READ",
      resource: "public:web",
      data_class: "PUBLIC",
      environment: "DEVELOPMENT",
      external_side_effect: false
    }).decision,
    "BLOCK"
  );
});
