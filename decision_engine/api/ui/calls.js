import {el, node, request, uuid, stamp, ms, renderAnswer} from './common.js';

export function callsWorkspace({authorized, openAuth, busy, changed}) {
  let selected = null, detail = null, cursor = null, traceFilter = null;
  let listing = 0, selection = 0, pending = null, submitting = false;
  const outcomeLabel = value => ({success: 'Successful', business_rejection: 'Business rejection', http_rejection: 'HTTP rejection', infrastructure_error: 'Server error'})[value] || value;

  function controls() {
    const saved = detail?.analysis;
    el('explain').textContent = saved ? 'View saved analysis' : 'Explain this call';
    el('explain').disabled = !selected || !detail || submitting || (!saved && (busy() || Boolean(pending)));
    el('reanalyse').hidden = !saved?.ended_at;
    el('reanalyse').disabled = submitting || busy() || Boolean(pending);
    el('cancel-analysis').hidden = !pending || !authorized();
    if (busy() && !pending && !saved) el('ask-notice').textContent = 'Busy · another analysis is in progress. Call browsing stays available.';
  }

  async function refresh(older = false) {
    const generation = ++listing;
    const params = new URLSearchParams({lookback_seconds: el('call-window').value, outcome: el('call-outcome').value, limit: '25'});
    if (el('call-route').value) params.set('route', el('call-route').value);
    if (traceFilter) { params.set('trace_id', traceFilter); params.set('lookback_seconds', '86400'); }
    if (older && cursor) params.set('cursor', cursor);
    el('calls-notice').textContent = 'Reading request metadata…';
    try {
      const page = await request('/calls?' + params);
      if (generation !== listing) return;
      cursor = page.next_cursor;
      el('calls-list').replaceChildren();
      for (const call of page.items) {
        const row = node('button', '', 'call-row' + (call.id === selected ? ' selected' : ''));
        row.dataset.callId = call.id;
        const head = node('div', '', 'call-row-head');
        head.append(node('span', stamp(call.completed_at).slice(11,23) + ' UTC'), node('span', call.client_kind));
        const foot = node('div', '', 'call-row-foot');
        foot.append(node('span', `HTTP ${call.status_code} · ${outcomeLabel(call.outcome)}`, 'badge ' + (call.status_code >= 500 ? 'bad' : call.status_code >= 400 ? 'warn' : 'good')), node('span', ms(call.duration_ms)));
        row.append(head, node('strong', `${call.method} ${call.route}`, 'call-route'), foot);
        row.onclick = () => select(call.id);
        el('calls-list').append(row);
      }
      el('call-count').textContent = `${page.items.length} shown`;
      el('more-calls').hidden = !cursor;
      el('clear-trace').hidden = !traceFilter;
      el('calls-notice').textContent = page.quality.status === 'UNKNOWN' ? `UNKNOWN · ${page.notice || 'Request logs unavailable. This is not an empty healthy result.'}` : page.items.length ? 'Select a call. Laya has not been invoked.' : 'No recorded calls in this window. Generate traffic or widen the window; telemetry may still be arriving.';
      if (traceFilter && page.items.length === 1) await select(page.items[0].id);
    } catch (e) { if (generation === listing) el('calls-notice').textContent = `UNKNOWN · ${e.message}`; }
  }

  function pair(dl, label, value, wide = false) {
    const group = node('div', '', wide ? 'wide' : ''); group.append(node('dt', label), node('dd', value ?? 'Unknown')); dl.append(group);
  }
  function section(box, title) { const head = node('div', '', 'section-head'); head.append(node('h3', title)); box.append(head); return head; }

  function renderDetail(data) {
    const call = data.call, box = el('call-details'); box.classList.remove('empty-state'); box.replaceChildren();
    const summary = node('div', '', 'call-summary');
    for (const [label, value] of [['HTTP response', String(call.status_code)], ['Duration', ms(call.duration_ms)], ['Outcome', outcomeLabel(call.outcome)]]) {
      const tile = node('div'); tile.append(node('small', label), node('strong', value)); summary.append(tile);
    }
    box.append(node('h3', `${call.method} ${call.route}`, 'call-route'), node('p', stamp(call.completed_at) + ' · UTC'), summary);
    const meta = node('dl', '', 'detail-meta');
    pair(meta, 'Call ID · unique attempt', call.id); pair(meta, 'Request ID · may repeat on retries', call.request_id);
    pair(meta, 'Started', stamp(call.started_at)); pair(meta, 'Trace ID', call.trace_id);
    if (call.error_code || call.error_class) pair(meta, 'Recorded error signals', [call.error_code, call.error_class].filter(Boolean).join(' · '), true);
    box.append(meta);
    const links = node('div', '', 'links');
    for (const [label, url] of [['Full trace in Grafana', data.links?.trace], ['Correlated logs in Grafana', data.links?.logs]]) {
      if (!url) continue;
      const a = node('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; links.append(a);
    }
    box.append(links);
    el('trace-status').textContent = `TRACE ${data.trace.status}`;
    el('trace-status').className = 'badge ' + (data.trace.status === 'AVAILABLE' ? 'good' : 'neutral');
    const head = section(box, 'Recorded execution path');
    const refresh = node('button', 'Refresh evidence', 'button quiet'); refresh.onclick = () => select(call.id); head.append(refresh);
    if (!data.trace.spans.length) box.append(node('p', 'Trace unavailable or still arriving. The HTTP record remains visible; no execution path is assumed.'));
    else {
      const waterfall = node('div', '', 'waterfall');
      const spans = data.trace.spans;
      const total = Math.max(call.duration_ms, ...spans.map(s => Math.max(0, s.start_offset_ms) + s.duration_ms), 1);
      const byId = new Map(spans.map(s => [s.id, s]));
      for (const s of spans) {
        let depth = 0, parent = s.parent_id; const seen = new Set([s.id]);
        while (parent && byId.has(parent) && depth < 5 && !seen.has(parent)) { seen.add(parent); depth++; parent = byId.get(parent).parent_id; }
        const row = node('div', '', 'span-row');
        const label = node('div', s.label, 'span-label'); label.style.paddingLeft = `${depth * 10}px`; label.append(node('small', `${s.service} / ${s.operation}${s.error ? ' · error' : ''}`));
        const track = node('div', '', 'span-track'), bar = node('div', '', 'span-bar' + (s.error ? ' bad' : ''));
        bar.style.left = `${Math.max(0, s.start_offset_ms) / total * 100}%`; bar.style.width = `${Math.min(100, s.duration_ms / total * 100)}%`; track.append(bar);
        row.append(label, track, node('span', ms(s.duration_ms), 'span-ms')); waterfall.append(row);
      }
      box.append(waterfall);
      if (data.trace.status === 'PARTIAL') box.append(node('p', `Partial timeline; ${data.trace.omitted_spans} spans omitted by evidence bounds.`));
    }
    section(box, 'Correlated log evidence');
    if (!data.logs.length) box.append(node('p', `${data.logs_status} · no correlated application log records available.`));
    for (const log of data.logs) {
      const row = node('div', [log.event, log.error_code, log.error_class].filter(Boolean).join(' · '), 'evidence-row'); row.append(node('small', `${stamp(log.observed_at)} · ${log.service}`)); box.append(row);
    }
    section(box, 'Asynchronous follow-up');
    box.append(node('p', 'Outbox publication and consumer processing follow the HTTP response. They have separate trace boundaries.'));
    if (!data.related_events.length) box.append(node('p', 'No correlated follow-up recorded yet. This does not prove delivery failure or success.'));
    for (const event of data.related_events) {
      const row = node('div', `${event.service} · ${event.event}`, 'evidence-row'); row.append(node('small', stamp(event.observed_at)));
      if (event.trace_id) row.append(node('small', `Related trace: ${event.trace_id}`)); box.append(row);
    }
    const metrics = document.createElement('details');
    const metricsBody = node('div'); metrics.append(node('summary', 'System measurements at this call’s time · preceding 30s'), metricsBody);
    let loaded = false;
    metrics.ontoggle = async () => {
      if (!metrics.open || loaded) return; loaded = true; metricsBody.replaceChildren(node('p', 'Reading historical measurements…'));
      try {
        const state = await request(`/calls/${call.id}/measurements`);
        metricsBody.replaceChildren(node('p', `Historical window ends ${stamp(state.observed_at)}. Current system recovery is not used as call-time evidence.`), node('pre', JSON.stringify(state, null, 2)));
      } catch (e) { loaded = false; metricsBody.replaceChildren(node('p', `UNKNOWN · ${e.message}`)); }
    };
    box.append(metrics);
  }

  async function select(uid) {
    const generation = ++selection; selected = uid; detail = null;
    for (const row of el('calls-list').children) row.classList.toggle('selected', row.dataset.callId === uid);
    el('call-details').replaceChildren(node('p', 'Reading call evidence…'));
    el('answer').replaceChildren(node('p', 'No analysis requested for this selection.'));
    el('analysis-status').textContent = 'NOT REQUESTED'; controls();
    try {
      const data = await request('/calls/' + uid);
      if (generation !== selection) return;
      detail = data; renderDetail(data); controls();
      el('ask-notice').textContent = 'Only Explain this call or Re-analyze invokes Laya.';
      if (data.analysis) await showAnalysis(data.analysis.id, uid);
    } catch (e) {
      if (generation === selection) { el('call-details').replaceChildren(node('p', `UNKNOWN · ${e.message}`)); el('explain').disabled = true; }
    }
  }

  async function showAnalysis(uid, callId) {
    const [session, timeline] = await Promise.all([request(`/investigations/${uid}`), request(`/investigations/${uid}/timeline`)]);
    if (selected !== callId) return;
    detail.analysis = session;
    if (!session.ended_at && !pending) pending = {sessionId: uid, callId};
    el('analysis-status').textContent = session.ended_at ? 'SAVED' : session.state;
    if (timeline.first_response) renderAnswer(timeline.first_response, el('answer'));
    else el('answer').replaceChildren(node('p', session.ended_at ? `No validated response (${session.last_error || session.state}). No actions executed.` : 'Collecting call-time evidence and waiting for the requested Laya response…'));
    if (session.ended_at) el('ask-notice').textContent = `Saved analysis · ${uid.slice(0,8)}. Reopening it performs no inference.`;
    controls();
  }

  async function analyse(reanalyse = false) {
    if (!selected || !detail || submitting) return;
    if (!reanalyse && detail.analysis) return showAnalysis(detail.analysis.id, selected);
    if (!authorized()) { openAuth(); return; }
    if (busy() || pending) { el('ask-notice').textContent = 'Busy · wait for the active analysis.'; return; }
    const uid = selected; submitting = true; controls();
    try {
      const result = await request(`/calls/${uid}/explain`, {method: 'POST', body: {reanalyse}, key: uuid()});
      pending = {sessionId: result.id, callId: uid}; changed();
      if (selected === uid) { el('ask-notice').textContent = result.cached ? 'Opening saved analysis…' : 'Analysis requested. Evidence is frozen at the call’s time; no experiment metadata is sent.'; await showAnalysis(result.id, uid); }
    } catch (e) { el('ask-notice').textContent = e.message; }
    finally { submitting = false; controls(); }
  }

  async function poll() {
    if (!pending) return;
    const current = pending;
    try {
      const row = await request(`/investigations/${current.sessionId}`);
      if (selected === current.callId) await showAnalysis(current.sessionId, current.callId);
      if (row.ended_at && pending === current) { pending = null; changed(); controls(); }
    } catch (e) { el('ask-notice').textContent = `Analysis status unavailable · ${e.message}`; }
  }

  el('call-filters').onchange = () => { cursor = null; refresh(); };
  el('call-filters').onsubmit = e => e.preventDefault();
  el('refresh-calls').onclick = () => refresh();
  el('more-calls').onclick = () => refresh(true);
  el('trace-form').onsubmit = e => { e.preventDefault(); traceFilter = el('trace-id').value.trim(); cursor = null; refresh(); };
  el('clear-trace').onclick = () => { traceFilter = null; refresh(); };
  el('explain').onclick = () => analyse(); el('reanalyse').onclick = () => analyse(true);
  el('cancel-analysis').onclick = async () => {
    if (!pending) return;
    try { await request(`/investigations/${pending.sessionId}/cancel`, {method: 'POST'}); await poll(); }
    catch (e) { el('ask-notice').textContent = e.message; }
  };
  return {refresh, controls, poll};
}
