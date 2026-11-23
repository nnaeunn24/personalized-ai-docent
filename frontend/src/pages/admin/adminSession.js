import { adminApi, AdminApiError } from './adminApi';

const storageKey = 'docent.admin.session';

export function createAdminSession() {
  let session = null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (saved?.access_token && saved?.refresh_token && saved.user && Number.isFinite(saved.expiresAt)) session = saved;
  } catch {
    // The session can still be used in memory when browser storage is unavailable.
  }
  let refresh = null;

  function store(value) {
    session = value;
    try {
      if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
      else sessionStorage.removeItem(storageKey);
    } catch {
      // Keep the current tab usable without persistent browser storage.
    }
  }

  function setSession(value) {
    store({ ...value, expiresAt: Date.now() + value.expires_in * 1000 });
    return session;
  }

  function renew(previous) {
    if (session && session !== previous) return session;
    if (!refresh) {
      refresh = adminApi.refresh(previous.refresh_token).then((value) => {
        if (session !== previous) throw new AdminApiError(401, '세션이 종료되었습니다.');
        return setSession(value);
      }).finally(() => { refresh = null; });
    }
    return refresh;
  }

  async function call(action, ...args) {
    if (!session) throw new AdminApiError(401, '로그인이 필요합니다.');
    const active = session.expiresAt - Date.now() < 15_000 ? await renew(session) : session;
    try {
      return await adminApi[action](active.access_token, ...args);
    } catch (error) {
      if (error.status !== 401) throw error;
      const renewed = await renew(active);
      return adminApi[action](renewed.access_token, ...args);
    }
  }

  return {
    get user() { return session?.user; },
    async login(email, password) { return setSession(await adminApi.login(email, password)).user; },
    clear() { store(null); },
    call,
  };
}
