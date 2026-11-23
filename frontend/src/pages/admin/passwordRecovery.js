const verifierKey = 'docent.admin.recovery.verifier';

export function recoveryCallback({ search, hash }) {
  const query = new URLSearchParams(search);
  const fragment = new URLSearchParams(hash.slice(1));
  const error = [query, fragment].some((params) => params.has('error') || params.has('error_code'));
  if (error) return { kind: 'invalid' };
  const type = fragment.get('type') ?? query.get('type');
  const token = fragment.get('access_token');
  const tokenHash = query.get('token_hash');
  const code = query.get('code');
  if (type === 'recovery' && token) return { kind: 'token', value: token };
  if (type === 'recovery' && tokenHash) return { kind: 'hash', value: tokenHash };
  if (code && (!type || type === 'recovery')) return { kind: 'code', value: code };
  return { kind: type === 'recovery' ? 'invalid' : 'none' };
}

export function readVerifier() {
  try {
    return localStorage.getItem(verifierKey);
  } catch {
    return null;
  }
}

export function clearVerifier(value) {
  try {
    if (localStorage.getItem(verifierKey) === value) localStorage.removeItem(verifierKey);
  } catch {
    // Storage can be disabled in private browsing.
  }
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

export async function prepareRecovery() {
  try {
    const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    localStorage.setItem(verifierKey, verifier);
    return { verifier, challenge: base64url(new Uint8Array(digest)) };
  } catch {
    // On origins without Web Crypto or storage, Supabase returns a fragment token.
    return {};
  }
}
