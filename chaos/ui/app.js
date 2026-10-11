const $ = (selector) => document.querySelector(selector);
const model = { scenarios: [], selected: null, token: null, status: null, job: null, busy: false };
function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text ?? ''; if (className) node.className = className; return node; }
function tone(value) { return ['PASS','HEALTHY','COMPLETED','RESTORED'].includes(value) ? 'good' : ['FAILED','RESILIENCE_FAILURE','INVALID','FAIL','UNHEALTHY'].includes(value) ? 'bad' : 'warn'; }
function badge(value, label) { return element('span', label ?? value ?? 'UNKNOWN', `badge ${tone(value)}`); }
function notice(message) { $('#notice').hidden = !message; $('#notice').textContent = message || ''; }
function pretty(value) { return JSON.stringify(value, null, 2); }
async function request(path, body) {
  const options = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': model.token }, body: JSON.stringify(body) };
  const response = await fetch(path, options); const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.message || pretty(data.detail) || `HTTP ${response.status}`);
  return data;
}
function select(scenario) {
  model.selected = scenario;
  document.querySelectorAll('.scenario').forEach(node => { const selected = node.dataset.scenario === scenario.id; node.classList.toggle('selected', selected); node.setAttribute('aria-pressed', selected); });
  $('#scenario-title').textContent = scenario.id.replace(/^[0-9]+-/, '').replaceAll('-', ' ');
  $('#scenario-description').textContent = scenario.description;
  $('#scenario-facts').replaceChildren();
  for (const [name, value] of [['Target service', scenario.target], ['Injector', scenario.injector], ['Exposure', `${scenario.duration_seconds} seconds`], ['Definition', 'Native Chaos Toolkit YAML']]) { const item = element('div'); item.append(element('dt', name), element('dd', value)); $('#scenario-facts').append(item); }
  $('#scenario-note').textContent = !scenario.enabled ? 'Unavailable: kernel CPU containment has not been independently verified.' : scenario.database_opt_in ? 'Database interruption needs explicit deployment opt-in. A previous run reached the load safety ceiling.' : scenario.requires_proxy ? 'Requires explicit Toxiproxy routing. Preflight checks the actual dependency configuration.' : 'Preflight requires fresh telemetry, stable write traffic and an independent PASS. The exact container target appears in the action output.';
  controls();
}
function controls() {
  const ready = model.status?.controls_ready && !model.busy;
  const active = model.status?.active_experiment;
  const working = model.job?.status === 'RUNNING' || model.status?.browser_job?.status === 'RUNNING';
  $('#preflight').disabled = !ready || working || active || !model.selected?.enabled;
  $('#run').disabled = !ready || working || active || !model.selected?.enabled || !model.status?.workload?.ready;
  $('#abort').disabled = !model.status?.controls_ready || (!active && !working);
  $('#restore').disabled = !ready || working;
}
function renderJob(job) { model.job = job; $('#job-status').textContent = job.status; $('#job-status').className = `badge ${tone(job.status)}`; let output = job.output || `${job.operation}: ${job.status}\n${job.reason || 'Waiting for native framework output…'}`; try { const result = JSON.parse(output.trim().split('\n').at(-1)); if (result.message) output = `${result.message}\n\n${result.remediation || ''}\n\n${output}`; } catch {} $('#job-output').textContent = output; controls(); }
async function action(operation, body = {}) {
  model.busy = true; controls(); notice('');
  try { renderJob(await request(`/api/actions/${operation}`, body)); }
  catch (error) { notice(error.message); }
  finally { model.busy = false; controls(); }
}
async function history() {
  const { items } = await request('/api/runs'); $('#history-count').textContent = `${items.length} retained runs`; const rows = [];
  for (const item of items) {
    const row = element('tr'); row.append(element('td', item.run_id), element('td', item.scenario || 'Unavailable'));
    const verdict = element('td'); verdict.append(badge(item.result)); row.append(verdict);
    const integrity = element('td'); integrity.append(badge(item.integrity?.after || 'UNKNOWN')); row.append(integrity);
    const last = element('td'); const open = element('button', 'View report', 'button quiet'); open.addEventListener('click', () => report(item.run_id).catch(error => notice(error.message))); last.append(open); row.append(last); rows.push(row);
  }
  if (!rows.length) { const row = element('tr'); const cell = element('td', 'No experiments recorded. Start with worker pause after preflight.', 'empty-cell'); cell.colSpan = 5; row.append(cell); rows.push(row); }
  $('#history-body').replaceChildren(...rows);
}
async function report(identifier) {
  const data = await request(`/api/runs/${encodeURIComponent(identifier)}`); $('#report-panel').hidden = false; $('#report-title').textContent = identifier;
  const integrity = data.summary?.integrity?.after || 'UNKNOWN'; const restoration = data.summary?.restoration || 'UNKNOWN';
  $('#report-verdicts').replaceChildren(badge(data.summary?.result), badge(integrity, `Integrity: ${integrity}`), badge(restoration, `Restoration: ${restoration}`));
  $('#report-summary').textContent = pretty(data.failure ? { ...data.summary, failure: data.failure } : data.summary || { status: 'Evidence incomplete' });
  $('#report-timeline').replaceChildren(...data.timeline.map(item => { const node = element('li', item.event); node.append(element('small', item.timestamp)); return node; }));
  $('#report-artifacts').replaceChildren(...data.artifacts.map(name => { const link = element('a', name); link.href = `/api/runs/${encodeURIComponent(identifier)}/artifacts/${encodeURIComponent(name)}`; link.target = '_blank'; link.rel = 'noopener'; return link; }));
  $('#report-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function refresh() {
  try {
    model.status = await request('/api/status');
    for (const [name, selector] of [['gateway','#gateway-status'],['watchdog','#watchdog-status']]) { const value = model.status.controls[name]; $(selector).textContent = value; $(selector).className = tone(value); }
    const active = model.status.active_experiment; $('#active-status').textContent = active?.scenario || 'Idle'; $('#active-id').textContent = active?.run_id || 'No fault is being injected';
    const load = model.status.workload; $('#load-status').textContent = load?.ready ? 'Locust workload ready' : 'Workload prerequisite: action needed'; $('#load-guidance').textContent = [load?.message, load?.remediation].filter(Boolean).join('. ');
    $('#freshness').textContent = `Observed ${new Date(model.status.observed_at).toLocaleTimeString()}`;
    if (!model.status.controls_ready) notice('Experiment controls unavailable. Run make up to start the stack controls. History remains accessible.');
    if (model.job?.status === 'RUNNING') { renderJob(await request(`/api/jobs/${model.job.job_id}`)); if (model.job.status !== 'RUNNING') await history(); }
    else if (model.status.browser_job && (!model.job || model.job.job_id !== model.status.browser_job.job_id)) renderJob(model.status.browser_job);
    controls();
  } catch (error) { notice(`Control state unavailable: ${error.message}`); model.status = null; controls(); }
}
$('#preflight').addEventListener('click', () => action('preflight', { scenario: model.selected.id }));
$('#run').addEventListener('click', () => { $('#confirmation-text').textContent = `${model.selected.id}: ${model.selected.description} Exposure: ${model.selected.duration_seconds} seconds.`; $('#confirmation').showModal(); });
$('#confirm-form').addEventListener('submit', event => { event.preventDefault(); $('#confirmation').close(); action('run', { scenario: model.selected.id, confirm: model.selected.id }); });
$('#cancel-confirm').addEventListener('click', () => $('#confirmation').close());
$('#abort').addEventListener('click', () => action('abort'));
$('#restore').addEventListener('click', () => action('restore'));
$('#refresh').addEventListener('click', async () => { await refresh(); await history().catch(error => notice(error.message)); });
$('#close-report').addEventListener('click', () => { $('#report-panel').hidden = true; });
for (const [id, port] of [['pulsepay-link',8080],['overview-link',8080],['locust-link',8089],['start-load-link',8089],['grafana-link',3000]]) { const url = new URL(location.href); url.port = port; url.pathname = '/'; url.search = ''; url.hash = ''; $(`#${id}`).href = url; }
try {
  model.token = (await request('/api/session')).token;
  model.scenarios = (await request('/api/scenarios')).items;
  for (const scenario of model.scenarios) { const button = element('button', '', `scenario${scenario.enabled ? '' : ' unavailable'}`); button.dataset.scenario = scenario.id; button.setAttribute('aria-pressed', 'false'); button.append(element('strong', scenario.id.replace(/^[0-9]+-/, '').replaceAll('-', ' ')), element('span', `${scenario.target.toUpperCase()} · ${scenario.duration_seconds}s · ${scenario.enabled ? scenario.injector.toUpperCase() : 'UNAVAILABLE'}`)); button.addEventListener('click', () => select(scenario)); $('#scenario-list').append(button); }
  select(model.scenarios.find(item => item.id === '002-worker-pause')); await refresh(); await history(); setInterval(refresh, 2000);
} catch (error) { notice(`Workbench unavailable: ${error.message}`); }
