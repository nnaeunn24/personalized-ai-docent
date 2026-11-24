import { useEffect, useRef, useState } from 'react';

const categories = ['VISUAL', 'MEANING', 'TECHNIQUE', 'BACKGROUND'];
const levels = [['Basic', 'Basic · 쉬운 설명'], ['Advanced', 'Advanced · 심화 설명']];
const labels = { pending: '검수 대기', reviewed: '검수 완료', published: '게시됨' };
const button = 'admin-button';
const secondary = button + ' secondary';
const emptyPool = { questions: [], units: [] };

function validQuestion(question, units, publish = false) {
  return levels.every(([level]) => question.answers_by_how[level]?.trim()) && question.related_unit_ids.length > 0
    && question.related_unit_ids.every((id) => {
      const status = units.get(id)?.status;
      return status === 'published' || (!publish && status === 'reviewed');
    });
}

function FollowupEditor({ question, units, onSave, busy }) {
  const [draft, setDraft] = useState(question);
  const [selectedUnits, setSelectedUnits] = useState(question.related_unit_ids);
  const change = (field, value) => setDraft((current) => ({ ...current, [field]: value }));
  const missing = selectedUnits.filter((id) => !units.some((unit) => unit.id === id));
  return <form className="admin-stack admin-followup-editor" onSubmit={(event) => {
    event.preventDefault();
    const answers = Object.fromEntries(Object.entries(draft.answers_by_how).filter(([, answer]) => answer.trim()));
    onSave({ question: draft.question, category: draft.category, priority: draft.priority,
      updated_at: question.updated_at, answers_by_how: answers, related_unit_ids: selectedUnits });
  }}>
    <label className="admin-field">질문<textarea required maxLength={300} value={draft.question}
      onChange={(event) => change('question', event.target.value)} /></label>
    <div className="admin-form-grid">
      <label className="admin-field">WHAT 카테고리<select value={draft.category} onChange={(event) => change('category', event.target.value)}>
        {categories.map((category) => <option key={category}>{category}</option>)}
      </select></label>
      <label className="admin-field">우선순위<input type="number" required min={1} max={100} value={draft.priority}
        onChange={(event) => change('priority', event.target.valueAsNumber || '')} /></label>
    </div>
    <div className="admin-form-grid">
      {levels.map(([level, label]) => <label className="admin-field" key={level}>{label}
        <textarea className="admin-description" maxLength={1600} value={draft.answers_by_how[level] ?? ''}
          onChange={(event) => change('answers_by_how', { ...draft.answers_by_how, [level]: event.target.value })} />
      </label>)}
    </div>
    <fieldset className="admin-followup-evidence">
      <legend>연결할 Content Unit</legend>
      {missing.map((id) => <label key={id}>
        <input type="checkbox" checked onChange={() => setSelectedUnits(selectedUnits.filter((unitId) => unitId !== id))} />
        삭제된 Unit · {id}
      </label>)}
      {units.map((unit) => <label key={unit.id}>
        <input type="checkbox" checked={selectedUnits.includes(unit.id)}
          disabled={selectedUnits.length >= 8 && !selectedUnits.includes(unit.id)}
          onChange={(event) => setSelectedUnits(event.target.checked
            ? [...selectedUnits, unit.id] : selectedUnits.filter((id) => id !== unit.id))} />
        <span><strong>UNIT-{String(unit.number).padStart(3, '0')} · {unit.category}</strong> · {labels[unit.status]}<br />{unit.content}</span>
      </label>)}
    </fieldset>
    <p className="admin-muted">질문, 근거, 답변 또는 우선순위를 수정하면 검수 대기로 돌아갑니다.</p>
    <button className={button} disabled={busy || !selectedUnits.length || missing.length > 0} type="submit">질문 및 답변 저장</button>
  </form>;
}

export default function FollowupQuestions({ artworkId, call, Modal }) {
  const [pool, setPool] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [regenerateCategory, setRegenerateCategory] = useState('');
  const [confirmation, setConfirmation] = useState(null);
  const running = useRef(false);
  const { questions, units } = pool ?? emptyPool;
  const unitMap = new Map(units.map((unit) => [unit.id, unit]));
  const pending = questions.filter((question) => question.review_status === 'pending');
  const selectedQuestions = questions.filter(({ id }) => selected.has(id));
  const reviewable = selectedQuestions.filter((question) => question.review_status === 'pending');
  const publishable = selectedQuestions.filter((question) => question.review_status === 'reviewed');

  useEffect(() => {
    const controller = new AbortController();
    call('getFollowups', artworkId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setPool(result);
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(failure.message);
    });
    return () => controller.abort();
  }, [artworkId, call]);

  async function run(label, operation) {
    if (running.current) return;
    running.current = true;
    setBusy(label);
    setError('');
    setMessage('');
    try {
      const feedback = await operation();
      setConfirmation(null);
      setPool(await call('getFollowups', artworkId));
      setSelected(new Set());
      if (feedback) setMessage(feedback);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy('');
      running.current = false;
    }
  }

  function generate(options) {
    return run('질문과 답변 생성 중…', async () => {
      const result = await call('generateFollowups', artworkId, options);
      return result.generated ? `${result.generated}개 질문의 생성 또는 답변 저장을 완료했습니다.`
        : '추가할 질문이나 답변이 없습니다. 기존 질문은 그대로 유지됩니다.';
    });
  }

  function changeStatus(status, items) {
    run('검수 상태 저장 중…', async () => {
      await call('reviewFollowups', artworkId, status, items);
      return `${items.length}개 질문을 ${labels[status]} 상태로 저장했습니다.`;
    });
  }

  return <section className="admin-card admin-stack" aria-labelledby="followup-title">
    <div className="admin-section-heading">
      <h2 id="followup-title">Follow-up Questions</h2>
      <div className="admin-actions">
        <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() =>
          run('후속 질문 불러오는 중…', async () => {})}>새로고침</button>
        <button type="button" className={button} disabled={!pool || Boolean(busy) || !units.some((unit) => unit.status !== 'pending')}
          onClick={() => generate({})}>질문 및 답변 생성</button>
      </div>
    </div>
    {busy && <p className="admin-notice" role="status">{busy}</p>}
    {message && <p className="admin-notice" role="status">{message}</p>}
    {error && !confirmation && <p className="admin-notice error" role="alert">{error}</p>}
    {!pool && !error && !busy && <p role="status">후속 질문을 불러오는 중…</p>}
    {pool && <>
      <p>전체 {questions.length}개 · 검수 대기 {pending.length}개 · 검수 완료 {questions.length - pending.length}개</p>
      {!units.some((unit) => unit.status !== 'pending') && <p className="admin-muted">Content Unit을 검수하면 질문과 답변을 생성할 수 있습니다.</p>}
      <p className="admin-muted">질문을 검수한 후 게시하세요. 게시하려면 연결된 Unit도 게시되어 있어야 합니다.</p>
      <div className="admin-actions">
        <select value={regenerateCategory} aria-label="재생성할 카테고리" disabled={Boolean(busy)}
          onChange={(event) => setRegenerateCategory(event.target.value)}>
          <option value="">재생성할 카테고리 선택</option>
          {categories.filter((category) => units.some((unit) => unit.category === category && unit.status !== 'pending'))
            .map((category) => <option key={category}>{category}</option>)}
        </select>
        <button className={secondary} type="button" disabled={Boolean(busy) || !regenerateCategory}
          onClick={() => setConfirmation({ title: `${regenerateCategory} 질문 재생성`,
            text: '새 결과가 생성되면 이 카테고리의 기존 질문과 답변을 교체합니다. 새 항목은 검수 대기 상태로 저장됩니다.',
            action: () => generate({ category: regenerateCategory, replace: true }) })}>카테고리 재생성</button>
      </div>
      <div className="admin-actions">
        <button type="button" className={secondary} disabled={Boolean(busy) || !questions.length} onClick={() =>
          setSelected(new Set(questions.map(({ id }) => id)))}>전체 선택</button>
        <button type="button" className={secondary} disabled={Boolean(busy) || !selected.size} onClick={() => setSelected(new Set())}>전체 해제</button>
        <button type="button" className={secondary} disabled={Boolean(busy) || !reviewable.length ||
          !reviewable.every((question) => validQuestion(question, unitMap))} onClick={() => changeStatus('reviewed', reviewable)}>
          선택한 {reviewable.length}개 검수 완료
        </button>
        <button type="button" className={button} disabled={Boolean(busy) || !publishable.length ||
          !publishable.every((question) => validQuestion(question, unitMap, true))} onClick={() => changeStatus('published', publishable)}>
          선택한 {publishable.length}개 게시
        </button>
      </div>
      {categories.map((category) => {
        const group = questions.filter((question) => question.category === category);
        return <section className="admin-card admin-stack compact" key={category} aria-label={category}>
          <h2>{category} <small>{group.length}개</small></h2>
          {!group.length && <p className="admin-muted">등록된 질문이 없습니다.</p>}
          {group.map((question) => {
            const canReview = validQuestion(question, unitMap);
            const canPublish = validQuestion(question, unitMap, true);
            return <article className="admin-unit" key={question.id}>
              <div className="admin-section-heading">
                <label className="admin-followup-select"><input type="checkbox" checked={selected.has(question.id)}
                  disabled={Boolean(busy)} onChange={(event) => {
                    const next = new Set(selected);
                    if (event.target.checked) next.add(question.id);
                    else next.delete(question.id);
                    setSelected(next);
                  }} /> <strong>{question.question}</strong></label>
                <span className={`admin-badge ${question.review_status === 'pending' ? 'pending' : 'approved'}`}>{labels[question.review_status]}</span>
              </div>
              <small>우선순위 {question.priority} · 근거 {question.related_unit_ids.map((id) => {
                const unit = unitMap.get(id);
                return unit ? 'UNIT-' + String(unit.number).padStart(3, '0') : '삭제된 Unit';
              }).join(', ')}</small>
              {question.needs_recheck && <p className="admin-blue">근거가 변경되어 재검수가 필요합니다.</p>}
              {!canReview && <p className="admin-muted">두 HOW 답변과 검수된 근거 Unit을 확인하세요.</p>}
              <div className="admin-actions">
                <button type="button" className={secondary} aria-expanded={open === question.id} onClick={() =>
                  setOpen(open === question.id ? null : question.id)}>상세 및 수정</button>
                {question.review_status === 'pending' && <button type="button" className={secondary} disabled={Boolean(busy) || !canReview}
                  onClick={() => changeStatus('reviewed', [question])}>검수 완료</button>}
                {question.review_status === 'reviewed' && <button type="button" className={button} disabled={Boolean(busy) || !canPublish}
                  onClick={() => changeStatus('published', [question])}>게시</button>}
                {question.review_status !== 'pending' && <button type="button" className={secondary} disabled={Boolean(busy)}
                  onClick={() => changeStatus('pending', [question])}>검수 대기로 변경</button>}
                <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => setConfirmation({
                  title: '답변 재생성', text: '기존 HOW별 답변을 교체하고 검수 대기로 변경합니다.',
                  action: () => generate({ question_id: question.id, replace: true }),
                })}>답변 재생성</button>
                <button type="button" className={button + ' danger'} disabled={Boolean(busy)} onClick={() => setConfirmation({
                  title: '후속 질문 삭제', text: question.question,
                  action: () => run('질문 삭제 중…', async () => {
                    await call('deleteFollowup', artworkId, question);
                    return '질문을 삭제했습니다.';
                  }),
                })}>삭제</button>
              </div>
              {open === question.id && <FollowupEditor key={question.updated_at} {...{ question, units, busy }}
                onSave={(values) => run('질문 저장 중…', async () => {
                  await call('saveFollowup', artworkId, question.id, values);
                  return '질문과 답변을 저장했습니다.';
                })} />}
            </article>;
          })}
        </section>;
      })}
    </>}
    {confirmation && <Modal title={confirmation.title} onClose={() => { if (!busy) { setError(''); setConfirmation(null); } }}>
      <p>{confirmation.text}</p>
      {busy && <p role="status">{busy}</p>}
      {error && <p className="admin-notice error" role="alert">{error}</p>}
      <div className="admin-dialog-actions">
        <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => { setError(''); setConfirmation(null); }}>취소</button>
        <button type="button" className={button} disabled={Boolean(busy)} onClick={confirmation.action}>확인</button>
      </div>
    </Modal>}
  </section>;
}
