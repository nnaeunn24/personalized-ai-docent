import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { createAdminSession } from './admin/adminSession';
import AiSettings from './admin/AiSettings';
import FollowupQuestions from './admin/FollowupQuestions';
import { visitorUrl } from './visitor/visitorApi';
import './admin/admin.css';

const screens = {
  dashboard: ['Dashboard', '대시보드'],
  exhibitions: ['Exhibitions', '전시 관리'],
  ai: ['AI Settings', 'AI Settings'],
};

const categoryLabels = {
  VISUAL: '시각적 특징',
  MEANING: '의미와 해석',
  TECHNIQUE: '재료와 제작 기법',
  BACKGROUND: '작가와 시대적 배경',
};
const categories = Object.keys(categoryLabels);
const statuses = ['검수 대기', '검수 완료', '게시됨'];
const adminUrl = (view, params = {}) => '?' + new URLSearchParams({ view, ...params });
const updated = () => new Date().toLocaleDateString('ko-KR');

function Button({ children, tone = 'primary', to, type = 'button', className: extraClass = '', ...props }) {
  const className = ['admin-button', tone, extraClass].filter(Boolean).join(' ');
  return to ? <Link to={to} className={className} {...props}>{children}</Link>
    : <button type={type} className={className} {...props}>{children}</button>;
}

function Field({ label, children }) {
  return <label className="admin-field"><span>{label}</span>{children}</label>;
}

function Notice({ children, error = false }) {
  return <p className={error ? 'admin-notice error' : 'admin-notice'} role={error ? 'status' : undefined}>{children}</p>;
}

function Empty({ title, children }) {
  return <div className="admin-empty"><h2>{title}</h2><p>{children}</p></div>;
}

function Modal({ title, children, onClose, compact = false }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  return <dialog className={compact ? "admin-dialog admin-dialog-compact" : "admin-dialog"} ref={dialog} aria-labelledby="admin-dialog-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <h1 id="admin-dialog-title">{title}</h1>{children}
  </dialog>;
}

function Brand() {
  return <div className="admin-brand"><strong>docent.</strong><small>Admin</small></div>;
}

function Login({ onLogin, error, busy }) {
  const { state } = useLocation();
  return <main className="admin admin-login">
    <div className="admin-login-card">
      <form onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onLogin(data.get('email'), data.get('password'));
      }}>
        <Brand />
        <h1>관리자 로그인</h1>
        <p className="admin-blue">등록된 관리자 계정으로 로그인하세요.</p>
        <Field label="이메일"><input name="email" type="email" placeholder="관리자 이메일 입력" autoComplete="username" required /></Field>
        <Field label="비밀번호"><input name="password" type="password" placeholder="비밀번호 입력" autoComplete="current-password" required /></Field>
        {error && <Notice error>{error}</Notice>}
        {state?.passwordReset && !error && <Notice>비밀번호를 변경했습니다. 새 비밀번호로 로그인하세요.</Notice>}
        <Button type="submit" disabled={busy}>{busy ? '로그인 중…' : '로그인'}</Button>
        {!busy && <Link className="admin-recovery-link" to="/admin/reset-password">비밀번호 찾기</Link>}
      </form>
      {busy ? <Button tone="ghost" disabled>관리자 화면 미리보기</Button>
        : <Button tone="ghost" to="/admin/preview?view=dashboard">관리자 화면 미리보기</Button>}
    </div>
  </main>;
}

const catalogImageTypes = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' };

function ImagePicker({ value, onChange, cover = false, imageUrl, busy = false, status }) {
  const [error, setError] = useState('');
  const id = cover ? 'exhibition-image' : 'artwork-image';
  function pick(file) {
    if (!file || busy) return;
    const extension = file.name.split('.').at(-1).toLowerCase();
    const mime = Object.hasOwn(catalogImageTypes, extension) ? catalogImageTypes[extension] : undefined;
    if (!mime || (file.type && file.type !== 'application/octet-stream' && file.type !== mime)) {
      setError('JPG, JPEG, PNG 또는 WEBP 이미지를 선택하세요.');
      return;
    }
    if (!file.size) {
      setError('빈 이미지 파일은 업로드할 수 없습니다.');
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError('8MB 이하의 이미지를 선택하세요.');
      return;
    }
    setError('');
    onChange(file.type === mime ? file : file.slice(0, file.size, mime));
  }
  return <div className="admin-upload">
    {(value || imageUrl || !cover) && <RecordImage record={{ image: value, imageUrl }}
      className={cover ? 'admin-cover-preview' : 'admin-artwork-preview'} />}
    <input className="admin-file" id={id} type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" disabled={busy}
      onChange={(event) => { pick(event.target.files[0]); event.target.value = ''; }} />
    <label className={'admin-button secondary' + (cover ? ' admin-drop' : '')} htmlFor={id} aria-disabled={busy || undefined}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => { event.preventDefault(); pick(event.dataTransfer.files[0]); }}>
      {value || imageUrl ? '이미지 변경' : cover ? '대표 이미지 업로드' : '이미지 업로드'}
      {cover && <small>JPG · JPEG · PNG · WEBP / 클릭하거나 파일을 끌어놓으세요</small>}
    </label>
    {!cover && <small>JPG · JPEG · PNG · WEBP / 원본 비율 유지</small>}
    {value && <p role="status" className="admin-muted">{status || '미리보기 · 저장하면 이미지가 업로드됩니다.'}</p>}
    {value && <Button tone="ghost" disabled={busy} onClick={() => onChange(null)}>{imageUrl ? '이미지 변경 취소' : '선택한 이미지 제거'}</Button>}
    {error && <Notice error>{error}</Notice>}
  </div>;
}

function ExhibitionForm({ record, onSave, onClose, busy, error, imageStatus }) {
  const [image, setImage] = useState(record?.image ?? null);
  return <Modal title={record ? '전시 정보 수정' : '신규 전시 등록'} onClose={onClose}>
    <form className="admin-stack" onSubmit={(event) => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(event.currentTarget));
      if (fields.name.trim()) onSave({ ...fields, name: fields.name.trim(), image });
    }}>
      <Field label="전시명"><input name="name" defaultValue={record?.name} placeholder="전시명을 입력하세요" required /></Field>
      <Field label="전시 소개"><textarea name="description" defaultValue={record?.description} placeholder="관람객에게 전시를 소개해 주세요" /></Field>
      <ImagePicker value={image} onChange={setImage} cover imageUrl={record?.imageUrl} busy={busy} status={imageStatus} />
        {error && <Notice error>{error}</Notice>}
      <div className="admin-dialog-actions"><Button tone="secondary" onClick={onClose}>취소</Button>
        <Button type="submit" disabled={busy}>{record ? '저장' : '초안으로 만들기'}</Button></div>
    </form>
  </Modal>;
}

function Heading({ label, title, description, children, className = '' }) {
  return <div className={'admin-heading ' + className}><div><small>{label}</small><h1>{title}</h1>
    {description && <p className="admin-heading-description">{description}</p>}</div>
    {children && <div className="admin-actions">{children}</div>}</div>;
}

function ArtworkHeading({ artwork, exhibition, active }) {
  const { id } = artwork;
  const tabs = [
    ['overview', 'Overview', adminUrl('artwork-edit', { id })],
    ['units', 'Content Units', adminUrl('unit-review', { id })],
    ['followups', 'Follow-up Questions', adminUrl('artwork-edit', { id, panel: 'followups' })],
  ];
  return <div className="admin-artwork-header">
    <nav className="admin-detail-breadcrumb" aria-label="현재 위치">
      <Link to={adminUrl('exhibitions')}>전시 목록</Link><span aria-hidden="true">›</span>
      {exhibition && <><Link to={adminUrl('exhibition', { id: exhibition.id })}>{exhibition.name}</Link><span aria-hidden="true">›</span></>}
      <span aria-current="page">{artwork.name}</span>
    </nav>
    <Heading title={artwork.name} description={<>
      {[artwork.artist, artwork.year, artwork.externalId].filter(Boolean).join(' · ')}
      {exhibition && <span className={'admin-badge ' + (exhibition.isPublic ? 'published' : '')}>{exhibition.isPublic ? '공개' : '비공개'}</span>}
    </>} />
    <nav className="admin-artwork-tabs" aria-label="작품 관리">
      {tabs.map(([key, label, url]) => <Link key={key} to={url} aria-current={key === active ? 'page' : undefined}>{label}</Link>)}
    </nav>
  </div>;
}

function RecordImage({ record, className = '' }) {
  const preview = useRef(null);
  const [failedUrl, setFailedUrl] = useState('');
  useEffect(() => {
    if (!record.image) return;
    const url = URL.createObjectURL(record.image);
    preview.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [record.image]);
  return <span className={'admin-record-image ' + className} aria-hidden="true">
    {record.image ? <img ref={preview} alt="" /> : record.imageUrl && record.imageUrl !== failedUrl &&
      <img src={record.imageUrl} alt="" onError={() => setFailedUrl(record.imageUrl)} />}
  </span>;
}

function ExhibitionRows({ exhibitions, artworks, actionLabel }) {
  const counts = new Map();
  for (const artwork of artworks) counts.set(artwork.exhibitionId, (counts.get(artwork.exhibitionId) ?? 0) + 1);
  return <ul className="admin-exhibition-rows">
    {exhibitions.map((record) => <li key={record.id}>
      <RecordImage record={record} />
      <div><strong>{record.name}</strong><small>{[record.code, record.updated].filter(Boolean).join(' · ')}</small></div>
      <span className={record.isPublic ? 'admin-badge approved' : 'admin-badge'}>{record.isPublic ? '공개' : '비공개'}</span>
      <span>{counts.get(record.id) ?? 0}점</span>
      <Button tone="secondary" to={adminUrl('exhibition', { id: record.id })}>{actionLabel}</Button>
    </li>)}
  </ul>;
}

function Dashboard({ exhibitions, artworks, units, onAdd, followups }) {
  const pending = units.filter((unit) => unit.status === statuses[0]);
  const reviewed = units.length - pending.length;
  const progress = units.length ? Math.round(reviewed / units.length * 100) : 0;
  const artworkById = new Map(artworks.map((artwork) => [artwork.id, artwork]));
  const recentActivity = [
    ...units.map((unit) => ({
      id: unit.id, time: unit.updatedAt, label: 'Content Unit', title: unit.label, artworkId: unit.artworkId,
      url: adminUrl('unit-review', { id: unit.artworkId }),
    })),
    ...(followups ?? []).map((question) => ({
      id: question.id, time: question.updated_at, label: '후속 질문', title: question.question, artworkId: question.artwork_id,
      url: adminUrl('artwork-edit', { id: question.artwork_id, panel: 'followups' }),
    })),
    ...artworks.map((artwork) => ({
      id: artwork.id, time: artwork.createdAt, label: '작품 등록', title: artwork.name,
      url: adminUrl('artwork-edit', { id: artwork.id }),
    })),
  ].filter(({ time }) => time).sort((left, right) => Date.parse(right.time) - Date.parse(left.time)).slice(0, 4);
  const pendingFollowups = followups?.filter((item) => item.review_status === 'pending');
  const followupArtworkIds = [...new Set(pendingFollowups?.map((item) => item.artwork_id))];
  const metrics = [
    ['전체 전시', exhibitions.length, '공개 ' + exhibitions.filter((record) => record.isPublic).length + '개'],
    ['등록된 작품', artworks.length, '전시 ' + new Set(artworks.map((record) => record.exhibitionId)).size + '개에 연결'],
    ['전체 Content Unit', units.length, '게시 ' + units.filter((unit) => unit.status === statuses[2]).length + '개'],
    ['검수 대기 Content Unit', pending.length, '관리자 확인 필요'],
  ];
  return <>
    <Heading title="대시보드"><Button onClick={onAdd}>+ 신규 전시 등록</Button></Heading>
    <div className="admin-metrics">{metrics.map(([label, value, detail]) => <article key={label} className="admin-card">
      <p>{label}</p><strong>{value}</strong><small>{detail}</small>
    </article>)}</div>
    <section className="admin-card admin-stack">
      <div className="admin-section-heading"><h2>전시 현황</h2><Button tone="secondary" to={adminUrl('exhibitions')}>전체 전시 보기</Button></div>
      {exhibitions.length ? <ExhibitionRows exhibitions={exhibitions.slice(0, 3)} artworks={artworks} actionLabel="전시 관리" />
        : <p className="admin-muted">아직 등록된 전시가 없습니다.</p>}
    </section>
    <section className="admin-card admin-stack">
      <div className="admin-section-heading"><h2>검수 현황</h2><Button tone="secondary" to={adminUrl('units')}>Content Unit 관리</Button></div>
      <small>검수 완료 {reviewed}개 · 검수 대기 {pending.length}개</small>
      <div className="admin-review-progress"><strong>{progress}%</strong><progress value={progress} max={100} aria-label="검수 진행률" /></div>
      {pending.length > 0 && <div><strong>검수 필요</strong><ul className="admin-dashboard-links">
        {pending.slice(0, 4).map((unit) => <li key={unit.id}><Link to={adminUrl('unit-review', { id: unit.artworkId })}>
          {artworkById.get(unit.artworkId)?.name} · {unit.label}
        </Link></li>)}
      </ul></div>}
      {followups && <div className="admin-stack">
        <hr /><strong>후속 질문 검수</strong>
        <p>전체 {followups.length}개 · 검수 대기 {pendingFollowups.length}개</p>
        {followupArtworkIds.length > 0 && <ul className="admin-dashboard-links">
          {followupArtworkIds.map((id) => <li key={id}><Link to={adminUrl('artwork-edit', { id, panel: 'followups' })}>
            {artworkById.get(id)?.name ?? '작품 상세'} · {pendingFollowups.filter((row) => row.artwork_id === id).length}개
          </Link></li>)}
        </ul>}
      </div>}
    </section>
    <section className="admin-card admin-stack">
      <h2>최근 작업</h2>
      {recentActivity.length ? <ul className="admin-dashboard-links admin-recent-activity">
        {recentActivity.map((activity) => <li key={activity.label + activity.id}>
          <strong>{activity.label}</strong>
          <Link to={activity.url}>
            {[artworkById.get(activity.artworkId)?.name, activity.title].filter(Boolean).join(' · ')}
          </Link>
          <time dateTime={activity.time}>{new Date(activity.time).toLocaleString('ko-KR', {
            month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
          })}</time>
        </li>)}
      </ul> : <p className="admin-muted">표시할 최근 검수 작업이 없습니다.</p>}
    </section>
  </>;
}

const listings = {
  exhibitions: {
    search: '전시명 또는 전시 코드 검색', filter: '전체 공개 상태', columns: ['전시명', '전시 코드', '작품', '최근 수정', '상태'],
    empty: ['등록된 전시가 없습니다', '신규 전시 등록으로 첫 전시를 추가하세요.'], note: '공개 상태는 전시 상세에서 관리합니다.',
  },
  artworks: {
    search: '작품명 또는 작가명 검색', filter: '전체 전시', columns: ['작품명', '작가명', '소속 전시', '추출 상태', '최근 수정'],
    empty: ['등록된 작품이 없습니다', '소속 전시를 선택하고 작품과 Description을 등록하세요.'], note: '작품 상세에서 Unit 추출을 실행하고 결과를 확인할 수 있습니다.',
  },
  units: {
    search: '작품명 검색', filter: '전체 검수 상태', columns: ['작품명', '소속 전시', '검수 대기', '검수 완료', '게시됨'],
    empty: ['추출된 Content Unit이 없습니다', '작품 상세에서 Description을 저장하고 Content Unit 추출을 실행하세요.'],
    note: '검수를 완료하고 게시한 Unit만 관람객 도슨트 생성에 사용됩니다.',
  },
};

function Listing({ view, exhibitions, artworks, units, onAdd }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const config = listings[view];
  const exhibitionName = (id) => exhibitions.find((record) => record.id === id)?.name ?? '—';
  const count = (id, status) => units.filter((unit) => unit.artworkId === id && unit.status === status).length;
  const matches = (...values) => values.join(' ').toLowerCase().includes(query.trim().toLowerCase());
  const rows = {
    exhibitions: exhibitions.filter((record) => matches(record.name, record.code) && (!filter || filter === (record.isPublic ? '공개' : '비공개'))).map((record) =>
      [record.id, record.name, record.code || '—', artworks.filter((artwork) => artwork.exhibitionId === record.id).length, record.updated, record.isPublic ? '공개' : '비공개']),
    artworks: artworks.filter((record) => matches(record.name, record.artist) && (!filter || record.exhibitionId === filter)).map((record) =>
      [record.id, record.name, record.artist || '—', exhibitionName(record.exhibitionId), (units.some((unit) => unit.artworkId === record.id && unit.extractionMethod === 'automatic') ? '추출 완료' : '추출 전'), record.updated]),
    units: artworks.filter((record) => matches(record.name) && units.some((unit) =>
      unit.artworkId === record.id && (!filter || unit.status === filter))).map((record) =>
      [record.id, record.name, exhibitionName(record.exhibitionId), ...statuses.map((status) => count(record.id, status))]),
  }[view];
  const options = view === 'artworks' ? exhibitions.map(({ id, name }) => [id, name])
    : (view === 'exhibitions' ? ['비공개', '공개'] : statuses).map((status) => [status, status]);
  const detail = { exhibitions: 'exhibition', artworks: 'artwork-edit', units: 'unit-review' }[view];
  return <>
    <Heading title={screens[view]?.[1] ?? (view === 'artworks' ? '작품 관리' : 'Content Units')}>
      {view === 'exhibitions' && <Button onClick={onAdd}>+ 신규 전시 등록</Button>}
      {view === 'artworks' && <Button to={adminUrl('artwork-new')}>+ 작품 등록</Button>}
      {view === 'units' && <Button to={adminUrl('artworks')}>작품 목록 보기</Button>}
    </Heading>
    <div className="admin-filters">
      <input type="search" placeholder={config.search} aria-label={config.search} value={query} onChange={(event) => setQuery(event.target.value)} />
      <select aria-label={config.filter} value={filter} onChange={(event) => setFilter(event.target.value)}>
        <option value="">{config.filter}</option>
        {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </div>
    {view === 'exhibitions' && rows.length > 0
      ? <section className="admin-card"><ExhibitionRows exhibitions={rows.map(([id]) => exhibitions.find((record) => record.id === id))}
        artworks={artworks} actionLabel="상세 보기" /></section>
      : <div className="admin-card admin-flush admin-table-scroll">
      <table className="admin-table">
        <thead><tr>{config.columns.map((column) => <th key={column} scope="col">{column}</th>)}
          <th scope="col"><span className="admin-visually-hidden">작업</span></th></tr></thead>
        <tbody>{rows.map(([id, name, ...values]) => <tr key={id}>
          <td><Link className="admin-table-title" to={adminUrl(detail, { id })}>
            {view === 'artworks' && <RecordImage record={artworks.find((record) => record.id === id)} />}
            {name}</Link></td>
          {values.map((value, index) => <td key={config.columns[index + 1]}>{value}</td>)}
          <td><Link to={adminUrl(detail, { id })}>{view === 'units' ? '검수 열기' : '상세 보기'}</Link></td>
        </tr>)}
        {!rows.length && <tr><td colSpan={6} className="admin-no-rows">
          <Empty title={query || filter ? '검색 결과가 없습니다' : config.empty[0]}>
            {query || filter ? '검색어나 필터를 변경해 주세요.' : config.empty[1]}
          </Empty>
        </td></tr>}</tbody>
      </table>
    </div>}
    <Notice>{config.note}</Notice>
  </>;
}

function ArtworkOrderList({ artworks, onSave }) {
  const original = artworks.map(({ id }) => id);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const ids = draft ?? original;
  const changed = ids.some((id, index) => id !== original[index]);
  const byId = new Map(artworks.map((artwork) => [artwork.id, artwork]));

  function move(index, direction) {
    const updated = [...ids];
    const destination = index + direction;
    [updated[index], updated[destination]] = [updated[destination], updated[index]];
    setDraft(updated);
    setError('');
  }

  async function save() {
    setSaving(true);
    setError('');
    try {
      await onSave(original, ids);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSaving(false);
    }
  }

  return <>
    <p className="admin-muted">관람객은 사전 질문을 마치면 첫 번째 작품부터 감상합니다.</p>
    <ol className="admin-record-list admin-artwork-order">
      {ids.map((id, index) => {
        const artwork = byId.get(id);
        return <li key={id}>
        <div className="admin-artwork-order-row">
          <span className="admin-artwork-order-position" aria-hidden="true">{index + 1}</span>
          <Link className="admin-table-title" to={adminUrl('artwork-edit', { id })}>
            <RecordImage record={artwork} /><span>
              <strong>{artwork.name}</strong>
              <small>{[artwork.artist, artwork.year].filter(Boolean).join(' · ')}</small>
            </span>
          </Link>
          <div className="admin-artwork-order-controls">
            <Button tone="secondary" aria-label={artwork.name + ' 위로'} disabled={saving || index === 0}
              onClick={() => move(index, -1)}>↑</Button>
            <Button tone="secondary" aria-label={artwork.name + ' 아래로'} disabled={saving || index === ids.length - 1}
              onClick={() => move(index, 1)}>↓</Button>
          </div>
        </div>
        </li>;
      })}
    </ol>
    {error && <Notice error>{error}</Notice>}
    {ids.length > 1 && <Button onClick={save} disabled={!changed || saving}>{saving ? '저장 중…' : '순서 저장'}</Button>}
  </>;
}

function ExhibitionDetail({ record, artworks, onEdit, onDelete, onPublish, onSaveOrder, preview }) {
  const ranks = new Map(record.artworkOrder?.map((id, index) => [id, index]));
  const ordered = [...artworks].sort((left, right) =>
    (ranks.get(left.id) ?? ranks.size) - (ranks.get(right.id) ?? ranks.size)
    || (left.createdAt ?? '').localeCompare(right.createdAt ?? '')
    || left.id.localeCompare(right.id));
  return <>
    <Heading title={record.name}><Button tone="secondary" to={adminUrl('exhibitions')}>← 전시 목록</Button>
      <Button onClick={onEdit}>전시 정보 수정</Button></Heading>
    <div className="admin-stack admin-exhibition-detail">
      <section className="admin-card admin-stack">
        <div className="admin-exhibition-summary">
          <RecordImage record={record} />
          <div className="admin-stack">
            <strong>전시 소개</strong>
            <p className="admin-source admin-blue">{record.description || '등록된 전시 소개가 없습니다.'}</p>
            {record.updated && <small>최근 수정 · {record.updated}</small>}
          </div>
          <span className={record.isPublic ? "admin-badge approved" : "admin-badge"}>{record.isPublic ? "공개" : "비공개"}</span>
        </div>
        <hr />
        <div className="admin-form-grid">
          <div><strong>전시 코드</strong><p className="admin-muted admin-code">{record.code || '전시 코드 없음'}</p></div>
          <div><strong>관람객 진입 링크</strong>
            {record.isPublic && !preview ? <p><Link to={visitorUrl(record.id)}>관람객 화면에서 열기</Link></p>
              : <p className="admin-muted">전시를 공개하면 관람객이 열 수 있습니다.</p>}
          </div>
        </div>
        <div className="admin-dialog-actions">
          <Button onClick={onPublish}>공개 상태 변경</Button>
          <Button tone="danger" onClick={onDelete}>전시 삭제</Button>
        </div>
      </section>
      <section className="admin-card admin-stack">
        <div className="admin-section-heading"><h2>전시 작품</h2>
          <Button tone="secondary" to={adminUrl('artwork-new', { exhibition: record.id })}>+ 작품 추가</Button></div>
        {ordered.length ? <ArtworkOrderList key={JSON.stringify(ordered.map(({ id }) => id))}
          artworks={ordered} onSave={onSaveOrder} />
          : <p className="admin-muted">등록된 작품이 없습니다. 이 전시에 작품을 추가할 수 있습니다.</p>}
      </section>
    </div>
  </>;
}

function ArtworkForm({ record, exhibition, exhibitions, onSave, onDelete, preview, extracting, extractionFailed, busy, imageStatus }) {
  const [image, setImage] = useState(record?.image ?? null);
  return <>
    {!record && <Heading title="작품 등록">
      <Button tone="secondary" to={exhibition ? adminUrl('exhibition', { id: exhibition }) : adminUrl('exhibitions')}>← 소속 전시</Button>
    </Heading>}
    {extracting && <p role="status" className="admin-notice">Unit을 추출하고 분류하는 중입니다…</p>}
    {extractionFailed && <p><Link to={adminUrl('ai')}>AI Settings에서 활성 프롬프트 확인</Link></p>}
    <form id="admin-artwork-form" className="admin-artwork-grid" onSubmit={(event) => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(event.currentTarget));
      if (fields.name.trim()) onSave(
        { ...fields, name: fields.name.trim(), image },
        event.nativeEvent.submitter?.name === 'extract',
        () => setImage(null),
      );
    }}>
      <div className="admin-stack">
        <section className="admin-card admin-stack">
          <h2>작품 이미지</h2><ImagePicker value={image} onChange={setImage} imageUrl={record?.imageUrl} busy={busy} status={imageStatus} />
        </section>
        {record && <section className="admin-card admin-stack">
          <h2>작품 관리 정보</h2>
          <div className="admin-section-heading"><span>연결 전시</span><span>{exhibitions.find(({ id }) => id === record.exhibitionId)?.name ?? '—'}</span></div>
          <div className="admin-section-heading"><span>Content Unit</span>
            <Link to={adminUrl('unit-review', { id: record.id })}>검수 열기</Link></div>
          <small>최근 수정 · {record.updated}</small>
        </section>}
      </div>
      <section className="admin-card admin-stack">
        <div className="admin-form-grid">
          <Field label="작품명"><input name="name" defaultValue={record?.name} placeholder="작품명 입력" required /></Field>
          <Field label="작가명"><input name="artist" defaultValue={record?.artist} placeholder="작가명 입력" /></Field>
        </div>
        <Field label="소속 전시"><select name="exhibitionId" defaultValue={record?.exhibitionId ?? exhibition ?? ''} required>
          <option value="">소속 전시 선택</option>
          {exhibitions.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
        </select></Field>
        {!exhibitions.length && <Notice>작품을 등록하려면 <Link to={adminUrl('exhibitions')}>전시를 먼저 추가</Link>하세요.</Notice>}
        <div className="admin-section-heading"><h2>원본 Description</h2><span className="admin-badge">원본 자료</span></div>
        <Notice>{record
          ? 'Description을 수정하면 변경된 원문을 기준으로 Unit을 다시 추출하고 검수하세요.'
          : '저장하면 작품 ID가 자동 생성됩니다. 원본 Description으로 Unit을 추출할 수 있습니다.'}</Notice>
        <textarea name="description" className="admin-description" aria-label="원본 Description" defaultValue={record?.description}
          placeholder="작품 Description 원문을 입력하세요." />
        <div className="admin-form-grid">
          <Field label="원문 언어"><select name="language" defaultValue={record?.language ?? ''}>
            <option value="">언어 선택</option><option value="ko">한국어</option><option value="en">영어</option><option value="other">기타</option>
          </select></Field>
          <Field label="제작 연도"><input name="year" defaultValue={record?.year} placeholder="제작 연도 입력" /></Field>
        </div>
        <div className="admin-dialog-actions admin-editor-actions">
          {record && <Button tone="danger" onClick={onDelete} disabled={busy}>삭제</Button>}
          <Button tone={preview ? 'primary' : 'secondary'} type="submit" disabled={busy}>
            {record ? '수정사항 저장' : '저장'}
          </Button>
          {!preview && <Button type="submit" name="extract" disabled={busy}>
            {extracting ? 'Unit 추출 중…' : extractionFailed ? '추출 재시도' : '저장 후 Unit 추출'}
          </Button>}
        </div>
      </section>
    </form>
  </>;
}

function UnitForm({ onSave, onClose, busy, error }) {
  const [content, setContent] = useState('');
  const [category, setCategory] = useState('');
  return <Modal title="Content Unit 수동 추가" onClose={onClose}>
    <form className="admin-stack" onSubmit={(event) => { event.preventDefault(); onSave({ content: content.trim(), category }); }}>
      <Field label="Unit 내용"><input value={content} placeholder="내용 입력" onChange={(event) => setContent(event.target.value)} required /></Field>
      <fieldset className="admin-categories"><legend>WHAT 카테고리</legend>
        <div>{categories.map((item) => <Button key={item} tone="secondary" aria-pressed={category === item}
          onClick={() => setCategory(item)}>{item}</Button>)}</div>
      </fieldset>
      {error && <Notice error>{error}</Notice>}
      <div className="admin-dialog-actions"><Button tone="secondary" onClick={onClose}>취소</Button>
        <Button type="submit" disabled={busy || !content.trim() || !category}>추가</Button></div>
    </form>
  </Modal>;
}

function UnitEditor({ unit, onSave, onDelete }) {
  const [content, setContent] = useState(unit.content);
  const [category, setCategory] = useState(unit.category);
  const [isRequired, setRequired] = useState(unit.isRequired ?? false);
  const changed = content.trim() !== unit.content || category !== unit.category || isRequired !== Boolean(unit.isRequired);
  const edits = { content: content.trim(), category, isRequired: isRequired === Boolean(unit.isRequired) ? undefined : isRequired };
  const manual = unit.extractionMethod === 'manual';
  return <form className="admin-card admin-stack admin-unit-editor" aria-label="Unit 상세" onSubmit={(event) => {
    event.preventDefault();
    if (content.trim()) onSave(unit, event.nativeEvent.submitter?.value || 'save', changed ? edits : undefined);
  }}>
    <div className="admin-section-heading"><strong className="admin-unit-detail-code">{unit.label}</strong><Status unit={unit} /></div>
    <Field label="Unit 내용"><textarea value={content} required onChange={(event) => setContent(event.target.value)} /></Field>
    <hr />
    <Field label="WHAT 카테고리"><select value={category} onChange={(event) => setCategory(event.target.value)}>
      {categories.map((item) => <option key={item}>{item}</option>)}
    </select></Field>
    <small>{categories.map((item) => <span key={item} className="admin-category-help">
      <strong className="admin-category">{item}</strong> · {categoryLabels[item]}
    </span>)}</small>
    <div className="admin-notice admin-unit-evidence">
      <strong>{manual ? '수동 추가' : '선택 Unit의 원문 근거'}</strong>
      {manual ? <p>관리자가 직접 작성한 Unit입니다.</p>
        : unit.sourceEvidence?.length > 0
          ? <ul className="admin-record-list">{unit.sourceEvidence.map((quote, index) => <li key={index}>{quote}</li>)}</ul>
          : <p>저장된 원문 근거가 없습니다.</p>}
    </div>
    {(unit.needsSplit || unit.needsReview) && <small>
      {[unit.needsSplit && 'AI 분리 제안', unit.needsReview && 'AI 분류 확인 필요'].filter(Boolean).join(' · ')}
    </small>}
    {unit.classificationRationale && <small>AI 분류 근거 · {unit.classificationRationale}</small>}
    <label className="admin-required-unit"><input type="checkbox" checked={isRequired}
      onChange={(event) => setRequired(event.target.checked)} /> 필수 Unit</label>
    <div className="admin-dialog-actions admin-editor-actions">
      <Button tone="danger" onClick={() => onDelete(unit)}>삭제</Button>
      <Button tone="secondary" type="submit" value="save" disabled={!content.trim() || !changed}>수정사항 저장</Button>
      {(unit.status === statuses[0] || changed) && <Button tone="secondary" type="submit" value="review" disabled={!content.trim()}>검수 완료</Button>}
      {unit.status === statuses[2] && <Button tone="secondary" onClick={() => onSave(unit, 'unpublish')}>게시 해제</Button>}
      {(unit.status !== statuses[2] || changed) && <Button type="submit" value="publish" disabled={!content.trim()}>검수 완료 및 게시</Button>}
    </div>
  </form>;
}

function Status({ unit }) {
  return <span className={'admin-badge ' + ['pending', 'approved', 'published'][statuses.indexOf(unit.status)]}>{unit.status}</span>;
}

function UnitReview({ artwork, units, onAdd, onSave, onDelete, onPublish, onReviewSelected, onExtract }) {
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [categoryDialog, setCategoryDialog] = useState(false);
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [reviewResult, setReviewResult] = useState(null);
  const visible = units.filter((unit) => (!filter || unit.status === filter)
    && (!categoryFilter || unit.category === categoryFilter));
  const selected = visible.find((unit) => unit.id === selectedId) ?? visible[0];
  const reviewable = visible.filter((unit) => unit.status !== statuses[2]);
  const checked = reviewable.filter((unit) => checkedIds.has(unit.id));
  const allChecked = reviewable.length > 0 && checked.length === reviewable.length;

  async function reviewChecked(action) {
    setReviewResult(null);
    const result = await onReviewSelected(checked.map((unit) => unit.id), action);
    if (result) {
      setCheckedIds(new Set());
      setReviewResult(result);
    }
  }

  return <>
    <div className="admin-dialog-actions">
      {onExtract && <Button tone="secondary" disabled={!artwork.description?.trim()} onClick={onExtract}>Unit 다시 추출</Button>}
      <Button disabled={!units.some((unit) => unit.status === statuses[1])} onClick={onPublish}>검수 완료 Unit 게시</Button>
    </div>
    <details className="admin-card admin-review-source" open>
      <summary>원본 Description 보기</summary>
      <p className="admin-source">{artwork.description || '저장된 원본 Description이 없습니다.'}</p>
    </details>
    <div className="admin-review-grid">
      <section className="admin-card admin-review-list" aria-label="Content Unit 목록">
        <div className="admin-section-heading"><h2>Content Units</h2><Button tone="secondary" onClick={onAdd}>+ 수동 추가</Button></div>
        <div className="admin-review-filters">
          <div className="admin-review-statuses" role="group" aria-label="검수 상태 필터">
            {['', ...statuses].map((status) => <Button key={status} tone="secondary" aria-pressed={filter === status}
              onClick={() => { setFilter(status); setSelectedId(null); setCheckedIds(new Set()); }}>{status || '전체'}</Button>)}
          </div>
          <Button tone="secondary" className="admin-review-category" aria-haspopup="dialog" aria-expanded={categoryDialog}
            onClick={() => setCategoryDialog(true)}>{categoryFilter || '전체 카테고리'}</Button>
        </div>
        <div className="admin-review-toolbar">
          <div className="admin-review-selection">
            <small>{checked.length}개 선택</small>
            <Button tone="secondary" disabled={!reviewable.length || allChecked}
              onClick={() => setCheckedIds(new Set(reviewable.map((unit) => unit.id)))}>전체 선택</Button>
            <Button tone="secondary" disabled={!checked.length} onClick={() => setCheckedIds(new Set())}>전체 해제</Button>
            {checked.length > 0 && <>
              <Button tone="secondary" disabled={!checked.some((unit) => unit.status === statuses[0])}
                onClick={() => reviewChecked('review')}>선택 검수 완료</Button>
              <Button onClick={() => reviewChecked('publish')}>선택 검수 완료 및 게시</Button>
            </>}
          </div>
        </div>
        {reviewResult && <p className={reviewResult.failed.length || reviewResult.refreshFailed ? 'admin-notice error' : 'admin-notice'} role="status">
          {reviewResult.action === 'publish' ? '게시' : '검수 완료'} {reviewResult.reviewed}건 · 실패 {reviewResult.failed.length}건
          {reviewResult.failed.length > 0 && ' · ' + reviewResult.failed.join(' / ')}
          {reviewResult.refreshFailed && ' · 최신 목록을 불러오지 못했습니다.'}
        </p>}
        <div className="admin-review-results">{visible.map((unit) => <div key={unit.id} className="admin-review-row">
          <input type="checkbox" aria-label={unit.label + ' 검수 선택'} disabled={unit.status === statuses[2]}
            checked={unit.status !== statuses[2] && checkedIds.has(unit.id)}
            onChange={(event) => {
              const isChecked = event.target.checked;
              setCheckedIds((current) => {
                const next = new Set(current);
                if (isChecked) next.add(unit.id);
                else next.delete(unit.id);
                return next;
              });
            }} />
          <button type="button" className="admin-unit" aria-pressed={unit.id === selected?.id}
            onClick={() => setSelectedId(unit.id)}>
            <span className="admin-section-heading"><strong className="admin-unit-list-code">{unit.label}</strong><Status unit={unit} /></span>
            <span className="admin-source">{unit.content}</span><strong className="admin-category">{unit.category}</strong>
          </button>
        </div>)}</div>
        {!visible.length && <p className="admin-muted">{units.length ? '선택한 조건의 Unit이 없습니다.' : '등록된 Content Unit이 없습니다.'}</p>}
      </section>
      {selected ? <UnitEditor key={JSON.stringify(selected)} unit={selected} onSave={onSave} onDelete={onDelete} />
        : <div className="admin-card admin-unit-editor"><p className="admin-muted">선택할 Content Unit이 없습니다.</p></div>}
    </div>
    <section className="admin-card admin-review-publish">
      <h2>게시 조건</h2><p className="admin-blue">검수를 완료한 Unit을 게시할 수 있습니다. 관람객 도슨트에는 게시된 Unit만 사용됩니다.</p>
    </section>
    {categoryDialog && <Modal title="카테고리 필터" compact onClose={() => setCategoryDialog(false)}>
      <div className="admin-review-category-options">
        {['', ...categories].map((category) => <Button key={category} tone="secondary"
          aria-pressed={categoryFilter === category} onClick={() => {
            setCategoryFilter(category);
            setSelectedId(null);
            setCheckedIds(new Set());
            setCategoryDialog(false);
          }}>{category ? <><strong className="admin-category">{category}</strong>&nbsp;· {categoryLabels[category]}</>
            : '전체 카테고리'}</Button>)}
      </div>
    </Modal>}
  </>;
}

function errorMessage(error) {
  if (error.status === 401) return '로그인 정보가 올바르지 않거나 세션이 만료되었습니다.';
  if (error.status === 403) return '관리자 권한을 확인해 주세요.';
  return error.message || '관리자 요청에 실패했습니다.';
}

function LiveAdmin() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [session] = useState(createAdminSession);
  const [user, setUser] = useState(() => session.user);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);

  const call = useCallback(async (action, ...args) => {
    try {
      return await session.call(action, ...args);
    } catch (failure) {
      if (failure.status === 401 || failure.status === 403) {
        session.clear();
        setUser(null);
        setError(errorMessage(failure));
      }
      throw failure;
    }
  }, [session]);

  async function login(email, password) {
    if (submitting.current) return;
    submitting.current = true;
    setError('');
    setBusy(true);
    try {
      setUser(await session.login(email, password));
      if (!params.get('view') || params.get('view') === 'login') navigate(adminUrl('dashboard'), { replace: true });
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }

  async function logout() {
    await call('logout');
    session.clear();
    setUser(null);
    setError('');
    navigate('/admin', { replace: true });
  }

  if (!user) return <Login onLogin={login} error={error} busy={busy} />;
  return <Workspace call={call} user={user} onLogout={logout} />;
}

function mergeRecord(records, record) {
  return records.some((item) => item.id === record.id)
    ? records.map((item) => item.id === record.id ? record : item)
    : [record, ...records];
}

function UnitReviewLoader({ call, artwork, onLoad, ...props }) {
  const [request, setRequest] = useState({ state: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const artworkId = artwork.id;

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    call('listUnits', { artworkId, signal }).then((rows) => {
      if (signal.aborted) return;
      if (rows.some((unit) => unit.artworkId !== artworkId)) {
        throw new Error('작품과 일치하지 않는 Content Unit 응답을 받았습니다.');
      }
      onLoad(rows);
      setRequest({ state: 'ready' });
    }).catch((failure) => {
      if (!signal.aborted) setRequest({ state: 'failed', message: errorMessage(failure) });
    });
    return () => controller.abort();
  }, [artworkId, attempt, call, onLoad]);

  if (request.state === 'loading') return <p role="status">작품의 Content Unit을 불러오는 중입니다…</p>;
  if (request.state === 'failed') return <div className="admin-card admin-stack">
    <Notice error>Content Unit을 불러오지 못했습니다. {request.message}</Notice>
    <Button tone="secondary" onClick={() => {
      setRequest({ state: 'loading' });
      setAttempt((value) => value + 1);
    }}>다시 불러오기</Button>
  </div>;
  return <UnitReview artwork={artwork} {...props} />;
}

function Workspace({ preview = false, call, user, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [followups, setFollowups] = useState(null);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [exhibitions, setExhibitions] = useState([]);
  const [artworks, setArtworks] = useState([]);
  const [units, setUnits] = useState([]);
  const [reviewUnits, setReviewUnits] = useState([]);
  const [overview, setOverview] = useState({ state: 'loading' });
  const [overviewAttempt, setOverviewAttempt] = useState(0);
  const [loaded, setLoaded] = useState(preview);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const [modal, setModal] = useState(null);
  const [nextUnit, setNextUnit] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [extracting, setExtracting] = useState(false);
  const [imageStatus, setImageStatus] = useState('');
  const [imageNotice, setImageNotice] = useState('');
  const [extractionFailedId, setExtractionFailedId] = useState(null);
  const saving = useRef(false);
  const requestedView = params.get('view');
  const view = requestedView && requestedView !== 'login' ? requestedView : 'dashboard';
  const id = params.get('id');
  const needsOverview = view === 'dashboard' || view === 'artworks' || view === 'units';
  const showFollowups = view === 'artwork-edit' && params.get('panel') === 'followups';
  useEffect(() => {
    if (preview || view !== 'dashboard') return;
    const controller = new AbortController();
    call('listFollowupOverview', controller.signal).then((rows) => {
      if (!controller.signal.aborted) setFollowups(rows);
    }).catch(() => {
      if (!controller.signal.aborted) setFollowups(null);
    });
    return () => controller.abort();
  }, [call, preview, view]);
  const currentReviewUnits = (preview ? units : reviewUnits).filter((unit) => unit.artworkId === id);
  const exhibition = exhibitions.find((record) => record.id === id);
  const artwork = artworks.find((record) => record.id === id);
  const section = ['dashboard', 'ai'].includes(view) ? view : 'exhibitions';
  const artworkExhibition = exhibitions.find((record) => record.id === artwork?.exhibitionId);
  const artworkTab = view === 'unit-review' ? 'units' : showFollowups ? 'followups' : 'overview';
  const close = () => { if (!saving.current) { setModal(null); setError(''); } };
  const open = (details) => { setError(''); setModal(details); };
  const addExhibition = () => open({ kind: 'exhibition' });
  const confirm = (title, message, action, label = '삭제', tone = label === '삭제' ? 'danger' : 'primary') =>
    open({ kind: 'confirm', title, message, action, label, tone });

  useEffect(() => {
    if (preview) return;
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      call('listExhibitions', signal),
      call('listArtworks', undefined, signal),
    ]).then(([exhibitionRows, artworkRows]) => {
      if (signal.aborted) return;
      setExhibitions(exhibitionRows);
      setArtworks(artworkRows);
      setLoaded(true);
    }).catch((failure) => {
      if (!signal.aborted) setLoadError(errorMessage(failure));
    });
    return () => controller.abort();
  }, [call, preview, reload]);

  useEffect(() => {
    if (preview || !needsOverview) return;
    const controller = new AbortController();
    const { signal } = controller;
    call('listUnits', { signal }).then((rows) => {
      if (signal.aborted) return;
      setUnits(rows);
      setOverview({ state: 'ready' });
    }).catch((failure) => {
      if (!signal.aborted) setOverview({ state: 'failed', message: errorMessage(failure) });
    });
    return () => controller.abort();
  }, [call, needsOverview, overviewAttempt, preview]);

  function updateUnits(update) {
    setUnits(update);
    if (!preview) setReviewUnits(update);
  }
  async function perform(action) {
    if (saving.current) return;
    saving.current = true;
    setError('');
    setImageNotice('');
    setBusy(true);
    try {
      await action();
      setModal(null);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  async function saveWithImage(image, saveRecord) {
    if (!image) return saveRecord();
    setImageStatus('이미지를 업로드하는 중입니다…');
    try {
      const { key } = await call('uploadCatalogImage', image);
      setImageStatus('업로드한 이미지 경로를 저장하는 중입니다…');
      const record = await saveRecord(key);
      setImageNotice('이미지를 업로드하고 저장했습니다.');
      return record;
    } catch (failure) {
      throw new Error('이미지 변경을 저장하지 못했습니다. ' + errorMessage(failure), { cause: failure });
    } finally {
      setImageStatus('');
    }
  }

  function saveExhibition(values) {
    perform(async () => {
      const record = preview
        ? { ...modal.record, ...values, id: modal.record?.id ?? crypto.randomUUID(), updated: updated() }
        : await saveWithImage(values.image, (imageKey) =>
          call('saveExhibition', { ...values, imageKey, id: modal.record?.id }));
      setExhibitions((current) => mergeRecord(current, record));
      navigate(adminUrl('exhibition', { id: record.id }));
    });
  }

  async function saveArtworkOrder(expected, order) {
    if (!preview) await call('saveArtworkOrder', id, expected, order);
    setExhibitions((current) => current.map((record) =>
      record.id === id ? { ...record, artworkOrder: order } : record));
  }

  function saveArtwork(values, extractRequested, onPersisted) {
    const replacingImage = artwork && values.image && values.description.trim() === (artwork.description ?? '').trim();
    const extract = extractRequested && !replacingImage;
    if (extract && (preview || !values.description.trim())) {
      if (!preview) setError('Unit을 추출하려면 Description을 입력해 주세요.');
      return;
    }
    perform(async () => {
      const record = preview
        ? { ...values, id: artwork?.id ?? crypto.randomUUID(), updated: updated() }
        : await saveWithImage(values.image, (imageKey) =>
          call('saveArtwork', { ...values, imageKey, id: artwork?.id }));
      setArtworks((current) => mergeRecord(current, record));
      if (!preview && values.image) onPersisted();
      navigate(adminUrl('artwork-edit', { id: record.id }));
      if (!extract) return;

      setExtractionFailedId(null);
      setExtracting(true);
      try {
        const result = await call('extractUnits', record.id);
        if (!Array.isArray(result?.units) || !result.units.length) {
          throw new Error('저장된 Unit이 확인되지 않았습니다. 추출을 다시 시도해 주세요.');
        }
        const verifiedIds = new Set(result.units.map((unit) => unit.id));
        const currentUnits = await call('listUnits', { artworkId: record.id });
        if (!currentUnits.some((unit) => verifiedIds.has(unit.id))) {
          throw new Error('검수 목록에서 저장된 Unit을 불러오지 못했습니다. 다시 시도해 주세요.');
        }
        navigate(adminUrl('unit-review', { id: record.id }));
      } catch (failure) {
        setExtractionFailedId(record.id);
        throw new Error('작품 정보는 저장했습니다. Unit 처리 중 오류가 발생했습니다. ' + errorMessage(failure), { cause: failure });
      } finally {
        setExtracting(false);
      }
    });
  }

  function deleteArtwork() {
    confirm('이 작품을 삭제할까요?', '이 작품이 작품 목록에서 삭제됩니다. 연결된 Content Unit도 함께 삭제됩니다.', async () => {
      if (!preview) await call('deleteArtwork', id);
      setArtworks((current) => current.filter((item) => item.id !== id));
      updateUnits((current) => current.filter((item) => item.artworkId !== id));
      navigate(adminUrl('exhibition', { id: artwork.exhibitionId }));
    }, '작품 삭제', 'danger');
  }

  function deleteExhibition() {
    confirm('전시 삭제', '이 전시와 연결된 작품 및 Content Unit을 삭제할까요?', async () => {
      if (!preview) await call('deleteExhibition', id);
      const artworkIds = new Set(artworks.filter((item) => item.exhibitionId === id).map((item) => item.id));
      setExhibitions((current) => current.filter((item) => item.id !== id));
      setArtworks((current) => current.filter((item) => !artworkIds.has(item.id)));
      updateUnits((current) => current.filter((item) => !artworkIds.has(item.artworkId)));
      navigate(adminUrl('exhibitions'));
    });
  }

  function saveUnit(values) {
    perform(async () => {
      const input = { ...values, artworkId: modal.artworkId };
      const record = preview ? {
        ...input, id: crypto.randomUUID(), label: 'UNIT-' + String(nextUnit).padStart(3, '0'), status: statuses[0], extractionMethod: 'manual',
      } : await call('saveUnit', input);
      if (preview) setNextUnit((current) => current + 1);
      updateUnits((current) => [...current, record]);
    });
  }

  function editUnit(unit, action, edits) {
    perform(async () => {
      const input = { ...unit, ...edits, isRequired: edits?.isRequired };
      const record = preview ? {
        ...unit, ...edits, isRequired: edits?.isRequired ?? unit.isRequired,
        status: action === 'publish' ? statuses[2] : action === 'save'
          ? ((unit.content !== input.content || unit.category !== input.category) ? statuses[0] : unit.status) : statuses[1],
      } : action === 'save' ? await call('saveUnit', input)
        : action === 'review' && !edits ? await call('reviewUnit', unit)
          : await call('reviewWorkspaceUnit', unit, action, edits);
      updateUnits((current) => mergeRecord(current, record));
    });
  }

  async function reviewSelectedUnits(selectedIds, action) {
    if (saving.current) return;
    const selected = new Set(selectedIds);
    const targets = currentReviewUnits.filter((unit) => selected.has(unit.id) &&
      (action === 'review' ? unit.status === statuses[0] : unit.status !== statuses[2]));
    if (!targets.length) return;

    saving.current = true;
    setBusy(true);
    const records = [];
    const failed = [];
    let refreshFailed = false;
    try {
      for (const unit of targets) {
        try {
          const record = preview ? { ...unit, status: statuses[action === 'publish' ? 2 : 1] }
            : action === 'review' ? await call('reviewUnit', unit) : await call('reviewWorkspaceUnit', unit, 'publish');
          records.push(record);
        } catch (failure) {
          failed.push(unit.label + ' · ' + errorMessage(failure));
        }
      }
      updateUnits((current) => records.reduce(mergeRecord, current));
      if (!preview) {
        try {
          const rows = await call('listUnits', { artworkId: id });
          if (rows.some((unit) => unit.artworkId !== id)) throw new Error('Unexpected artwork in Unit list');
          updateUnits((current) => [...current.filter((unit) => unit.artworkId !== id), ...rows]);
        } catch {
          refreshFailed = true;
        }
      }
      return { action, reviewed: records.length, failed, refreshFailed };
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  function setVisibility() {
    const isPublic = !exhibition.isPublic;
    const label = isPublic ? '공개' : '비공개';
    confirm('공개 상태 변경', '전시를 ' + label + ' 상태로 변경할까요?', async () => {
      const record = preview ? { ...exhibition, isPublic } : await call('setExhibitionVisibility', id, isPublic);
      setExhibitions((current) => mergeRecord(current, record));
    }, label);
  }

  function publishUnits() {
    confirm('Unit 게시 확인', '이 작품의 검수 완료 Unit을 게시할까요?', async () => {
      const records = preview
        ? currentReviewUnits.filter((item) => item.status === statuses[1]).map((item) => ({ ...item, status: statuses[2] }))
        : await call('publishUnits', id);
      updateUnits((current) => records.reduce(mergeRecord, current));
    }, '게시');
  }

  const ReviewPage = preview ? UnitReview : UnitReviewLoader;
  let content;
  if (view === 'ai') content = preview
    ? <div className="admin-card"><h2>AI Settings</h2><p>실제 관리자 화면에서 프롬프트를 관리할 수 있습니다.</p></div>
    : <AiSettings call={call} artworks={artworks} />;
  else if (!loaded) content = loadError
    ? <div className="admin-card admin-stack"><Notice error>{loadError}</Notice><Button tone="secondary"
      onClick={() => { setLoadError(''); setReload((value) => value + 1); }}>다시 불러오기</Button></div>
    : <p role="status">관리자 데이터를 불러오는 중입니다…</p>;
  else if (!preview && needsOverview && overview.state !== 'ready') content = overview.state === 'failed'
    ? <div className="admin-card admin-stack"><Notice error>{overview.message}</Notice><Button tone="secondary"
      onClick={() => { setOverview({ state: 'loading' }); setOverviewAttempt((value) => value + 1); }}>다시 불러오기</Button></div>
    : <p role="status">Content Unit 요약을 불러오는 중입니다…</p>;
  else if (view === 'dashboard') content = <Dashboard {...{ exhibitions, artworks, units, followups }} onAdd={addExhibition} />;
  else if (Object.hasOwn(listings, view)) content = <Listing key={view} {...{ view, exhibitions, artworks, units }} onAdd={addExhibition} />;
  else if (view === 'exhibition' && exhibition) content = <ExhibitionDetail record={exhibition} preview={preview}
    artworks={artworks.filter((item) => item.exhibitionId === id)}
    onSaveOrder={saveArtworkOrder}
    onEdit={() => open({ kind: 'exhibition', record: exhibition })}
    onDelete={deleteExhibition} onPublish={setVisibility} />;
  else if (view === 'artwork-edit' && artwork && showFollowups) content = <>
    {preview ? <Notice>후속 질문을 관리하려면 실제 관리자 화면에서 로그인하세요.</Notice>
      : <FollowupQuestions key={id} artworkId={id} call={call} Modal={Modal} />}
  </>;
  else if (view === 'artwork-new' || (view === 'artwork-edit' && artwork)) content = <>
    <ArtworkForm
    key={view === 'artwork-edit' ? artwork.id : params.get('exhibition') ?? view} record={view === 'artwork-edit' ? artwork : undefined}
    exhibition={params.get('exhibition')} exhibitions={exhibitions} preview={preview}
    onSave={saveArtwork} onDelete={deleteArtwork}
    busy={busy} imageStatus={imageStatus} extracting={extracting}
    extractionFailed={Boolean(artwork && artwork.id === extractionFailedId)} />
  </>;
  else if (view === 'unit-review' && artwork) content = <ReviewPage key={id} artwork={artwork}
    {...(!preview && { call, onLoad: setReviewUnits })}
    units={currentReviewUnits}
    onAdd={() => open({ kind: 'unit', artworkId: id })}
    onSave={editUnit}
    onReviewSelected={reviewSelectedUnits}
    onExtract={preview ? undefined : () => confirm('Unit 다시 추출', '현재 원본 Description에서 Unit을 추출할까요?', async () => {
      await call('extractUnits', id);
      const rows = await call('listUnits', { artworkId: id });
      updateUnits((current) => [...current.filter((unit) => unit.artworkId !== id), ...rows]);
    }, 'Unit 추출')}
    onDelete={(target) => confirm('Content Unit 삭제 확인', '선택한 Unit을 삭제할까요?', async () => {
      if (!preview) await call('deleteUnit', target.id);
      updateUnits((current) => current.filter((unit) => unit.id !== target.id));
    })}
    onPublish={publishUnits} />;
  else content = <div className="admin-card admin-stack"><h1>화면을 찾을 수 없습니다</h1>
    <Button to={adminUrl(Object.hasOwn(screens, section) ? section : 'dashboard')}>목록으로 이동</Button></div>;

  const displayName = preview ? '미리보기' : user.display_name;
  function navigation(onSelect) {
    return <nav aria-label="관리자 메뉴">{Object.entries(screens).map(([key, [label]]) =>
      <Link key={key} to={adminUrl(key)} aria-current={key === section ? 'page' : undefined}
        className={key === section ? 'selected' : undefined} onClick={() => { setError(''); onSelect?.(); }}>{label}</Link>)}</nav>;
  }
  const accountAction = preview ? <Button tone="ghost" to="/admin">실제 관리자 화면으로</Button>
    : <Button tone="ghost" onClick={() => { setMenuOpen(false); perform(onLogout); }}>로그아웃</Button>;
  return <div className="admin admin-workspace" aria-busy={busy}>
    <aside className="admin-sidebar" inert={busy}>
      <div><Brand />
        <div className="admin-workspace-label"><small>CURATOR WORKSPACE</small><strong>{preview ? '로컬 미리보기' : '전시 관리자'}</strong></div>
        {navigation()}
      </div>
      <div className="admin-sidebar-footer">
        <div className="admin-account"><span aria-hidden="true">U</span><div><strong>{displayName}</strong><small>{preview ? '로컬 데이터' : '관리자 계정'}</small></div></div>
        {accountAction}
      </div>
    </aside>
    <div className="admin-main" inert={busy}>
      <header className="admin-topbar"><span className="admin-breadcrumb">워크스페이스 / 전시 콘텐츠 관리</span>
        <div className="admin-narrow-nav">
          <Button tone="secondary" aria-haspopup="dialog" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>메뉴</Button>
          <strong>{screens[section]?.[0] ?? 'Dashboard'}</strong>
        </div>
        {preview && <span>로컬 미리보기 · 새로고침하면 입력 내용이 초기화됩니다</span>}</header>
      <main className="admin-page">
        {error && !modal && <Notice error>{error}</Notice>}
        {imageNotice && <p className="admin-notice" role="status">{imageNotice}</p>}
        {artwork && ['artwork-edit', 'unit-review'].includes(view) &&
          <ArtworkHeading artwork={artwork} exhibition={artworkExhibition} active={artworkTab} />}
        {content}
      </main>
    </div>
    {menuOpen && <Modal title="관리자 메뉴" compact onClose={() => setMenuOpen(false)}>
      <div className="admin-menu-links">{navigation(() => setMenuOpen(false))}
        {accountAction}
        <Button tone="ghost" onClick={() => setMenuOpen(false)}>닫기</Button>
      </div>
    </Modal>}
    {modal?.kind === 'exhibition' && <ExhibitionForm record={modal.record} onSave={saveExhibition} onClose={close}
      busy={busy} error={error} imageStatus={imageStatus} />}
    {modal?.kind === 'unit' && <UnitForm onSave={saveUnit} onClose={close} busy={busy} error={error} />}
    {(modal?.kind === 'confirm' || modal?.kind === 'notice') && <Modal title={modal.title} onClose={close}>
      <p className="admin-muted">{modal.message}</p>
        {error && <Notice error>{error}</Notice>}
      <div className="admin-dialog-actions">
        <Button tone="secondary" onClick={close} disabled={busy}>{modal.kind === 'confirm' ? '취소' : '닫기'}</Button>
        {modal.kind === 'confirm' && <Button tone={modal.tone}
          disabled={busy} onClick={() => perform(modal.action)}>{modal.label}</Button>}
      </div>
    </Modal>}
  </div>;
}

export default function Admin({ preview = false }) {
  return preview ? <Workspace preview /> : <LiveAdmin />;
}
