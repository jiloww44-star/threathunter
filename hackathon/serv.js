export async function reasonWithSERV(userRequest) {
  const apiKey = process.env.SERV_API_KEY;
  if (!apiKey) throw new Error("SERV_API_KEY is not configured.");
  const baseUrl = process.env.SERV_API_BASE_URL || "https://inference-api.openserv.ai/v1";
  const model = process.env.SERV_MODEL || "SERV-Standard";
  const schema = {agent_id:"string",action:"READ|CREATE|UPDATE|DELETE|TRANSFER|PUBLISH|GRANT|ADMIN",tool:"string",resource:"string",data_class:"PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED",environment:"DEVELOPMENT|STAGING|PRODUCTION",external_side_effect:true,target:"string",purpose:"string",requested_effect:"string",risk_flags:["string"],uncertainty:"LOW|MEDIUM|HIGH",reasoning_summary:"short summary"};
  const system = [
    "You are the reasoning layer for LOG_ON, an Agent Governance + Agent Assurance product.",
    "Do NOT authorize anything. Structure and assess the proposed agent action so an independent deterministic policy engine can decide.",
    "Return JSON only.", "Schema:", JSON.stringify(schema), "Use conservative values when ambiguous."
  ].join("\\n");
  const response = await fetch(baseUrl.replace(/\\\/$/, "") + "/chat/completions", {
    method:"POST", headers:{"Content-Type":"application/json", "Authorization":"Bearer " + apiKey},
    body:JSON.stringify({model, temperature:0.1, messages:[{role:"system",content:system},{role:"user",content:userRequest}]})
  });
  if (!response.ok) throw new Error("SERV request failed (" + response.status + "): " + (await response.text()).slice(0,500));
  const payload = await response.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) throw new Error("SERV returned no assistant content.");
  const cleaned = String(content).trim().replace(/^```json\\s*/i, "").replace(/^```\\s*/i, "").replace(/```$/i, "").trim();
  try { return JSON.parse(cleaned); } catch { throw new Error("SERV returned non-JSON reasoning output."); }
}