import { request, ApiError, money, minorAmount, loadIntent, saveIntent, clearIntent, commitIntent, uuid } from './api.js';

const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const number = value => value === undefined || value === null ? '—' : new Intl.NumberFormat('en-IN').format(value);
const short = value => value ? String(value).slice(0, 8) : '—';
const date = value => value ? new Date(value).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'Not observed';
const age = value => value ? Math.max(0, (Date.now() - new Date(value).getTime()) / 1000) : Infinity;
const kind = status => ['PASS', 'HEALTHY', 'active', 'PROCESSED'].includes(status) ? 'good' : ['FAIL', 'UNHEALTHY'].includes(status) ? 'bad' : ['DEGRADED', 'PENDING_PUBLICATION', 'PENDING_PROCESSING'].includes(status) ? 'warn' : 'neutral';
const badge = (status, label = status) => `<span class="badge ${kind(status)}">${escape(label)}</span>`;
const state = { view: 'overview', data: null, fresh: false, dataError: '', health: null, signals: null, refreshing: false,
  paused: false, accounts: [], accountCursor: null, accountVersion: 0, transfers: [], transferCursor: null,
  transferVersion: 0, directory: new Map(), directoryLoaded: false, pending: loadIntent(), transferBusy: false,
  transferError: null, modalMode: '', dialogGeneration: 0, lastFocus: null, selectedNode: null };

const components = {
  activity: { title: 'Activity client', icon: 'pulse', subtitle: 'Real HTTP requests', description: 'The external client sends modest reads and bidirectional transfers through the same public HTTP API as this dashboard. Its process state is observed independently.' },
  api: { title: 'FastAPI', icon: 'system', subtitle: 'Atomic transfers', description: 'FastAPI validates requests. A transfer commits balances, its immutable ledger pair and outbox event together in PostgreSQL. Optional cache or event delays do not invalidate that commit.' },
  postgres: { title: 'PostgreSQL', icon: 'db', subtitle: 'Source of truth', description: 'PostgreSQL owns account balances, transfers, the ledger and transactional outbox. Redis balances never approve transfers. All displayed overview totals come from one read-only database snapshot.' },
  'outbox-relay': { title: 'Outbox relay', icon: 'transfer', subtitle: 'Publish after commit', description: 'The relay leases committed outbox rows, publishes to Redis Streams, then records publication. A crash may publish an event twice; durable event IDs make duplicate processing safe.' },
  redis: { title: 'Redis', icon: 'stream', subtitle: 'Cache + Streams', description: 'Redis supplies optional TTL-cached summaries and at-least-once event transport. During an outage, core transfers can still commit and the PostgreSQL outbox waits for recovery.' },
  'event-worker': { title: 'Event worker', icon: 'system', subtitle: 'Idempotent effects', description: 'The consumer atomically writes a receipt and notification projection in PostgreSQL before acknowledging the stream message. It reclaims abandoned deliveries after restart.' },
  verifier: { title: 'Integrity verifier', icon: 'shield', subtitle: 'Independent read-only checks', description: 'The verifier uses a separate SELECT-only principal and independent SQL in a repeatable-read, read-only transaction. Unavailable or stale evidence is UNKNOWN; event lag is distinct from financial corruption.' },
};

function verification() {
  const value = state.signals?.verification;
  if (!value) return { status: 'UNKNOWN', reason: 'No independent report available', report: null };
  if (value.source_finished_at && age(value.source_finished_at) > 30) return { status: 'UNKNOWN', reason: 'Independent report is stale', report: null };
  return value;
}
function componentState(name) {
  if (name === 'verifier') { const v = verification(); return { status: v.status, observed_at: v.source_finished_at, reason: v.reason }; }
  if (name === 'activity') {
    const value = state.signals?.activity;
    return !value || age(value.observed_at) > 30 ? { status: 'UNKNOWN', reason: 'No fresh activity observation' } : value;
  }
  if (name === 'api') return !state.health || age(state.health.observed_at) > 30 ? { status: 'UNKNOWN', reason: 'No fresh API observation' } :
    { status: state.health.core_transactions_ready ? 'HEALTHY' : 'UNHEALTHY', reason: state.health.core_transactions_ready ? 'Core transactions ready' : 'Core dependency unavailable', observed_at: state.health.observed_at };
  const value = state.health?.dependencies?.[name];
  return !value || age(value.observed_at) > 30 ? { status: 'UNKNOWN', reason: 'No fresh dependency observation' } : value;
}

function updateAction() {
  $('new-transfer').querySelector('span').textContent = state.pending ? 'Resolve pending transfer' : 'New transfer';
  $('new-transfer').disabled = state.transferBusy;
}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { $('toast').hidden = true; }, 4500); }
function errorText(error) { return `${error.message || 'Request failed'}${error.code ? ` · ${error.code}` : ''}${error.requestId ? ` · Request ${error.requestId}` : ''}`; }

function renderMetrics() {
  const data = state.data;
  if (!data) return;
  const t = data.totals;
  $('metric-funds').textContent = money(t.balance_minor, data.currency);
  $('metric-transfers').textContent = number(t.transfers);
  $('metric-accounts').textContent = number(t.accounts);
  $('metric-pending').textContent = number(t.outbox_pending);
  $('funds-note').textContent = `${money(t.provisioned_minor, data.currency)} explicitly provisioned`;
  $('transfers-note').textContent = `${number(t.ledger_entries)} immutable ledger entries`;
  $('accounts-note').textContent = `${number(t.active_accounts)} active · zero-balance account creation`;
  $('pending-note').textContent = t.outbox_pending ? `Oldest unpublished event: ${Math.round(t.oldest_pending_seconds)}s` : 'No unpublished events in this snapshot';
  $('metrics-grid').classList.toggle('stale', !state.fresh || age(data.observed_at) > 30);
  $('snapshot-time').textContent = `Snapshot ${date(data.observed_at)}`;
  $('recent-table').querySelector('tbody').innerHTML = transferRows(data.recent_transfers);
  renderChart(data.activity);
}

function renderChart(points) {
  const max = Math.max(1, ...points.map(p => p.count)), width = 650, height = 170, left = 32, right = 12, top = 12, bottom = 142;
  const x = i => left + i * (width - left - right) / (points.length - 1);
  const y = value => bottom - value * (bottom - top) / max;
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(p.count).toFixed(2)}`).join(' ');
  const area = `${line} L${x(points.length - 1)},${bottom} L${left},${bottom}Z`;
  const ticks = [0, .5, 1].map(f => `<line x1="${left}" x2="${width - right}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="#293d49" stroke-dasharray="3 5"/><text x="0" y="${y(max * f) + 3}" fill="#6c889a" font-size="9">${Math.round(max * f)}</text>`).join('');
  const labels = [0, 10, 20, 29].map(i => `<text x="${x(i)}" y="163" text-anchor="${i === 29 ? 'end' : 'start'}" fill="#718b9d" font-size="9">${escape(new Date(points[i].at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))}</text>`).join('');
  $('activity-chart').innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Real committed transfers per minute over the last thirty minutes"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#55dfbe" stop-opacity=".22"/><stop offset="100%" stop-color="#55dfbe" stop-opacity="0"/></linearGradient></defs>${ticks}<path d="${area}" fill="url(#chart-fill)"/><path d="${line}" fill="none" stroke="#55dfbe" stroke-width="2" stroke-linejoin="round"/>${labels}</svg>${points.every(p => p.count === 0) ? '<span class="empty-chart">No transfers in this window</span>' : ''}`;
}

function transferRows(rows) {
  if (!rows.length) return '<tr><td colspan="5" class="empty-cell">No transfers yet. Make a synthetic transfer to see the ledger and event pipeline work.</td></tr>';
  return rows.map(t => `<tr><td><button class="table-link mono" data-transfer="${escape(t.id)}">${escape(short(t.id))}${icon('arrow')}</button><span class="table-sub">Committed</span></td><td><span class="route-ref" title="${escape(t.source_ref)}">${escape(t.source_ref)}</span><span class="route-arrow">→</span><span class="route-ref" title="${escape(t.destination_ref)}">${escape(t.destination_ref)}</span></td><td class="number">${escape(money(t.amount_minor, t.currency))}</td><td>${badge(t.event_status, { PROCESSED: 'Delivered', PENDING_PUBLICATION: 'Queued', PENDING_PROCESSING: 'Published' }[t.event_status])}</td><td>${escape(date(t.committed_at))}</td></tr>`).join('');
}

function renderVerification() {
  const v = verification(), checks = v.report?.checks || [];
  $('verification-status').textContent = v.status;
  $('verification-status').className = `verification-state ${kind(v.status)}`;
  $('verification-description').textContent = checks.length ? `${checks.filter(c => c.status === 'PASS').length} of ${checks.length} checks pass · ${date(v.source_finished_at)}` : v.reason.replaceAll('_', ' ').toLowerCase();
  $('overview-checks').innerHTML = checks.slice(0, 4).map(c => `<div class="check-line"><span>${escape(checkName(c.name))}</span>${c.status === 'PASS' ? icon('check') : badge(c.status)}</div>`).join('');
  $('system-verification-status').outerHTML = `<span id="system-verification-status" class="badge ${kind(v.status)}">${escape(v.status)}</span>`;
  $('full-checks').innerHTML = checks.length ? checks.map(c => `<div class="full-check-row"><span>${escape(checkName(c.name))}</span><small>${number(c.inspected_records)} inspected · ${number(c.violations)} violations</small>${badge(c.status)}</div>`).join('') : `<div class="empty-cell">${escape(v.reason.replaceAll('_', ' ').toLowerCase())}. No fresh independent evidence is available.</div>`;
}
function checkName(name) {
  const friendly = { global_conservation: 'Global funds conserved', ledger_balance_reconciliation: 'Account balances reconcile', account_state: 'Account state valid', provisioning_evidence: 'Issuance is traceable', transfer_double_entry: 'Double-entry transfers balance', durable_event_contract: 'Durable event contract valid', event_delivery_lag: 'Event delivery within window' };
  return friendly[name] || name.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}

function renderFlow() {
  const chain = ['activity', 'api', 'postgres', 'outbox-relay', 'redis', 'event-worker'];
  $('system-flow').innerHTML = `<div class="flow-scroll"><div class="flow-chain">${chain.map((name, i) => {
    const c = components[name], s = componentState(name);
    return `${i ? '<svg class="icon flow-arrow" aria-hidden="true"><use href="#i-arrow"/></svg>' : ''}<button class="flow-node ${state.selectedNode === name ? 'selected' : ''}" data-component="${name}" aria-label="Inspect ${c.title}">${icon(c.icon)}<strong>${c.title}</strong><small>${c.subtitle}</small>${badge(s.status)}</button>`;
  }).join('')}</div><div class="verifier-branch"><button data-component="verifier">${icon('shield')}Independent verifier ${badge(verification().status)}</button><span>Reads PostgreSQL · worker receipts return to PostgreSQL</span></div></div>`;
  if (state.selectedNode) {
    const c = components[state.selectedNode], s = componentState(state.selectedNode);
    $('flow-explanation').textContent = `${c.description} Latest state: ${s.status}. ${s.reason || ''}${s.observed_at ? ` · Observed ${date(s.observed_at)}` : ''}`;
  }
}
function renderServices() {
  $('service-cards').innerHTML = Object.entries(components).map(([name, c]) => {
    const s = componentState(name);
    return `<article class="service-card"><div class="service-title"><h3>${escape(c.title)}</h3>${badge(s.status)}</div><p>${escape(s.reason || c.subtitle)}</p><span class="service-stamp">${s.observed_at ? `Observed ${escape(date(s.observed_at))}` : 'No fresh observation'}${s.last_success_at ? `<br>Last success ${escape(date(s.last_success_at))}` : ''}${s.last_failure_at ? `<br>Last failure ${escape(date(s.last_failure_at))}` : ''}</span></article>`;
  }).join('');
}

function renderFreshness() {
  const stale = !state.fresh || (state.data && age(state.data.observed_at) > 30);
  const ready = componentState('api');
  const label = state.paused ? 'Live paused' : stale && state.data ? 'Data stale' : ready.status === 'HEALTHY' ? 'Core ready' : ready.status === 'UNHEALTHY' ? 'Core unavailable' : 'Connecting';
  $('connection-status').textContent = label;
  $('connection-status').className = `badge ${state.paused || stale ? 'neutral' : kind(ready.status)}`;
  $('metrics-grid').classList.toggle('stale', Boolean(stale));
  $('footer-freshness').textContent = state.data ? `${state.paused ? 'Paused · ' : ''}Last snapshot ${date(state.data.observed_at)}` : 'No database snapshot available';
  const banner = state.dataError || (state.data && age(state.data.observed_at) > 30 ? 'Snapshot is stale. Refresh to observe the current state.' : '');
  $('data-banner').hidden = !banner;
  $('data-banner').textContent = banner ? `${banner}${state.data ? ` Last successful snapshot: ${date(state.data.observed_at)}. Values below are retained, not current evidence.` : ''}` : '';
}

async function refresh(manual = false) {
  if (state.refreshing) return;
  state.refreshing = true; $('refresh-data').disabled = true;
  try {
    const [data, health, signals] = await Promise.allSettled([request('/api/v1/dashboard'), request('/health/dependencies'), request('/api/v1/dashboard/signals')]);
    if (data.status === 'fulfilled') { state.data = data.value; state.fresh = true; state.dataError = ''; }
    else { state.fresh = false; state.dataError = `Dashboard data unavailable. ${errorText(data.reason)}`; }
    state.health = health.status === 'fulfilled' ? health.value : null;
    state.signals = signals.status === 'fulfilled' ? signals.value : null;
    renderMetrics(); renderVerification(); renderFlow(); renderServices(); renderFreshness();
    if (state.view === 'accounts' && (manual || state.accounts.length <= 25)) await loadAccounts();
    if (state.view === 'transfers' && (manual || state.transfers.length <= 25)) await loadTransfers();
  } finally { state.refreshing = false; $('refresh-data').disabled = false; }
}

function rememberAccounts(accounts) { for (const account of accounts) state.directory.set(account.id, account); }
async function loadAccounts(append = false) {
  const version = ++state.accountVersion, search = $('account-search').value;
  const params = new URLSearchParams({ limit: '25', search });
  if (append && state.accountCursor) params.set('cursor', state.accountCursor);
  $('more-accounts').disabled = true;
  try {
    const data = await request(`/api/v1/dashboard/accounts?${params}`);
    if (version !== state.accountVersion) return;
    state.accounts = append ? [...state.accounts, ...data.items] : data.items; state.accountCursor = data.next_cursor;
    rememberAccounts(data.items);
    $('accounts-table').querySelector('tbody').innerHTML = state.accounts.length ? state.accounts.map(a => `<tr><td><button class="table-link" data-account="${escape(a.id)}" title="${escape(a.external_ref)}">${escape(a.external_ref)}</button><span class="table-sub mono">${escape(short(a.id))}</span></td><td>${badge(a.status)}</td><td>${escape(a.currency)}</td><td class="number">${escape(money(a.balance_minor, a.currency))}</td><td>${escape(date(a.updated_at))}</td><td><button class="text-button" data-account="${escape(a.id)}" aria-label="Inspect ${escape(a.external_ref)}">${icon('arrow')}</button></td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">No matching accounts. Create a zero-balance account, or seed your lab to begin.</td></tr>';
    $('account-list-status').textContent = `${number(state.accounts.length)} records loaded · ${new Date().toLocaleTimeString()}${state.accounts.length > 25 ? ' · paginated view pinned until refresh' : ''}`;
    $('more-accounts').hidden = !data.next_cursor;
  } catch (error) { if (version === state.accountVersion) $('account-list-status').textContent = `Account refresh failed: ${errorText(error)}. Retained rows may be stale.`; }
  finally { if (version === state.accountVersion) $('more-accounts').disabled = false; }
}
async function loadTransfers(append = false) {
  const version = ++state.transferVersion, params = new URLSearchParams({ limit: '25' });
  if (append && state.transferCursor) params.set('cursor', state.transferCursor);
  $('more-transfers').disabled = true;
  try {
    const data = await request(`/api/v1/dashboard/transfers?${params}`);
    if (version !== state.transferVersion) return;
    state.transfers = append ? [...state.transfers, ...data.items] : data.items; state.transferCursor = data.next_cursor;
    $('transfers-table').querySelector('tbody').innerHTML = transferRows(state.transfers);
    $('transfer-list-status').textContent = `${number(state.transfers.length)} records loaded · ${new Date().toLocaleTimeString()}${state.transfers.length > 25 ? ' · paginated view pinned until refresh' : ''}`;
    $('more-transfers').hidden = !data.next_cursor;
  } catch (error) { if (version === state.transferVersion) $('transfer-list-status').textContent = `Transfer refresh failed: ${errorText(error)}. Retained rows may be stale.`; }
  finally { if (version === state.transferVersion) $('more-transfers').disabled = false; }
}

function view(name) {
  if (!['overview', 'accounts', 'transfers', 'system'].includes(name)) return;
  state.view = name;
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== `view-${name}`;
  for (const button of document.querySelectorAll('[data-view]')) { button.classList.toggle('active', button.dataset.view === name); if (button.dataset.view === name) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); }
  $('breadcrumb-view').textContent = name[0].toUpperCase() + name.slice(1);
  $('page-title').textContent = { overview: 'System overview', accounts: 'Synthetic accounts', transfers: 'Transfer journal', system: 'System & integrity' }[name];
  $('page-subtitle').textContent = { overview: 'Your synthetic transaction lab, in real time.', accounts: 'Explore balances and the immutable ledger behind them.', transfers: 'Follow each durable commit through asynchronous delivery.', system: 'Observe dependencies, freshness and independent correctness.' }[name];
  if (name === 'accounts') loadAccounts();
  if (name === 'transfers') loadTransfers();
}

function dialog(title, subtitle, body, footer = '') {
  const modal = $('modal');
  if (!modal.open) state.lastFocus = document.activeElement;
  modal.innerHTML = `<div class="dialog-header"><div><h2 id="dialog-title">${escape(title)}</h2><p>${escape(subtitle)}</p></div><button class="dialog-close" data-close aria-label="Close dialog">${icon('close')}</button></div>${body}${footer}`;
  if (!modal.open) modal.showModal();
}
function modalError(error) { return `<div class="dialog-body"><div class="form-error bad" role="alert">${escape(errorText(error))}</div></div>`; }
function closeDialog() { if (!state.transferBusy) $('modal').close(); }
function directoryOptions() { return [...state.directory.values()].map(a => `<option value="${escape(a.external_ref)}">${escape(a.id)}</option>`).join(''); }
async function directory() {
  if (state.directoryLoaded) return;
  let cursor = null;
  for (let page = 0; page < 10; page++) {
    const params = new URLSearchParams({ limit: '100' }); if (cursor) params.set('cursor', cursor);
    const data = await request(`/api/v1/dashboard/accounts?${params}`); rememberAccounts(data.items); cursor = data.next_cursor;
    if (!cursor) { state.directoryLoaded = true; break; }
  }
  if ($('account-options')) $('account-options').innerHTML = directoryOptions();
}
function accountId(value) {
  const match = [...state.directory.values()].find(a => a.external_ref === value);
  if (match) return match.id;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) return value;
  throw new Error('Choose an account reference from the list or paste a valid account UUID.');
}
function openTransfer() {
  state.modalMode = 'transfer'; state.dialogGeneration++; state.transferError = state.pending ? new Error('Result unconfirmed. Retry this exact transfer to confirm its outcome.') : null;
  renderTransferForm();
  directory().catch(() => { const help = $('account-selection-help'); if (help) help.textContent = 'Account directory unavailable. You can paste source and destination UUIDs.'; });
}
function renderTransferForm() {
  const payload = state.pending?.payload, locked = Boolean(state.pending), currency = payload?.currency || state.data?.currency || 'INR';
  const disabled = locked || state.transferBusy ? 'disabled' : '';
  dialog(locked && !state.transferBusy ? 'Confirm pending transfer' : 'New synthetic transfer', 'Balances and the double-entry ledger commit together.',
    `<form id="transfer-form"><div class="dialog-body form-grid">${state.transferError ? `<div class="form-error" role="alert">${escape(state.transferError.message)}${state.transferError.code ? `<br>${escape(errorText(state.transferError))}` : ''}</div>` : ''}<label for="source-account">Source account<input id="source-account" name="source" list="account-options" placeholder="Select reference or paste UUID" value="${escape(payload?.source_account_id || '')}" autocomplete="off" required ${disabled}></label><label for="destination-account">Destination account<input id="destination-account" name="destination" list="account-options" placeholder="Select reference or paste UUID" value="${escape(payload?.destination_account_id || '')}" autocomplete="off" required ${disabled}></label><datalist id="account-options">${directoryOptions()}</datalist><p class="form-help" id="account-selection-help">Select a reference, or use any account UUID. PostgreSQL checks available funds.</p><div class="form-row"><label for="transfer-amount">Amount in minor units<input id="transfer-amount" name="amount" inputmode="numeric" pattern="[0-9]+" maxlength="19" value="${escape(payload?.amount_minor || '100')}" required ${disabled}></label><label for="transfer-currency">Currency<input id="transfer-currency" value="${escape(currency)}" readonly></label></div><p class="form-help">100 minor units = ${escape(money('100', currency))}. All money is synthetic.${state.pending ? `<br>Operation key: <span class="mono">${escape(state.pending.key)}</span>` : ''}</p></div><div class="dialog-footer"><button type="button" class="button quiet" data-close ${state.transferBusy ? 'disabled' : ''}>Close</button><button type="submit" class="button primary" ${state.transferBusy ? 'disabled' : ''}>${state.transferBusy ? 'Committing…' : locked ? 'Retry same transfer' : 'Commit transfer'}</button></div></form>`);
  $('transfer-form').addEventListener('submit', submitTransfer);
  const input = $('source-account'); if (!locked && !state.transferBusy) input.focus();
}
async function submitTransfer(event) {
  event.preventDefault(); if (state.transferBusy) return;
  try {
    if (!state.pending) {
      const payload = { source_account_id: accountId($('source-account').value.trim()), destination_account_id: accountId($('destination-account').value.trim()), amount_minor: minorAmount($('transfer-amount').value), currency: $('transfer-currency').value };
      if (payload.source_account_id.toLowerCase() === payload.destination_account_id.toLowerCase()) throw new Error('Source and destination must be different accounts.');
      const intent = { key: `ui-${uuid()}`, payload };
      saveIntent(intent); state.pending = intent;
    }
    saveIntent(state.pending);
    state.transferBusy = true; state.transferError = null; updateAction(); renderTransferForm();
    const result = await commitIntent(state.pending);
    state.pending = null; clearIntent(); state.transferBusy = false; updateAction(); state.modalMode = 'receipt';
    dialog(result.replayed ? 'Transfer confirmed' : 'Transfer committed', 'The PostgreSQL commit is durable; event delivery follows asynchronously.', `<div class="dialog-body receipt"><span class="receipt-icon">${icon('check')}</span><h3>${result.replayed ? 'Transfer confirmed' : 'Transfer committed'}</h3><p>${result.replayed ? 'The original transfer was returned. No second debit was created.' : 'The source debit and destination credit were committed atomically.'}</p><p class="mono">${escape(result.transfer.id)}</p><p>Request ID: <span class="mono">${escape(result.transfer.request_id)}</span></p></div>`, `<div class="dialog-footer"><button class="button quiet" data-close>Close</button><button class="button primary" data-transfer="${escape(result.transfer.id)}">View transfer</button></div>`);
    refresh(true);
  } catch (error) {
    state.transferBusy = false;
    const definite = error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status);
    if (definite) { state.pending = null; clearIntent(); }
    state.transferError = state.pending ? new ApiError(`Result unconfirmed. ${error.message} Retry this exact transfer with the original key.`, error.status, error.code, error.requestId) : error;
    updateAction(); renderTransferForm();
  }
}

function openCreateAccount() {
  state.modalMode = 'create-account'; const generation = ++state.dialogGeneration;
  dialog('Create synthetic account', 'New accounts start with zero balance. Provisioning is a separate lab seed operation.', `<form id="account-form"><div class="dialog-body form-grid"><div id="account-error" class="form-error bad" role="alert" hidden></div><label for="external-ref">External reference<input id="external-ref" maxlength="128" pattern="[A-Za-z0-9_.:\\-]+" placeholder="e.g. lab-account-001" required></label><label for="account-currency">Currency<input id="account-currency" value="${escape(state.data?.currency || 'INR')}" readonly></label><p class="form-help">Letters, numbers, underscores, periods, colons and hyphens.</p></div><div class="dialog-footer"><button type="button" class="button quiet" data-close>Cancel</button><button class="button primary" type="submit">Create account</button></div></form>`);
  $('external-ref').focus();
  $('account-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      await request('/api/v1/accounts', { method: 'POST', body: JSON.stringify({ external_ref: $('external-ref').value, currency: $('account-currency').value }) });
      state.directoryLoaded = false; if (generation === state.dialogGeneration && $('modal').open) closeDialog(); toast('Created a zero-balance synthetic account.'); refresh(true);
    } catch (error) { if (generation === state.dialogGeneration && $('account-error')) { $('account-error').textContent = errorText(error); $('account-error').hidden = false; } }
    finally { button.disabled = false; }
  });
}

function ledgerCards(entries) {
  if (!entries.length) return '<p class="form-help">No ledger entries yet. This account has not been provisioned or transferred.</p>';
  return entries.map(e => `<div class="ledger-card"><div><strong>${escape(e.entry_kind)}</strong><small>${escape(e.account_ref || date(e.created_at))}</small>${e.transfer_id ? `<small class="mono">Transfer ${escape(short(e.transfer_id))}</small>` : ''}</div><span class="ledger-amount ${BigInt(e.signed_amount_minor) < 0n ? 'debit' : ''}">${escape(money(e.signed_amount_minor, e.currency))}<small>${escape(e.signed_amount_minor)} minor units</small></span></div>`).join('');
}
async function openAccount(id) {
  state.modalMode = 'account'; const generation = ++state.dialogGeneration;
  dialog('Account ledger', 'Loading authoritative account details…', '<div class="dialog-body"><p>Fetching account and ledger history.</p></div>');
  try {
    const [account, ledger] = await Promise.all([request(`/api/v1/dashboard/accounts/${id}`), request(`/api/v1/dashboard/accounts/${id}/ledger?limit=25`)]);
    if (generation !== state.dialogGeneration || !$('modal').open) return;
    dialog(account.external_ref, 'Authoritative account metadata and immutable ledger history.', `<div class="dialog-body"><dl class="detail-meta"><div><dt>Balance</dt><dd class="detail-amount">${escape(money(account.balance_minor, account.currency))}</dd></div><div><dt>Status</dt><dd>${badge(account.status)}</dd></div><div class="wide"><dt>Account ID</dt><dd class="mono">${escape(id)}</dd></div><div class="wide"><dt>Balance source updated</dt><dd>${escape(date(account.updated_at))}</dd></div></dl><h3 class="detail-section-title">Ledger entries</h3><div id="account-ledger">${ledgerCards(ledger.items)}</div><button id="more-ledger" class="button quiet" ${ledger.next_cursor ? '' : 'hidden'}>Load more ledger entries</button><p id="ledger-error" class="form-help" role="status"></p></div>`, '<div class="dialog-footer"><button class="button quiet" data-close>Close</button></div>');
    let cursor = ledger.next_cursor;
    $('more-ledger').addEventListener('click', async () => {
      const button = $('more-ledger'); button.disabled = true;
      try {
        const page = await request(`/api/v1/dashboard/accounts/${id}/ledger?limit=25&cursor=${encodeURIComponent(cursor)}`);
        if (generation !== state.dialogGeneration || !$('modal').open) return;
        $('account-ledger').insertAdjacentHTML('beforeend', ledgerCards(page.items)); cursor = page.next_cursor; button.hidden = !cursor;
      } catch (error) { if ($('ledger-error')) $('ledger-error').textContent = errorText(error); }
      finally { button.disabled = false; }
    });
  } catch (error) { if (generation === state.dialogGeneration && $('modal').open) dialog('Account unavailable', 'The read could not be completed.', modalError(error)); }
}
async function openTransferDetails(id) {
  state.modalMode = 'transfer-detail'; const generation = ++state.dialogGeneration;
  dialog('Transfer details', 'Loading the committed transfer and its ledger pair…', '<div class="dialog-body"><p>Fetching durable evidence.</p></div>');
  try {
    const data = await request(`/api/v1/dashboard/transfers/${id}`);
    if (generation !== state.dialogGeneration || !$('modal').open) return;
    const t = data.transfer;
    dialog('Transfer details', 'A committed transfer remains valid while event processing catches up.', `<div class="dialog-body"><dl class="detail-meta"><div><dt>Amount</dt><dd class="detail-amount">${escape(money(t.amount_minor, t.currency))}</dd></div><div><dt>Event delivery</dt><dd>${badge(t.event_status, { PROCESSED: 'Delivered', PENDING_PUBLICATION: 'Queued', PENDING_PROCESSING: 'Published' }[t.event_status])}</dd></div><div><dt>Source</dt><dd>${escape(t.source_ref)}</dd></div><div><dt>Destination</dt><dd>${escape(t.destination_ref)}</dd></div><div class="wide"><dt>Transfer ID</dt><dd class="mono">${escape(t.id)}</dd></div><div><dt>Committed</dt><dd>${escape(date(t.committed_at))}</dd></div><div><dt>Request ID</dt><dd class="mono">${escape(t.request_id || 'Not recorded')}</dd></div><div class="wide"><dt>Event ID</dt><dd class="mono">${escape(t.event_id || 'Not recorded')}</dd></div>${data.traceparent ? `<div class="wide"><dt>W3C trace context</dt><dd class="mono">${escape(data.traceparent)}</dd></div>` : ''}</dl><h3 class="detail-section-title">Immutable double-entry ledger</h3>${ledgerCards(data.ledger)}</div>`, '<div class="dialog-footer"><button class="button quiet" data-close>Close</button></div>');
  } catch (error) { if (generation === state.dialogGeneration && $('modal').open) dialog('Transfer unavailable', 'The read could not be completed.', modalError(error)); }
}

document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.view) view(button.dataset.view);
  if (button.dataset.go) view(button.dataset.go);
  if (button.dataset.component) { state.selectedNode = button.dataset.component; renderFlow(); }
  if (button.hasAttribute('data-close')) closeDialog();
  if (button.dataset.account) openAccount(button.dataset.account);
  if (button.dataset.transfer) openTransferDetails(button.dataset.transfer);
});
$('new-transfer').addEventListener('click', openTransfer);
$('create-account').addEventListener('click', openCreateAccount);
$('refresh-data').addEventListener('click', () => refresh(true));
$('pause-refresh').addEventListener('click', () => { state.paused = !state.paused; $('pause-refresh').textContent = state.paused ? 'Resume live' : 'Pause live'; renderFreshness(); if (!state.paused) refresh(true); });
$('more-accounts').addEventListener('click', () => loadAccounts(true));
$('more-transfers').addEventListener('click', () => loadTransfers(true));
let searchTimer;
$('account-search').addEventListener('input', () => { state.accountVersion++; clearTimeout(searchTimer); searchTimer = setTimeout(() => loadAccounts(), 250); });
$('modal').addEventListener('cancel', event => { if (state.transferBusy) event.preventDefault(); });
$('modal').addEventListener('close', () => { state.dialogGeneration++; state.modalMode = ''; state.lastFocus?.focus(); });
for (const [id, port] of [['grafana-link', '3000'], ['prometheus-link', '9090']]) { const url = new URL(location.href); url.port = port; url.pathname = '/'; url.search = ''; url.hash = ''; $(id).href = url.href; }
updateAction(); renderServices(); renderFlow(); refresh();
setInterval(() => { if (!state.paused && !document.hidden) refresh(); }, 10000);
setInterval(() => { renderFreshness(); renderVerification(); renderServices(); renderFlow(); }, 5000);
