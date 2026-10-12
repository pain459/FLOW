export class ApiError extends Error {
  constructor(message, status = 0, code = 'CONNECTION_INTERRUPTED', requestId = '') {
    super(message); this.status = status; this.code = code; this.requestId = requestId;
  }
}

export function uuid() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function request(path, { method = 'GET', body, signal } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch(path, { method, body, cache: 'no-store', signal: controller.signal,
      headers: { 'Accept': 'application/json', 'X-PulsePay-Client': 'dashboard', 'X-Request-ID': `ui-${uuid()}`, ...(body ? { 'Content-Type': 'application/json' } : {}) } });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.message || `Request failed (${response.status})`, response.status, data.code, data.request_id);
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('Connection interrupted or request timed out.');
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort);
  }
}

export function minorAmount(value) {
  if (!/^[0-9]{1,19}$/.test(String(value))) throw new Error('Enter a whole number of minor units.');
  const amount = BigInt(value);
  if (amount < 1n || amount > 9223372036854775807n) throw new Error('Amount must be between 1 and 9,223,372,036,854,775,807 minor units.');
  return amount.toString();
}

export function money(value, currency = 'INR') {
  if (value === undefined || value === null) return '—';
  const signed = BigInt(value), amount = signed < 0n ? -signed : signed;
  return `${currency} ${signed < 0n ? '−' : ''}${new Intl.NumberFormat('en-IN').format(amount / 100n)}.${String(amount % 100n).padStart(2, '0')}`;
}

export function transferBody(payload) {
  const amount = minorAmount(payload.amount_minor);
  // Encode a validated integer token, preserving BIGINT digits without Number conversion.
  return JSON.stringify({ source_account_id: payload.source_account_id,
    destination_account_id: payload.destination_account_id, amount_minor: null, currency: payload.currency })
    .replace('"amount_minor":null', `"amount_minor":${amount}`);
}

const STORAGE_KEY = 'pulsepay.pending-transfer.v1';
export function loadIntent() {
  try {
    const intent = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    if (!intent) return null;
    if (!/^ui-[a-f0-9-]{36}$/.test(intent.key) || !/^[A-Z]{3}$/.test(intent.payload.currency)) return null;
    minorAmount(intent.payload.amount_minor);
    return intent;
  } catch { return null; }
}
export function saveIntent(intent) {
  try {
    const encoded = JSON.stringify(intent);
    sessionStorage.setItem(STORAGE_KEY, encoded);
    if (sessionStorage.getItem(STORAGE_KEY) !== encoded) throw new Error('Persistence failed');
  } catch { throw new Error('Browser storage is unavailable. No transfer was sent. Enable session storage and retry.'); }
}
export function clearIntent() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* Storage may be disabled. */ }
}
export async function commitIntent(intent) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/api/v1/transfers', { method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-PulsePay-Client': 'dashboard', 'Idempotency-Key': intent.key, 'X-Request-ID': intent.key }, body: transferBody(intent.payload) });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.message || 'Transfer failed', response.status, data.code, data.request_id);
    return { transfer: data, replayed: response.status === 200 };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('Connection interrupted or request timed out.');
  } finally { clearTimeout(timer); }
}
