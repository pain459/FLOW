import {el, request} from './common.js';
import {callsWorkspace} from './calls.js';
import {historyWorkspace} from './workspace.js';

let authenticated = false, modelBusy = false, activeView = 'calls', refreshing = false;
const openAuth = () => { el('auth-notice').textContent = ''; el('auth-dialog').showModal(); el('token').focus(); };
const access = {authorized: () => authenticated, openAuth, busy: () => modelBusy, changed: () => refreshHealth()};
const calls = callsWorkspace(access);
const history = historyWorkspace({...access, selectView});

function selectView(view) {
  activeView = view;
  for (const tab of document.querySelectorAll('[role=tab]')) tab.setAttribute('aria-selected', String(tab.dataset.view === view));
  for (const item of ['calls', 'history', 'replays']) el(item + '-view').hidden = item !== view;
  if (view === 'history') history.refresh();
  if (view === 'replays') history.replays();
}
for (const tab of document.querySelectorAll('[role=tab]')) tab.onclick = () => selectView(tab.dataset.view);

async function refreshHealth() {
  try {
    const health = await request('/health');
    modelBusy = health.analysis_busy;
    el('health').textContent = `Services ${health.status} · Laya ${health.model.status}${modelBusy ? ' · Busy' : ''}`;
    el('health').className = 'badge ' + (health.status === 'HEALTHY' ? 'good' : 'warn');
  } catch (e) {
    el('health').textContent = 'Investigation services UNKNOWN';
    el('health').className = 'badge neutral';
    modelBusy = true;
  }
  try {
    authenticated = (await request('/auth/session')).authorized;
    el('authorize').textContent = authenticated ? 'Sign out' : 'Sign in';
  } catch { authenticated = false; }
  calls.controls();
}
el('authorize').onclick = async () => {
  if (!authenticated) return openAuth();
  try { await request('/auth/logout', {method: 'POST'}); authenticated = false; await refreshHealth(); }
  catch (e) { el('ask-notice').textContent = e.message; }
};
el('close-auth').onclick = () => { el('token').value = ''; el('auth-dialog').close(); };
el('auth-dialog').addEventListener('close', () => { el('token').value = ''; });
el('auth-form').onsubmit = async e => {
  e.preventDefault(); el('sign-in').disabled = true;
  try {
    await request('/auth/session', {method: 'POST', body: {token: el('token').value}});
    el('token').value = ''; authenticated = true; el('auth-dialog').close();
    el('ask-notice').textContent = 'Authorized. Select a call and explicitly request analysis.';
    await refreshHealth();
  } catch (error) { el('auth-notice').textContent = error.message; }
  finally { el('sign-in').disabled = false; }
};

// This timer only reads health and existing requested-session results.
// It never starts an analysis, replay or diagnostic operation.
async function poll() {
  if (refreshing) return;
  refreshing = true;
  try { await refreshHealth(); await calls.poll(); await history.poll(); }
  catch (e) { el('ask-notice').textContent = `Status unavailable · ${e.message}`; }
  finally { refreshing = false; }
}
refreshHealth();
calls.refresh();
setInterval(() => { if (!document.hidden) poll(); }, 5000);
