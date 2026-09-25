const HIGH_IMPACT = new Set(["DELETE", "TRANSFER", "PUBLISH"]);
const ALWAYS_BLOCK = new Set(["GRANT", "ADMIN"]);

export function evaluatePolicy(request) {
  const required = ["agent_id", "action", "tool", "resource", "environment"];
  const missing = required.filter((key) => !request?.[key]);

  if (missing.length) {
    return {
      decision: "BLOCK",
      reasons: ["Missing required control fields: " + missing.join(", ")],
      controls: baseControls(request)
    };
  }
  if (ALWAYS_BLOCK.has(request.action)) {
    return {
      decision: "BLOCK",
      reasons: ["Requested capability is outside the autonomous authority boundary."],
      controls: baseControls(request)
    };
  }
  if (request.data_class === "RESTRICTED" && request.action !== "READ") {
    return {
      decision: "BLOCK",
      reasons: ["Restricted data cannot be modified or exported by the MVP."],
      controls: baseControls(request)
    };
  }
  if (HIGH_IMPACT.has(request.action)) {
    return {
      decision: "ESCALATE",
      reasons: ["High-impact action requires independent human approval."],
      controls: { ...baseControls(request), approval: false }
    };
  }
  if (request.environment === "PRODUCTION" && request.action === "UPDATE") {
    return {
      decision: "ESCALATE",
      reasons: ["Production update requires independent human approval."],
      controls: { ...baseControls(request), approval: false }
    };
  }
  if (request.external_side_effect === true && request.action !== "READ") {
    return {
      decision: "ESCALATE",
      reasons: ["External side effect detected; approval boundary applies."],
      controls: { ...baseControls(request), approval: false }
    };
  }
  return {
    decision: "PASS",
    reasons: ["Identity, capability, resource and environment checks passed."],
    controls: { ...baseControls(request), approval: true }
  };
}

function baseControls(request) {
  return {
    identity: Boolean(request?.agent_id),
    permissions: Boolean(request?.action),
    tools: Boolean(request?.tool),
    data_access: Boolean(request?.resource),
    runtime: Boolean(request?.environment),
    approval: true,
    audit: true
  };
}
