import { useEffect, useRef, useState } from 'react';

const categories = ['VISUAL', 'MEANING', 'TECHNIQUE', 'BACKGROUND'];
const levels = [['Basic', 'Basic · 쉬운 설명'], ['Advanced', 'Advanced · 심화 설명']];
const labels = { pending: '검수 대기', reviewed: '검수 완료', published: '게시됨' };
const button = 'admin-button';
const secondary = button + ' secondary';
const emptyPool = { questions: [], units: [] };

function reviewIssues(question, units, publish = false) {
  const issues = levels.filter(([level]) => !question.answers_by_how[level]?.trim()).map(([level]) => level + ' 답변이 필요합니다.');
  if (!question.related_unit_ids.length) issues.push('연결된 Content Unit이 필요합니다.');
  for (const id of question.related_unit_ids) {
    const unit = units.get(id);
    if (!unit) issues.push('삭제된 Content Unit의 연결을 수정하세요.');
    else if (unit.status === 'pending' || (publish && unit.status !== 'published')) {
      issues.push('UNIT-' + String(unit.number).padStart(3, '0') + (publish ? ' 게시가 필요합니다.' : ' 검수가 필요합니다.'));
    }
  }
  return issues;
}

function QuestionStatus({ question }) {
  const tone = { pending: 'pending', reviewed: 'approved', published: 'published' }[question.review_status];
  return <span className={'admin-badge ' + tone}>{labels[question.review_status]}</span>;
}

function FollowupEditor({ question, number, units, unitMap, onSave, onReview, onRegenerate, onDelete, busy, Modal }) {
  const [draft, setDraft] = useState(question);
  const [selectedUnits, setSelectedUnits] = useState(question.related_unit_ids);
  const [editingUnits, setEditingUnits] = useState(false);
  const [unitSelection, setUnitSelection] = useState([]);
  const change = (field, value) => setDraft((current) => ({ ...current, [field]: value }));
  const pendingDraft = { ...draft, related_unit_ids: selectedUnits };
  const publishIssues = reviewIssues(pendingDraft, unitMap, true);
  const changed = draft !== question || JSON.stringify(selectedUnits) !== JSON.stringify(question.related_unit_ids);
  const missing = selectedUnits.some((id) => !unitMap.has(id));
  return <form className="admin-card admin-stack admin-unit-editor admin-followup-editor" onSubmit={(event) => {
    event.preventDefault();
    const answers = Object.fromEntries(Object.entries(draft.answers_by_how).filter(([, answer]) => answer.trim()));
    onSave(event.nativeEvent.submitter?.value || 'save', { question: draft.question, category: draft.category, priority: draft.priority,
      updated_at: question.updated_at, answers_by_how: answers, related_unit_ids: selectedUnits });
  }}>
    <div className="admin-section-heading"><h2>{number}</h2><QuestionStatus question={question} /></div>
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
        <textarea maxLength={1600} value={draft.answers_by_how[level] ?? ''}
          onChange={(event) => change('answers_by_how', { ...draft.answers_by_how, [level]: event.target.value })} />
      </label>)}
    </div>
    <div className="admin-followup-evidence">
      <div className="admin-section-heading"><strong>연결된 Content Unit</strong>
        <button className={secondary} type="button" disabled={Boolean(busy)} onClick={() => {
          setUnitSelection(selectedUnits);
          setEditingUnits(true);
        }}>연결 수정</button>
      </div>
      {selectedUnits.map((id) => {
        const unit = unitMap.get(id);
        return unit ? <div className="admin-stack" key={id}>
          <div className="admin-section-heading"><strong>UNIT-{String(unit.number).padStart(3, '0')} · {unit.category}</strong>
            <span className="admin-badge">{labels[unit.status]}</span></div>
          <p>{unit.content}</p>
        </div> : <p key={id}>삭제된 Unit</p>;
      })}
    </div>
    {question.needs_recheck && <p className="admin-blue">근거가 변경되어 재검수가 필요합니다.</p>}
    {publishIssues.length > 0 && <div className="admin-notice error">
      <strong>게시 조건</strong><ul>{publishIssues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
    </div>}
    <div className="admin-dialog-actions admin-editor-actions">
      <button type="button" className={button + ' danger'} disabled={Boolean(busy)} onClick={onDelete}>삭제</button>
      <button type="button" className={secondary} disabled={Boolean(busy)} onClick={onRegenerate}>답변 재생성</button>
      {question.review_status === 'published' && <button type="button" className={secondary} disabled={Boolean(busy)}
        onClick={() => onReview('pending')}>게시 해제</button>}
      {question.review_status === 'reviewed' && <button type="button" className={secondary} disabled={Boolean(busy)}
        onClick={() => onReview('pending')}>검수 대기로 변경</button>}
      {question.review_status === 'pending' && <button type="button" className={secondary}
        disabled={Boolean(busy) || changed || reviewIssues(question, unitMap).length > 0}
        onClick={() => onReview('reviewed')}>검수 완료</button>}
      <button className={secondary} disabled={Boolean(busy) || !changed || !selectedUnits.length || missing} type="submit" value="save">수정사항 저장</button>
      {(question.review_status !== 'published' || changed) &&
        <button className={button} disabled={Boolean(busy) || publishIssues.length > 0} type="submit" value="publish">검수 완료 및 게시</button>}
    </div>
    {editingUnits && <Modal title="연결된 Unit 수정" onClose={() => setEditingUnits(false)}>
      <fieldset className="admin-followup-evidence">
        <legend>연결할 Content Unit</legend>
        {unitSelection.filter((id) => !unitMap.has(id)).map((id) => <label key={id}>
          <input type="checkbox" checked onChange={() => setUnitSelection(unitSelection.filter((unitId) => id !== unitId))} /> 삭제된 Unit
        </label>)}
        {units.map((unit) => <label key={unit.id}>
          <input type="checkbox" checked={unitSelection.includes(unit.id)}
            disabled={unitSelection.length >= 8 && !unitSelection.includes(unit.id)}
            onChange={(event) => setUnitSelection(event.target.checked
              ? [...unitSelection, unit.id] : unitSelection.filter((id) => id !== unit.id))} />
          <span><strong>UNIT-{String(unit.number).padStart(3, '0')} · {unit.category}</strong> · {labels[unit.status]}<br />{unit.content}</span>
        </label>)}
      </fieldset>
      <div className="admin-dialog-actions">
        <button className={secondary} type="button" onClick={() => setEditingUnits(false)}>취소</button>
        <button className={button} type="button" disabled={!unitSelection.length} onClick={() => {
          setSelectedUnits(unitSelection);
          setEditingUnits(false);
        }}>적용</button>
      </div>
    </Modal>}
  </form>;
}

export default function FollowupQuestions({ artworkId, call, Modal }) {
  const [pool, setPool] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [open, setOpen] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [regenerateCategory, setRegenerateCategory] = useState('');
  const [confirmation, setConfirmation] = useState(null);
  const running = useRef(false);
  const { questions, units } = pool ?? emptyPool;
  const unitMap = new Map(units.map((unit) => [unit.id, unit]));
  const numbers = new Map(questions.map(({ id }, index) => [id, 'Q-' + String(index + 1).padStart(3, '0')]));
  const visible = questions.filter((question) => (!statusFilter || question.review_status === statusFilter) &&
    (!categoryFilter || question.category === categoryFilter));
  const current = visible.find(({ id }) => id === open) ?? visible[0];
  const checkable = visible.filter(({ review_status }) => review_status !== 'published');
  const checked = checkable.filter(({ id }) => selected.has(id));
  const pending = checked.filter(({ review_status }) => review_status === 'pending');

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
      if (feedback) setMessage(feedback);
      setPool(await call('getFollowups', artworkId));
      setSelected(new Set());
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
      return result.generated ? result.generated + '개 질문의 생성 또는 답변 저장을 완료했습니다.' : '추가할 질문이나 답변이 없습니다.';
    });
  }

  function changeStatus(status, question) {
    run('검수 상태 저장 중…', async () => {
      await call('reviewFollowups', artworkId, status, [question]);
      return '질문을 ' + labels[status] + ' 상태로 저장했습니다.';
    });
  }

  function reviewSelected(publish) {
    run('선택한 질문을 처리하는 중…', async () => {
      const targets = publish ? checked : pending;
      const failures = [];
      for (const question of targets) {
        try {
          const issues = reviewIssues(question, unitMap, publish);
          if (issues.length) throw new Error(issues.join(' '));
          if (publish) await call('publishWorkspaceFollowup', artworkId, question);
          else await call('reviewFollowups', artworkId, 'reviewed', [question]);
        } catch (failure) {
          failures.push(numbers.get(question.id) + ' · ' + failure.message);
        }
      }
      if (failures.length) setError(failures.join(' / '));
      return (publish ? '게시' : '검수 완료') + ' ' + (targets.length - failures.length) + '건 · 실패 ' + failures.length + '건';
    });
  }

  function saveCurrent(action, values) {
    run('질문 저장 중…', async () => {
      if (action === 'publish') {
        await call('publishWorkspaceFollowup', artworkId, current, values);
        return '질문과 답변을 검수하고 게시했습니다.';
      }
      await call('saveFollowup', artworkId, current.id, values);
      return '질문과 답변을 저장했습니다.';
    });
  }

  function confirmRegeneration(options, title, text) {
    setConfirmation({ title, text, action: () => generate({ ...options, replace: true }) });
  }

  function changeFilter(update, value) {
    update(value);
    setOpen(null);
    setSelected(new Set());
  }

  return <>
    <div className="admin-dialog-actions admin-followup-toolbar">
      <button type="button" className={secondary} disabled={Boolean(busy)}
        onClick={() => run('후속 질문 불러오는 중…', async () => {})}>새로고침</button>
      <select value={regenerateCategory} aria-label="재생성할 카테고리" disabled={Boolean(busy)}
        onChange={(event) => setRegenerateCategory(event.target.value)}>
        <option value="">재생성할 카테고리</option>
        {categories.filter((category) => units.some((unit) => unit.category === category && unit.status !== 'pending'))
          .map((category) => <option key={category}>{category}</option>)}
      </select>
      <button className={secondary} type="button" disabled={Boolean(busy) || !regenerateCategory}
        onClick={() => confirmRegeneration({ category: regenerateCategory }, regenerateCategory + ' 질문 재생성',
          '해당 카테고리의 기존 질문과 답변을 새 결과로 교체하고 검수 대기로 저장합니다.')}>카테고리 재생성</button>
      <button type="button" className={button} disabled={!pool || Boolean(busy) || !units.some((unit) => unit.status !== 'pending')}
        onClick={() => generate({})}>질문 및 답변 생성</button>
    </div>
    {busy && <p className="admin-notice" role="status">{busy}</p>}
    {message && <p className="admin-notice" role="status">{message}</p>}
    {error && !confirmation && <p className="admin-notice error" role="alert">{error}</p>}
    {!pool && !error && !busy && <p role="status">후속 질문을 불러오는 중…</p>}
    {pool && <div className="admin-review-grid">
      <section className="admin-card admin-review-list" aria-label="Follow-up Questions 목록">
        <h2>전체 질문 {questions.length}개</h2>
        <div className="admin-review-filters">
          <div className="admin-review-statuses" role="group" aria-label="검수 상태 필터">
            {Object.entries({ '': '전체', ...labels }).map(([status, label]) =>
              <button className={secondary} type="button" key={status} aria-pressed={statusFilter === status}
                onClick={() => changeFilter(setStatusFilter, status)}>{label}</button>)}
          </div>
          <select aria-label="카테고리 필터" value={categoryFilter} onChange={(event) => changeFilter(setCategoryFilter, event.target.value)}>
            <option value="">전체 카테고리</option>
            {categories.map((category) => <option key={category}>{category}</option>)}
          </select>
        </div>
        <div className="admin-review-selection">
          <small>{checked.length}개 선택</small>
          <button type="button" className={secondary} disabled={Boolean(busy) || checked.length === checkable.length}
            onClick={() => setSelected(new Set(checkable.map(({ id }) => id)))}>전체 선택</button>
          <button type="button" className={secondary} disabled={Boolean(busy) || !checked.length}
            onClick={() => setSelected(new Set())}>선택 해제</button>
          {checked.length > 0 && <>
            <button type="button" className={secondary} disabled={Boolean(busy) || !pending.length}
              onClick={() => reviewSelected(false)}>선택 검수 완료</button>
            <button type="button" className={button} disabled={Boolean(busy)} onClick={() => reviewSelected(true)}>선택 검수 완료 및 게시</button>
          </>}
        </div>
        <div className="admin-review-results">
          {categories.map((category) => {
            const group = visible.filter((question) => question.category === category);
            if (!group.length) return null;
            return <section key={category} className="admin-followup-group" aria-label={category}>
              <strong>{category} · {group.length}</strong>
              {group.map((question) => <div className="admin-question-row" key={question.id}
                data-selected={current?.id === question.id}>
                <input type="checkbox" aria-label={numbers.get(question.id) + ' 검수 선택'}
                  checked={selected.has(question.id) && question.review_status !== 'published'}
                  disabled={Boolean(busy) || question.review_status === 'published'} onChange={(event) => {
                    const next = new Set(selected);
                    if (event.target.checked) next.add(question.id);
                    else next.delete(question.id);
                    setSelected(next);
                  }} />
                <button type="button" aria-pressed={current?.id === question.id} onClick={() => setOpen(question.id)}>
                  <span><small>{numbers.get(question.id)} · 우선순위 {question.priority}</small><strong>{question.question}</strong></span>
                  <QuestionStatus question={question} />
                </button>
              </div>)}
            </section>;
          })}
          {!visible.length && <p className="admin-muted">{questions.length ? '선택한 조건의 질문이 없습니다.' : '등록된 질문이 없습니다.'}</p>}
        </div>
      </section>
      {current ? <FollowupEditor key={current.id + current.updated_at} question={current} number={numbers.get(current.id)}
        {...{ units, unitMap, busy, Modal }} onSave={saveCurrent} onReview={(status) => changeStatus(status, current)}
        onRegenerate={() => confirmRegeneration({ question_id: current.id }, '답변 재생성', '기존 HOW별 답변을 교체하고 검수 대기로 변경합니다.')}
        onDelete={() => setConfirmation({
          title: '후속 질문 삭제', text: current.question,
          action: () => run('질문 삭제 중…', async () => {
            await call('deleteFollowup', artworkId, current);
            return '질문을 삭제했습니다.';
          }),
        })} /> : <div className="admin-card admin-unit-editor"><p className="admin-muted">선택할 질문이 없습니다.</p></div>}
    </div>}
    {confirmation && <Modal title={confirmation.title} onClose={() => { if (!busy) { setError(''); setConfirmation(null); } }}>
      <p>{confirmation.text}</p>
      {busy && <p role="status">{busy}</p>}
      {error && <p className="admin-notice error" role="alert">{error}</p>}
      <div className="admin-dialog-actions">
        <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => { setError(''); setConfirmation(null); }}>취소</button>
        <button type="button" className={button} disabled={Boolean(busy)} onClick={confirmation.action}>확인</button>
      </div>
    </Modal>}
  </>;
}
