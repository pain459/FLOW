import {el, node, request, uuid, renderAnswer} from './common.js';

export function historyWorkspace({authorized, openAuth, selectView, busy, changed}) {
  let selected = null, offset = 0, pendingReplay = null, selectedActive = false;
  async function refresh() {
    try {
      const list = await request(`/investigations?limit=25&offset=${offset}`);
      el('sessions').replaceChildren();
      for (const s of list.items) {
        const button = node('button', `${s.call_id ? 'Call analysis' : s.mode === 'live_question' ? 'Manual question' : 'Replay'} · ${s.state} · ${s.id.slice(0,8)}\n${s.created_at}`, 'session');
        button.onclick = () => { selected = s.id; details(); };
        el('sessions').append(button);
      }
      el('older-sessions').disabled = list.items.length < 25;
      el('newest-sessions').disabled = offset === 0;
      if (selected) await details();
    } catch (e) { el('details').replaceChildren(node('p', e.message)); }
  }
  async function details() {
    const uid = selected;
    const [session, timeline] = await Promise.all([request(`/investigations/${uid}`), request(`/investigations/${uid}/timeline`)]);
    if (uid !== selected) return;
    selectedActive = !session.ended_at;
    const box = el('details'); box.replaceChildren(node('h3', `${session.state} · recovery ${session.recovery_status}`));
    el('cancel').hidden = Boolean(session.ended_at) || !authorized();
    if (timeline.first_response) {
      const response = node('div'); renderAnswer(timeline.first_response, response); box.append(response);
    }
    for (const d of timeline.decisions) {
      const row = node('div', '', 'decision'); row.append(node('h3', `Step ${d.step + 1} · ${d.observation.observed_at}`));
      const a = d.normalized_answers;
      if (!a?.suspected_subsystem) { row.append(node('p', `No validated response: ${d.validation_status || 'pending'}`)); box.append(row); continue; }
      row.append(node('p', `Suspected: ${a.suspected_subsystem.choice} · expected ordinal severity ${a.incident_severity.score.toFixed(2)} · needs evidence P(true) ${a.needs_more_evidence.noul.toFixed(3)}`));
      row.append(node('p', `Proposed ${d.policy_decision.proposed} → policy ${d.policy_decision.selected} (${d.policy_decision.verdict}); executed: no`));
      for (const [label, probability] of Object.entries(a.next_diagnostic_tool.probabilities)) {
        const line = node('div', '', 'probability'), meter = document.createElement('meter'); meter.min = 0; meter.max = 1; meter.value = probability;
        line.append(node('span', label), meter, node('span', `${(probability * 100).toFixed(1)}%`)); row.append(line);
      }
      row.append(node('p', `Fixed rules: ${d.baseline_decision.subsystem} / ${d.baseline_decision.tool}. Inference ${d.latency_ms.toFixed(0)} ms. Question version: ${d.question_set_version}.`));
      const raw = document.createElement('details'); raw.append(node('summary', 'Observation and source freshness'), node('pre', JSON.stringify(d.observation, null, 2))); row.append(raw); box.append(row);
    }
  }
  async function replays() {
    try {
      const [datasets, tools] = await Promise.all([request('/datasets'), request('/tools')]);
      if (!el('dataset').options.length) for (const d of datasets.datasets) { const option = node('option', `${d.id} · ${d.snapshot_count} observations`); option.value = d.id; el('dataset').append(option); }
      el('tools').replaceChildren(...tools.tools.map(t => node('span', `${t.tool_id} · ${t.execution_enabled ? 'enabled' : 'recommendation only'}`, 'tool')));
    } catch (e) { el('notice').textContent = e.message; }
  }
  el('refresh').onclick = refresh;
  el('older-sessions').onclick = () => { offset = Math.min(10000, offset + 25); refresh(); };
  el('newest-sessions').onclick = () => { offset = 0; refresh(); };
  el('cancel').onclick = async () => {
    try { await request(`/investigations/${selected}/cancel`, {method: 'POST'}); await refresh(); }
    catch (e) { el('details').prepend(node('p', e.message)); }
  };
  el('start-form').onsubmit = async e => {
    e.preventDefault();
    if (!authorized()) { openAuth(); return; }
    if (busy()) { el('notice').textContent = 'Busy · wait for the active analysis.'; return; }
    el('start').disabled = true;
    try {
      const result = await request('/replays', {method: 'POST', body: {dataset_ref: el('dataset').value, mode: 'shadow'}, key: uuid()});
      selected = result.id; pendingReplay = result.id; changed(); selectView('history'); offset = 0; await refresh();
    } catch (error) { el('notice').textContent = error.message; el('start').disabled = false; }
  };
  async function poll() {
    if (pendingReplay) {
      const session = await request(`/investigations/${pendingReplay}`);
      if (session.ended_at) { pendingReplay = null; el('start').disabled = false; changed(); }
    }
    if (selected && (selectedActive || pendingReplay)) await details();
  }
  return {refresh, replays, poll};
}
