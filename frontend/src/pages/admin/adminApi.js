const apiUrl = import.meta.env.VITE_ADMIN_API_URL?.trim().replace(/\/+$/, '');
const prefix = '/api/admin';

export class AdminApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'AdminApiError';
    this.status = status;
  }
}

async function request(path, { token, method = 'GET', body, signal } = {}) {
  if (!apiUrl) throw new AdminApiError(0, 'VITE_ADMIN_API_URL을 설정하세요.');
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const isFile = body instanceof Blob;
  if (body !== undefined) headers['Content-Type'] = isFile ? body.type : 'application/json';

  let response;
  try {
    response = await fetch(apiUrl + prefix + path, {
      method, headers, signal, cache: 'no-store',
      body: body === undefined || isFile ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new AdminApiError(0, '관리자 API에 연결할 수 없습니다.');
  }
  if (response.status === 204) return;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = Array.isArray(data?.detail)
      ? data.detail.map(({ loc, msg }) => loc.slice(1).join('.') + ' ' + msg).join(', ')
      : data?.detail;
    throw new AdminApiError(response.status, detail || '관리자 API 요청을 완료하지 못했습니다.');
  }
  if (data === null) throw new AdminApiError(response.status, '관리자 API 응답을 읽을 수 없습니다.');
  return data;
}

const unitStatuses = { pending: '검수 대기', reviewed: '검수 완료', published: '게시됨' };
const unitStatusCodes = { '검수 대기': 'pending', '검수 완료': 'reviewed', '게시됨': 'published' };
const dateLabel = (timestamp) => new Date(timestamp).toLocaleDateString('ko-KR');
const exhibition = (row) => ({
  id: row.id, name: row.name, description: row.description, code: row.code,
  isPublic: row.is_public, coverObjectKey: row.cover_object_key, imageUrl: row.image_url, updated: dateLabel(row.updated_at),
  artworkOrder: row.artwork_order ?? [],
});
const artwork = (row) => ({
  id: row.id, exhibitionId: row.exhibition_id, name: row.name, artist: row.artist,
  externalId: row.external_id, description: row.description, source: row.source_url,
  language: row.language, year: row.year, imageObjectKey: row.image_object_key, imageUrl: row.image_url,
  createdAt: row.created_at, updated: dateLabel(row.updated_at),
});
const unit = (row) => ({
  id: row.id, artworkId: row.artwork_id, label: 'UNIT-' + String(row.number).padStart(3, '0'),
  content: row.content, category: row.category, status: unitStatuses[row.status], updatedAt: row.updated_at,
  extractionMethod: row.extraction_method, extractionModel: row.extraction_model,
  sourceEvidence: row.source_evidence ?? [], classificationRationale: row.classification_rationale,
  needsSplit: row.needs_split, needsReview: row.needs_review,
  classificationMethod: row.classification_method, classificationModel: row.classification_model,
});
const idPath = (id) => encodeURIComponent(id);

function save(path, token, values, id, map) {
  const method = id ? 'PUT' : 'POST';
  return request(id ? path + '/' + idPath(id) : path, { token, method, body: values }).then(map);
}

async function list(path, token, map, filters = {}, signal) {
  const entries = [];
  const limit = 50;
  for (let offset = 0; ; offset += limit) {
    const query = new URLSearchParams({ ...filters, limit, offset });
    const rows = await request(path + '?' + query, { token, signal });
    entries.push(...rows.map(map));
    if (rows.length < limit) return entries;
  }
}

export const adminApi = {
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  refresh: (refreshToken) => request('/auth/refresh', { method: 'POST', body: { refresh_token: refreshToken } }),
  logout: (token) => request('/auth/logout', { token, method: 'POST' }),
  me: (token) => request('/me', { token }),
  recoverPassword: (email, challenge) =>
    request('/auth/recover', { method: 'POST', body: { email, code_challenge: challenge } }),
  verifyRecoveryHash: (tokenHash) =>
    request('/auth/recover/verify', { method: 'POST', body: { token_hash: tokenHash } }),
  exchangeRecoveryCode: (code, verifier) =>
    request('/auth/recover/exchange', { method: 'POST', body: { code, verifier } }),
  resetPassword: (token, password) =>
    request('/auth/password', { token, method: 'PUT', body: { password } }),

  activeAiPrompts: (token, signal) => request('/ai/prompts', { token, signal }),
  aiPromptVersions: (token, kind, signal) =>
    list('/ai/prompts/' + idPath(kind) + '/versions', token, (row) => row, {}, signal),
  updateAiPrompt: (token, kind, body) =>
    request('/ai/prompts/' + idPath(kind), { token, method: 'PUT', body }),
  aiTests: (token, signal) => list('/ai/tests', token, (row) => row, {}, signal),
  runAiTest: (token, body) => request('/ai/tests', { token, method: 'POST', body }),
  runFollowupTest: (token, body) => request('/ai/followup-tests', { token, method: 'POST', body }),

  listFollowupOverview: (token, signal) => list('/followups', token, (row) => row, {}, signal),
  getFollowups: (token, artworkId, signal) => request('/artworks/' + idPath(artworkId) + '/followups', { token, signal }),
  generateFollowups: (token, artworkId, body) =>
    request('/artworks/' + idPath(artworkId) + '/followups/generate', { token, method: 'POST', body }),
  reviewFollowups: (token, artworkId, status, questions) =>
    request('/artworks/' + idPath(artworkId) + '/followups/review', {
      token, method: 'POST', body: { status, items: Object.fromEntries(questions.map(({ id, updated_at }) => [id, updated_at])) },
    }),
  saveFollowup: (token, artworkId, id, body) =>
    request('/artworks/' + idPath(artworkId) + '/followups/' + idPath(id), { token, method: 'PUT', body }),
  deleteFollowup: (token, artworkId, question) =>
    request('/artworks/' + idPath(artworkId) + '/followups/' + idPath(question.id) +
      '?' + new URLSearchParams({ updated_at: question.updated_at }), { token, method: 'DELETE' }),

  listExhibitions: (token, signal) => list('/exhibitions', token, exhibition, {}, signal),
  uploadCatalogImage: (token, file) => request('/catalog-images', { token, method: 'POST', body: file }),
  saveExhibition: (token, { id, name, description = '', imageKey }) =>
    save('/exhibitions', token, { name, description, cover_object_key: imageKey }, id, exhibition),
  setExhibitionVisibility: (token, id, isPublic) =>
    request('/exhibitions/' + idPath(id) + '/visibility', {
      token, method: 'PATCH', body: { is_public: isPublic },
    }).then(exhibition),
  deleteExhibition: (token, id) => request('/exhibitions/' + idPath(id), { token, method: 'DELETE' }),
  saveArtworkOrder: (token, id, expectedIds, artworkIds) =>
    request('/exhibitions/' + idPath(id) + '/artwork-order', {
      token, method: 'PUT', body: { expected_ids: expectedIds, artwork_ids: artworkIds },
    }),

  listArtworks: (token, exhibitionId, signal) =>
    list('/artworks', token, artwork, exhibitionId ? { exhibition_id: exhibitionId } : {}, signal),
  saveArtwork: (token, values) => save('/artworks', token, {
    exhibition_id: values.exhibitionId, name: values.name, artist: values.artist ?? '',
    external_id: values.externalId, description: values.description ?? '',
    source_url: values.source, language: values.language ?? '', year: values.year ?? '', image_object_key: values.imageKey,
  }, values.id, artwork),
  deleteArtwork: (token, id) => request('/artworks/' + idPath(id), { token, method: 'DELETE' }),

  extractUnits: (token, id) => request('/artworks/' + idPath(id) + '/units/extract', { token, method: 'POST' }),
  listUnits: (token, { artworkId, status, signal } = {}) =>
    list(artworkId ? '/artworks/' + idPath(artworkId) + '/units' : '/units', token, unit,
      status ? { status: unitStatusCodes[status] ?? status } : {}, signal),
  saveUnit: (token, { id, artworkId, content, category }) =>
    save(id ? '/units' : '/artworks/' + idPath(artworkId) + '/units', token, { content, category }, id, unit),
  reviewUnit: (token, { id, updatedAt }) => request('/units/' + idPath(id) + '/review', {
    token, method: 'POST', body: { updated_at: updatedAt },
  }).then(unit),
  publishUnits: (token, artworkId) =>
    request('/artworks/' + idPath(artworkId) + '/units/publish', { token, method: 'POST' })
      .then(({ units }) => units.map(unit)),
  deleteUnit: (token, id) => request('/units/' + idPath(id), { token, method: 'DELETE' }),
};
