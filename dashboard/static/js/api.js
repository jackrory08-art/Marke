// Fetch wrapper: sends the CSRF token on unsafe methods, and returns to the
// login page when the session has ended.
let csrfToken = null;

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function goToLogin() {
  window.location.href = '/login';
}

export async function init() {
  const me = await request('GET', '/api/auth/me');
  csrfToken = me.csrf_token;
  return me;
}

export async function request(method, url, body) {
  const headers = { Accept: 'application/json' };
  const opts = { method, headers, credentials: 'same-origin' };
  if (method !== 'GET' && method !== 'HEAD') {
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw new ApiError(0, 'Could not reach the server.');
  }
  if (res.status === 401) {
    goToLogin();
    throw new ApiError(401, 'Signed out');
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
    } catch (e) { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const get = (url) => request('GET', url);
export const post = (url, body) => request('POST', url, body);
export const patch = (url, body) => request('PATCH', url, body);
export const del = (url) => request('DELETE', url);
