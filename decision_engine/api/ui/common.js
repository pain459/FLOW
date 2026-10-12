export const el = id => document.getElementById(id);
export function node(tag, text = '', cls) {
  const n = document.createElement(tag);
  n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
export function uuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const h = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
export async function request(path, {method = 'GET', body, key} = {}) {
  const headers = {'Accept': 'application/json'};
  if (method !== 'GET') {
    headers['X-Requested-With'] = 'PulsePay';
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (key) headers['Idempotency-Key'] = key;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const r = await fetch('/api/v1/intelligence' + path, {method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal});
    const result = await r.json();
    if (!r.ok) {
      const error = new Error(`${r.status === 429 ? 'Busy' : 'Request refused'} (${r.status}): ${typeof result.detail === 'string' ? result.detail : result.code || 'unavailable'}`);
      error.status = r.status;
      throw error;
    }
    return result;
  } finally { clearTimeout(timer); }
}
export const stamp = value => value ? new Date(value).toISOString().replace('T', ' ').replace('+00:00', 'Z') : 'Unknown';
export const ms = value => typeof value === 'number' ? `${value.toFixed(value < 10 ? 2 : 1)} ms` : 'Unknown';
export function renderAnswer(a, box) {
  box.replaceChildren(node('h3', `Possible reason: ${a.reason}`));
  box.append(node('p', `Hypothesis: ${a.suspected_subsystem}. Suggested human check: ${a.next_check}. No action executed.`));
  if (a.override_reason) box.append(node('p', `Unsupported model proposal withheld (${a.override_reason}).`));
  box.append(node('p', `Evidence window ends ${stamp(a.observed_at)} · ${a.window_seconds}s. This is a hypothesis, not a confirmed cause.`, 'muted'));
  const facts = document.createElement('ul');
  for (const fact of a.evidence) facts.append(node('li', fact));
  box.append(node('h4', 'Observed facts'), a.evidence.length ? facts : node('p', 'No failure-specific evidence captured.'));
  box.append(node('h4', 'Possible explanations'));
  for (const h of a.hypotheses) {
    const row = node('div', '', 'probability');
    const meter = document.createElement('meter'); meter.min = 0; meter.max = 1; meter.value = h.model_score;
    row.append(node('span', `${h.reason} · ${h.symptom_support ? 'supported symptoms' : 'unsupported'}`), meter, node('span', `${(h.model_score * 100).toFixed(1)}%`)); box.append(row);
  }
  const unknowns = document.createElement('ul'); for (const v of a.unknowns) unknowns.append(node('li', v));
  box.append(node('h4', 'Missing evidence'), unknowns);
  const detail = document.createElement('details'); detail.append(node('summary', 'Model scores and interpretation'), node('p', a.score_interpretation), node('p', `Needs more evidence P(true): ${a.needs_more_evidence_probability.toFixed(3)}. Severity expected ordinal: ${a.severity_expected_ordinal.toFixed(2)}.`)); box.append(detail);
}
