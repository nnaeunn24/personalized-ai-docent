const apiUrl = (import.meta.env.VITE_VISITOR_API_URL || import.meta.env.VITE_ADMIN_API_URL || 'http://127.0.0.1:8000')
  .trim().replace(/\/+$/, '');

export function visitorUrl(exhibitionId, artworkId, step, view) {
  const params = new URLSearchParams();
  if (exhibitionId) params.set('exhibition', exhibitionId);
  if (artworkId) params.set('artwork', artworkId);
  if (step) params.set('step', step);
  if (view) params.set('view', view);
  const query = params.toString();
  return '/visitor' + (query ? '?' + query : '');
}

export async function askArtworkQuestion(exhibitionId, artworkId, question, history, signal) {
  const path = '/exhibitions/' + encodeURIComponent(exhibitionId) + '/artworks/' + encodeURIComponent(artworkId);
  const response = await fetch(apiUrl + '/api/visitor' + path + '/questions', {
    method: 'POST', credentials: 'omit', cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(60000)]),
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ question, history }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : '답변을 불러오지 못했어요.');
  }
  return response.json();
}

export async function generateDocent(exhibitionId, artworkId, profile, signal) {
  const path = '/exhibitions/' + encodeURIComponent(exhibitionId) + '/artworks/' + encodeURIComponent(artworkId);
  const response = await fetch(apiUrl + '/api/visitor' + path + '/docent', {
    method: 'POST', credentials: 'omit', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(profile),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : '도슨트 설명을 생성하지 못했습니다.');
  }
  return response.json();
}

export async function readVisitorCatalog(exhibitionId, artworkId, signal) {
  let path = '/exhibitions';
  if (exhibitionId) path += '/' + encodeURIComponent(exhibitionId);
  if (exhibitionId && artworkId) path += '/artworks/' + encodeURIComponent(artworkId);
  const response = await fetch(apiUrl + '/api/visitor' + path, {
    headers: { Accept: 'application/json' }, signal, cache: 'no-store', credentials: 'omit',
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('Unable to load the public catalog.');
  return response.json();
}
