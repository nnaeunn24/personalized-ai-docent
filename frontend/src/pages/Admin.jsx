import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { createAdminSession } from './admin/adminSession';
import AiSettings from './admin/AiSettings';
import { visitorUrl } from './visitor/visitorApi';
import './admin/admin.css';

const screens = {
  dashboard: ['Dashboard', '대시보드'],
  exhibitions: ['Exhibitions', '전시 관리'],
  artworks: ['Artworks', '작품 관리'],
  units: ['Content Units', 'Content Units'],
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

function ImagePicker({ value, onChange, cover = false, disabled = false }) {
  const [error, setError] = useState('');
  const id = cover ? 'exhibition-image' : 'artwork-image';
  function pick(file) {
    if (!file) return;
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      setError('JPG 또는 PNG 이미지를 선택하세요.');
      return;
    }
    setError('');
    onChange(file);
  }
  const imageRef = useRef(null);
  useEffect(() => {
    if (!value) return;
    const url = URL.createObjectURL(value);
    imageRef.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [value]);
  if (disabled) return <div className="admin-upload">
    <span className={cover ? "admin-button secondary admin-drop" : "admin-button secondary"} aria-disabled="true">
      {cover ? "대표 이미지 업로드" : "이미지 업로드"}
    </span>
    <small>이미지 업로드는 준비 중입니다.</small>
  </div>;
  return <div className="admin-upload">
    {value && <img ref={imageRef} alt={cover ? '전시 대표 이미지 미리보기' : '작품 이미지 미리보기'} />}
    <input className="admin-file" id={id} type="file" accept="image/jpeg,image/png"
      onChange={(event) => { pick(event.target.files[0]); event.target.value = ''; }} />
    <label className={'admin-button secondary' + (cover ? ' admin-drop' : '')} htmlFor={id}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => { event.preventDefault(); pick(event.dataTransfer.files[0]); }}>
      {cover ? '대표 이미지 업로드' : '이미지 업로드'}
      {cover && <small>JPG · PNG / 클릭하거나 파일을 끌어놓으세요</small>}
    </label>
    {!cover && <small>JPG · PNG / 원본 비율 유지</small>}
    {value && <Button tone="ghost" onClick={() => onChange(null)}>이미지 제거</Button>}
    {error && <Notice error>{error}</Notice>}
  </div>;
}

function ExhibitionForm({ record, onSave, onClose, preview, busy, error }) {
  const [image, setImage] = useState(record?.image ?? null);
  return <Modal title={record ? '전시 정보 수정' : '신규 전시 등록'} onClose={onClose}>
    <form className="admin-stack" onSubmit={(event) => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(event.currentTarget));
      if (fields.name.trim()) onSave({ ...fields, name: fields.name.trim(), image });
    }}>
      <Field label="전시명"><input name="name" defaultValue={record?.name} placeholder="전시명을 입력하세요" required /></Field>
      <Field label="전시 소개"><textarea name="description" defaultValue={record?.description} placeholder="관람객에게 전시를 소개해 주세요" /></Field>
      <ImagePicker value={image} onChange={setImage} cover disabled={!preview} />
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

function Dashboard({ exhibitions, artworks, units, onAdd }) {
  const metrics = [
    ['등록된 전시', exhibitions.length, exhibitions.length ? '로컬 미리보기 전시' : '등록된 전시 없음'],
    ['등록된 작품', artworks.length, artworks.length ? '로컬 미리보기 작품' : '등록된 작품 없음'],
    ['검수 대기 Unit', units.filter((unit) => unit.status === statuses[0]).length, '관리자 확인이 필요한 Unit'],
    ['게시된 Unit', units.filter((unit) => unit.status === statuses[2]).length, '도슨트 생성에 사용 가능'],
  ];
  return <>
    <Heading label="DASHBOARD" title="대시보드"><Button onClick={onAdd}>+ 신규 전시 등록</Button></Heading>
    <div className="admin-metrics">{metrics.map(([label, value, detail]) => <article key={label} className="admin-card">
      <p>{label}</p><strong>{value}</strong><small>{detail}</small>
    </article>)}</div>
    <section className="admin-card admin-flush">
      {exhibitions.length === 0 ? <Empty title="아직 등록된 전시가 없습니다">전시를 만든 다음 작품과 Description을 등록하세요.</Empty>
        : <Empty title="등록된 전시"><Link to={adminUrl('exhibitions')}>전시 목록 보기</Link></Empty>}
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
    <Heading label={screens[view][0].toUpperCase()} title={screens[view][1]}>
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
    <div className="admin-card admin-flush">
      <table className="admin-table">
        <thead><tr>{config.columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{rows.map(([id, name, ...values]) => <tr key={id}>
          <td><Link to={adminUrl(detail, { id })}>{name}</Link></td>
          {values.map((value, index) => <td key={config.columns[index + 1]}>{value}</td>)}
        </tr>)}
        {!rows.length && <tr><td colSpan={5} className="admin-no-rows">
          <Empty title={query || filter ? '검색 결과가 없습니다' : config.empty[0]}>
            {query || filter ? '검색어나 필터를 변경해 주세요.' : config.empty[1]}
          </Empty>
        </td></tr>}</tbody>
      </table>
    </div>
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
      {ids.map((id, index) => <li key={id}>
        <div className="admin-artwork-order-row">
          <Link to={adminUrl('artwork-edit', { id })}>{byId.get(id).name}</Link>
          <div className="admin-artwork-order-controls">
            <Button tone="secondary" aria-label={byId.get(id).name + ' 위로'} disabled={saving || index === 0}
              onClick={() => move(index, -1)}>↑</Button>
            <Button tone="secondary" aria-label={byId.get(id).name + ' 아래로'} disabled={saving || index === ids.length - 1}
              onClick={() => move(index, 1)}>↓</Button>
          </div>
        </div>
      </li>)}
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
    <Heading label="EXHIBITIONS / 상세" title="전시 상세"><Button onClick={onEdit}>전시 정보 수정</Button></Heading>
    <div className="admin-detail-grid">
      <section className="admin-card admin-stack">
        <div className="admin-section-heading"><h2>전시 작품</h2>
          <Button tone="secondary" to={adminUrl('artwork-new', { exhibition: record.id })}>+ 작품 추가</Button></div>
        {ordered.length ? <ArtworkOrderList key={JSON.stringify(ordered.map(({ id }) => id))}
          artworks={ordered} onSave={onSaveOrder} />
          : <p className="admin-muted">등록된 작품이 없습니다. 이 전시에 작품을 추가할 수 있습니다.</p>}
      </section>
      <section className="admin-card admin-stack">
        <span className={record.isPublic ? "admin-badge approved" : "admin-badge pending"}>{record.isPublic ? "공개" : "비공개"}</span>
        <h2>전시 정보</h2><strong>{record.name}</strong>
        {record.description && <p className="admin-source admin-muted">{record.description}</p>}
        <hr />
        <Field label="전시 코드"><input value={record.code ?? ""} placeholder="전시 코드 없음" readOnly /></Field>
        <strong>관람객 진입 링크</strong>
        {record.isPublic && !preview ? <Link to={visitorUrl(record.id)}>관람객 화면에서 열기</Link>
          : <p className="admin-muted">실제 전시를 공개하면 관람객이 열 수 있습니다.</p>}
        <Button onClick={onPublish}>공개 상태 변경</Button>
        <Button tone="danger" onClick={onDelete}>전시 삭제</Button>
      </section>
    </div>
  </>;
}

function ArtworkForm({ record, exhibition, exhibitions, onSave, onDelete, preview, extracting, extractionFailed }) {
  const [image, setImage] = useState(record?.image ?? null);
  return <>
    <Heading className="admin-artwork-heading" label={record ? 'ARTWORKS / 작품 상세' : 'ARTWORKS / 등록'}
      title={record ? '작품 정보 편집' : '작품 등록'}
      description={record && <>작품 ID · <span className="admin-artwork-id">ART-{record.id.toUpperCase()}</span></>}>
      {record && <Button tone="danger" onClick={onDelete} disabled={extracting}>삭제</Button>}
      <Button type="submit" form="admin-artwork-form" name={preview ? undefined : 'extract'} disabled={extracting}>
        {preview ? '저장' : extracting ? 'Unit 추출 중…' : extractionFailed ? '추출 재시도' : '저장 후 Unit 추출'}
      </Button>
    </Heading>
    {extracting && <p role="status" className="admin-notice">Unit을 추출하고 분류하는 중입니다…</p>}
    <form id="admin-artwork-form" className="admin-artwork-grid" onSubmit={(event) => {
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(event.currentTarget));
      if (fields.name.trim()) onSave({ ...fields, name: fields.name.trim(), image }, event.nativeEvent.submitter?.name === "extract");
    }}>
      <section className="admin-card admin-stack">
        <h2>작품 이미지</h2><ImagePicker value={image} onChange={setImage} disabled={!preview} />
      </section>
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
          : '저장하면 작품 ID가 자동 생성되고 Description에서 Unit을 추출합니다.'}</Notice>
        <textarea name="description" className="admin-description" aria-label="원본 Description" defaultValue={record?.description}
          placeholder="작품 Description 원문을 입력하세요." />
        <div className="admin-form-grid">
          <Field label="원문 언어"><select name="language" defaultValue={record?.language ?? ''}>
            <option value="">언어 선택</option><option value="ko">한국어</option><option value="en">영어</option><option value="other">기타</option>
          </select></Field>
          <Field label="제작 연도"><input name="year" defaultValue={record?.year} placeholder="제작 연도 입력" /></Field>
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
  const changed = content.trim() !== unit.content || category !== unit.category;
  const manual = unit.extractionMethod === 'manual';
  return <form className="admin-card admin-stack admin-unit-editor" aria-label="Unit 상세" onSubmit={(event) => {
    event.preventDefault();
    if (content.trim()) onSave({ ...unit, content: content.trim(), category, status: changed ? statuses[0] : statuses[1] });
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
    <div className="admin-dialog-actions"><Button tone="danger" onClick={() => onDelete(unit)}>삭제</Button>
      <Button type="submit" disabled={!content.trim() || (!changed && unit.status !== statuses[0])}>{changed ? '저장' : '검수 완료'}</Button></div>
  </form>;
}

function Status({ unit }) {
  return <span className={'admin-badge ' + (unit.status === statuses[0] ? 'pending' : 'approved')}>{unit.status}</span>;
}

function UnitReview({ artwork, artworks, units, onAdd, onSave, onDelete, onPublish, onReviewSelected }) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [categoryDialog, setCategoryDialog] = useState(false);
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [reviewResult, setReviewResult] = useState(null);
  const visible = units.filter((unit) => (!filter || unit.status === filter)
    && (!categoryFilter || unit.category === categoryFilter));
  const selected = visible.find((unit) => unit.id === selectedId);
  const reviewable = visible.filter((unit) => unit.status === statuses[0]);
  const checked = reviewable.filter((unit) => checkedIds.has(unit.id));
  const allChecked = reviewable.length > 0 && checked.length === reviewable.length;

  async function reviewChecked() {
    setReviewResult(null);
    const result = await onReviewSelected(checked.map((unit) => unit.id));
    if (result) {
      setCheckedIds(new Set());
      setReviewResult(result);
    }
  }

  return <>
    <Heading label="CONTENT UNITS / 작품별 결과" title="Content Unit 검수">
      <Button disabled={!units.some((unit) => unit.status === statuses[1])} onClick={onPublish}>검수 완료 Unit 게시</Button>
    </Heading>
    <div className="admin-review-filters">
      <select className="admin-review-artwork" aria-label="작품 선택" value={artwork.id}
        onChange={(event) => navigate(adminUrl('unit-review', { id: event.target.value }))}>
        {artworks.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
      </select>
      <div className="admin-review-statuses" role="group" aria-label="검수 상태 필터">
        {['', ...statuses].map((status) => <Button key={status} tone="secondary" aria-pressed={filter === status}
          onClick={() => { setFilter(status); setSelectedId(null); setCheckedIds(new Set()); }}>{status || '전체'}</Button>)}
      </div>
      <Button tone="secondary" className="admin-review-category" aria-haspopup="dialog" aria-expanded={categoryDialog}
        onClick={() => setCategoryDialog(true)}>{categoryFilter || '전체 카테고리'}</Button>
      <Button tone="secondary" onClick={onAdd}>+ 수동 추가</Button>
    </div>
    <section className="admin-card admin-review-source" aria-label="원본 Description">
      <div className="admin-section-heading"><h2>원본 Description</h2>
        <Button tone="ghost" to={adminUrl('artwork-edit', { id: artwork.id })}>작품 상세로</Button></div>
      <p className="admin-source">{artwork.description || '저장된 원본 Description이 없습니다.'}</p>
    </section>
    <div className={'admin-review-grid' + (selected ? ' has-selection' : '')}>
      <section className="admin-card admin-review-list" aria-label="Content Unit 목록">
        <header><h2>Content Units</h2><small>작품에 연결된 Unit과 WHAT 분류 결과입니다.</small></header>
        <div className="admin-review-selection">
          <label>
            <input type="checkbox" checked={allChecked} disabled={!reviewable.length}
              ref={(input) => { if (input) input.indeterminate = checked.length > 0 && !allChecked; }}
              onChange={(event) => setCheckedIds(new Set(event.target.checked ? reviewable.map((unit) => unit.id) : []))} />
            전체 선택
          </label>
          <span aria-live="polite">{checked.length}개 선택</span>
          <Button disabled={!checked.length} onClick={reviewChecked}>선택 항목 검수 완료</Button>
        </div>
        {reviewResult && <p className={reviewResult.failed || reviewResult.refreshFailed ? 'admin-notice error' : 'admin-notice'} role="status">
          검수 완료 {reviewResult.reviewed}건 · 실패 {reviewResult.failed}건
          {reviewResult.refreshFailed && ' · 최신 목록을 불러오지 못했습니다.'}
        </p>}
        {visible.map((unit) => <div key={unit.id} className="admin-review-row">
          <input type="checkbox" aria-label={unit.label + ' 검수 선택'} disabled={unit.status !== statuses[0]}
            checked={unit.status === statuses[0] && checkedIds.has(unit.id)}
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
            onClick={() => setSelectedId((current) => current === unit.id ? null : unit.id)}>
            <span className="admin-section-heading"><strong className="admin-unit-list-code">{unit.label}</strong><Status unit={unit} /></span>
            <span className="admin-source">{unit.content}</span><strong className="admin-category">{unit.category}</strong>
          </button>
        </div>)}
        {!visible.length && <p className="admin-muted">{units.length ? '선택한 조건의 Unit이 없습니다.' : '등록된 Content Unit이 없습니다.'}</p>}
      </section>
      {selected && <UnitEditor key={JSON.stringify(selected)} unit={selected} onSave={onSave} onDelete={onDelete} />}
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
  const [extractionFailedId, setExtractionFailedId] = useState(null);
  const saving = useRef(false);
  const requestedView = params.get('view');
  const view = requestedView && requestedView !== 'login' ? requestedView : 'dashboard';
  const id = params.get('id');
  const needsOverview = view === 'dashboard' || view === 'artworks' || view === 'units';
  const currentReviewUnits = (preview ? units : reviewUnits).filter((unit) => unit.artworkId === id);
  const exhibition = exhibitions.find((record) => record.id === id);
  const artwork = artworks.find((record) => record.id === id);
  const section = { exhibition: 'exhibitions', 'artwork-new': 'artworks', 'artwork-edit': 'artworks', 'unit-review': 'units' }[view] ?? view;
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

  function saveExhibition(values) {
    perform(async () => {
      const record = preview
        ? { ...modal.record, ...values, id: modal.record?.id ?? crypto.randomUUID(), updated: updated() }
        : await call('saveExhibition', { ...values, id: modal.record?.id });
      setExhibitions((current) => mergeRecord(current, record));
      navigate(adminUrl('exhibition', { id: record.id }));
    });
  }

  async function saveArtworkOrder(expected, order) {
    if (!preview) await call('saveArtworkOrder', id, expected, order);
    setExhibitions((current) => current.map((record) =>
      record.id === id ? { ...record, artworkOrder: order } : record));
  }

  function saveArtwork(values, extract) {
    if (extract && (preview || !values.description.trim())) {
      if (!preview) setError('Unit을 추출하려면 Description을 입력해 주세요.');
      return;
    }
    perform(async () => {
      const record = preview
        ? { ...values, id: artwork?.id ?? crypto.randomUUID(), updated: updated() }
        : await call('saveArtwork', { ...values, id: artwork?.id });
      setArtworks((current) => mergeRecord(current, record));
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
      navigate(adminUrl('artworks'));
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

  function editUnit(input) {
    perform(async () => {
      const record = preview ? input : await call(
        input.status === statuses[1] ? 'reviewUnit' : 'saveUnit', input,
      );
      updateUnits((current) => mergeRecord(current, record));
    });
  }

  async function reviewSelectedUnits(selectedIds) {
    if (saving.current) return;
    const selected = new Set(selectedIds);
    const targets = currentReviewUnits.filter((unit) => unit.status === statuses[0] && selected.has(unit.id));
    if (!targets.length) return;

    saving.current = true;
    setBusy(true);
    const records = [];
    let refreshFailed = false;
    try {
      for (const unit of targets) {
        try {
          const record = preview ? { ...unit, status: statuses[1] } : await call('reviewUnit', unit);
          records.push(record);
        } catch {
          // Continue processing the other selected Units after a conflict or request failure.
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
      return { reviewed: records.length, failed: targets.length - records.length, refreshFailed };
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
        ? units.filter((item) => item.artworkId === id && item.status === statuses[1]).map((item) => ({ ...item, status: statuses[2] }))
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
  else if (view === 'dashboard') content = <Dashboard {...{ exhibitions, artworks, units }} onAdd={addExhibition} />;
  else if (Object.hasOwn(listings, view)) content = <Listing key={view} {...{ view, exhibitions, artworks, units }} onAdd={addExhibition} />;
  else if (view === 'exhibition' && exhibition) content = <ExhibitionDetail record={exhibition} preview={preview}
    artworks={artworks.filter((item) => item.exhibitionId === id)}
    onSaveOrder={saveArtworkOrder}
    onEdit={() => open({ kind: 'exhibition', record: exhibition })}
    onDelete={deleteExhibition} onPublish={setVisibility} />;
  else if (view === 'artwork-new' || (view === 'artwork-edit' && artwork)) content = <ArtworkForm
    key={view === 'artwork-edit' ? artwork.id : params.get('exhibition') ?? view} record={view === 'artwork-edit' ? artwork : undefined}
    exhibition={params.get('exhibition')} exhibitions={exhibitions} preview={preview}
    onSave={saveArtwork} onDelete={deleteArtwork}
    extracting={extracting} extractionFailed={Boolean(artwork && artwork.id === extractionFailedId)} />;
  else if (view === 'unit-review' && artwork) content = <ReviewPage key={id} {...{ artwork, artworks }}
    {...(!preview && { call, onLoad: setReviewUnits })}
    units={currentReviewUnits}
    onAdd={() => open({ kind: 'unit', artworkId: id })}
    onSave={editUnit}
    onReviewSelected={reviewSelectedUnits}
    onDelete={(target) => confirm('Content Unit 삭제 확인', '선택한 Unit을 삭제할까요?', async () => {
      if (!preview) await call('deleteUnit', target.id);
      updateUnits((current) => current.filter((unit) => unit.id !== target.id));
    })}
    onPublish={publishUnits} />;
  else content = <div className="admin-card admin-stack"><h1>화면을 찾을 수 없습니다</h1>
    <Button to={adminUrl(Object.hasOwn(screens, section) ? section : 'dashboard')}>목록으로 이동</Button></div>;

  const displayName = preview ? '미리보기' : user.display_name;
  return <div className="admin admin-workspace" aria-busy={busy}>
    <aside className="admin-sidebar" inert={busy}>
      <div><Brand />
        <div className="admin-workspace-label"><small>CURATOR WORKSPACE</small><strong>{preview ? '로컬 미리보기' : '전시 관리자'}</strong></div>
        <nav aria-label="관리자 메뉴">{Object.entries(screens).map(([key, [label]]) =>
          <Link key={key} to={adminUrl(key)} aria-current={key === section ? 'page' : false}
            className={key === section ? 'selected' : ''} onClick={() => setError('')}>{label}</Link>)}</nav>
      </div>
      <div className="admin-sidebar-footer">
        <div className="admin-account"><span aria-hidden="true">U</span><div><strong>{displayName}</strong><small>{preview ? '로컬 데이터' : '관리자 계정'}</small></div></div>
        {preview ? <Button tone="ghost" to="/admin">실제 관리자 화면으로</Button>
          : <Button tone="ghost" onClick={() => perform(onLogout)}>로그아웃</Button>}
      </div>
    </aside>
    <div className="admin-main" inert={busy}>
      <header className="admin-topbar"><span>워크스페이스 / 전시 콘텐츠 관리</span>
        {preview && <span>로컬 미리보기 · 새로고침하면 입력 내용이 초기화됩니다</span>}</header>
      <main className="admin-page">{error && !modal && <Notice error>{error}</Notice>}{content}</main>
    </div>
    {modal?.kind === 'exhibition' && <ExhibitionForm record={modal.record} onSave={saveExhibition} onClose={close}
      preview={preview} busy={busy} error={error} />}
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
