import { useEffect, useRef, useState } from 'react';

const promptKinds = [
  ['extraction', 'Unit Extraction Prompt'],
  ['classification', 'WHAT Classification Prompt'],
  ['followup', 'Follow-up Question & Answer Generation Prompt'],
];
const showVersion = (version) => version == null ? '미저장 초안' : 'v' + version;
const describeRun = (run) => new Date(run.created_at).toLocaleString('ko-KR')
  + ' · ' + showVersion(run.extraction_prompt_version) + ' / ' + showVersion(run.classification_prompt_version);

function MissingPrompt({ title, versions, busy, onActivate }) {
  const [selection, setSelection] = useState('');
  return <section className="admin-card admin-stack">
    <div className="admin-section-heading"><h2>{title}</h2><span className="admin-badge pending">활성 버전 없음</span></div>
    {versions.length ? <>
      <label className="admin-field"><span>활성화할 기존 버전</span>
        <select value={selection} onChange={(event) => setSelection(event.target.value)} disabled={busy}>
          <option value="">버전 선택</option>
          {versions.map(({ version }) => <option key={version} value={version}>v{version}</option>)}
        </select>
      </label>
      <button type="button" className="admin-button" disabled={busy || !selection}
        onClick={() => onActivate(Number(selection))}>선택한 버전 활성화</button>
    </> : <>
      <p>저장된 버전이 없습니다. 이 프로젝트의 초기 프롬프트를 v1으로 설정할 수 있습니다.</p>
      <button type="button" className="admin-button" disabled={busy} onClick={() => onActivate(null)}>프로젝트 기본 프롬프트 설정</button>
    </>}
  </section>;
}

function PromptEditor({ kind, title, active, versions, draft, busy, onDraft, onSave, onRestore }) {
  const [selected, setSelected] = useState('');
  const historical = versions.find((version) => String(version.version) === selected);
  return <section className="admin-card admin-stack">
    <div className="admin-section-heading"><h2>{title}</h2><span className="admin-badge">활성 v{active.version}</span></div>
    <label className="admin-field"><span>프롬프트</span>
      <textarea className="admin-description" rows={8} value={draft.body} maxLength={12000}
        onChange={(event) => onDraft(kind, { ...draft, body: event.target.value })} disabled={busy} />
    </label>
    <div className="admin-actions">
      <button className="admin-button" type="button" disabled={busy || !draft.body.trim() || draft.body.trim() === active.body}
        onClick={() => onSave(kind)}>새 버전 저장</button>
      <button className="admin-button secondary" type="button" disabled={busy} onClick={() => onDraft(kind, active)}>활성 버전 불러오기</button>
    </div>
    <label className="admin-field"><span>이전 버전</span>
      <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={busy}>
        <option value="">버전 선택</option>
        {versions.map((version) => <option key={version.version} value={version.version}>
          v{version.version}{version.version === active.version ? ' (활성)' : ''}
        </option>)}
      </select>
    </label>
    <div className="admin-actions">
      <button className="admin-button secondary" type="button" disabled={busy || !historical}
        onClick={() => onDraft(kind, { version: historical.version, body: historical.body.trim() })}>편집기에 불러오기</button>
      <button className="admin-button secondary" type="button" disabled={busy || !historical || historical.version === active.version}
        onClick={() => onRestore(kind, historical)}>활성 버전으로 복원</button>
    </div>
  </section>;
}

function RunResult({ run }) {
  if (!run) return <p className="admin-muted">비교할 테스트를 선택하세요.</p>;
  const classifications = new Map(run.classification_result.map((unit) => [unit.index, unit]));
  return <div className="admin-stack">
    <p className="admin-muted">Unit {run.extraction_result.length}개 · {run.extraction_model} / {run.classification_model}</p>
    <details><summary>테스트 Description 및 프롬프트</summary>
      <p className="admin-source">{run.description}</p>
      <h2>추출 · {showVersion(run.extraction_prompt_version)}</h2><p className="admin-source">{run.extraction_prompt}</p>
      <h2>분류 · {showVersion(run.classification_prompt_version)}</h2><p className="admin-source">{run.classification_prompt}</p>
    </details>
    {run.extraction_result.map((unit, index) => {
      const result = classifications.get(index);
      return <article key={index} className="admin-card admin-stack compact">
        <div className="admin-section-heading"><strong>{result?.category}</strong>
          <small>{[result?.needs_split && '분리 필요', result?.needs_review && '검수 필요'].filter(Boolean).join(' · ')}</small>
        </div>
        <p className="admin-source">{unit.content}</p>
        {result?.rationale && <p className="admin-muted">{result.rationale}</p>}
        <ul className="admin-record-list">{unit.evidence.map((quote, position) => <li key={position}>{quote}</li>)}</ul>
      </article>;
    })}
  </div>;
}

function FollowupPromptTest({ call, artworks, draft }) {
  const [artworkId, setArtworkId] = useState('');
  const [result, setResult] = useState(null);
  const [sources, setSources] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const units = sources?.artworkId === artworkId ? sources.units : [];
  useEffect(() => {
    if (!artworkId) return;
    const controller = new AbortController();
    call('getFollowups', artworkId, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      const eligible = data.units.filter((unit) => unit.status !== 'pending');
      setSources({ artworkId, units: eligible });
      setSelected(new Set(eligible.map((unit) => unit.id)));
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(failure.message);
    });
    return () => controller.abort();
  }, [artworkId, call]);

  async function run(event) {
    event.preventDefault();
    const unitIds = units.filter(({ id }) => selected.has(id)).map(({ id }) => id);
    if (busy || !unitIds.length) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await call('runFollowupTest', {
        artwork_id: artworkId, unit_ids: unitIds, body: draft.body, version: draft.version,
      }));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="admin-card admin-stack">
    <h2>후속 질문 및 답변 프롬프트 테스트</h2>
    <small>현재 편집기의 프롬프트로 실행합니다. 결과는 작품의 질문 목록에 저장되지 않습니다.</small>
    <form className="admin-stack" onSubmit={run}>
      <label className="admin-field">작품 선택<select value={artworkId} disabled={busy} onChange={(event) => {
        setArtworkId(event.target.value);
        setError('');
        setResult(null);
      }}>
        <option value="">작품을 선택하세요</option>
        {artworks.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
      </select></label>
      {artworkId && sources?.artworkId === artworkId && (!units.length ? <p>검수된 Content Unit이 없습니다.</p> :
        <fieldset className="admin-followup-evidence">
          <legend>테스트에 사용할 Content Unit</legend>
          {units.map((unit) => <label key={unit.id}>
            <input type="checkbox" disabled={busy} checked={selected.has(unit.id)} onChange={(event) => {
              const next = new Set(selected);
              if (event.target.checked) next.add(unit.id);
              else next.delete(unit.id);
              setSelected(next);
            }} /><span>UNIT-{unit.number} · {unit.category}<br />{unit.content}</span>
          </label>)}
        </fieldset>)}
      <div className="admin-actions"><button className="admin-button" type="submit"
        disabled={busy || !units.length || !selected.size || !draft.body.trim()}>{busy ? '테스트 실행 중…' : '테스트 실행'}</button></div>
    </form>
    {error && <p className="admin-notice error" role="alert">{error}</p>}
    {result && <div className="admin-stack">
      <p><strong>{result.artwork.name}</strong> · {showVersion(result.version)} · {result.model}</p>
      <details><summary>사용한 Content Unit {result.units.length}개</summary>
        <ul className="admin-record-list">{result.units.map((unit) => <li key={unit.id}>UNIT-{unit.number} · {unit.content}</li>)}</ul>
      </details>
      {!result.questions.length && <p>선택한 근거로 생성된 질문이 없습니다.</p>}
      {result.questions.map((item) => <article className="admin-card admin-stack compact" key={item.question}>
        <h2>{item.question}</h2>
        <small>{item.category} · 우선순위 {item.priority} · {item.related_unit_ids.map((id) =>
          'UNIT-' + result.units.find((unit) => unit.id === id)?.number).join(', ')}</small>
        <div className="admin-form-grid">
          {['Basic', 'Advanced'].map((level) => <div key={level}><strong>{level}</strong><p className="admin-source">{item.answers_by_how[level]}</p></div>)}
        </div>
      </article>)}
    </div>}
  </section>;
}

export default function AiSettings({ call, artworks }) {
  const [active, setActive] = useState(null);
  const [drafts, setDrafts] = useState(null);
  const [versions, setVersions] = useState(null);
  const [runs, setRuns] = useState([]);
  const [description, setDescription] = useState('');
  const [leftId, setLeftId] = useState('');
  const [rightId, setRightId] = useState('');
  const [restore, setRestore] = useState(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const pending = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    Promise.all([
      call('activeAiPrompts', signal),
      call('aiPromptVersions', 'extraction', signal),
      call('aiPromptVersions', 'classification', signal),
      call('aiPromptVersions', 'followup', signal),
      call('aiTests', signal),
    ]).then(([prompts, extraction, classification, followup, history]) => {
      if (signal.aborted) return;
      setActive(prompts.active);
      setDrafts(prompts.active);
      setVersions({ extraction, classification, followup });
      setRuns(history);
      setLeftId(history[1]?.id ?? '');
      setRightId(history[0]?.id ?? '');
    }).catch((failure) => {
      if (!signal.aborted) setError(failure.message);
    });
    return () => controller.abort();
  }, [call, reload]);

  async function perform(label, action) {
    if (pending.current) return;
    pending.current = true;
    setBusy(label);
    setError('');
    try {
      await action();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy('');
      pending.current = false;
    }
  }

  function updateDraft(kind, draft) {
    setDrafts((current) => ({ ...current, [kind]: draft }));
  }

  function updatePrompt(kind, body, newBody) {
    perform('프롬프트 저장 중…', async () => {
      const { version } = await call('updateAiPrompt', kind, { expected_version: active[kind].version, ...body });
      const next = { version, body: newBody };
      setActive((current) => ({ ...current, [kind]: next }));
      updateDraft(kind, next);
      setRestore(null);
      if (body.body) setVersions((current) => ({ ...current, [kind]: [next, ...current[kind]] }));
    });
  }

  function activatePrompt(kind, version) {
    perform('프롬프트 활성화 중…', async () => {
      const saved = await call('activateAiPrompt', kind, version);
      const next = { version: saved.version, body: saved.body.trim() };
      setActive((current) => ({ ...current, [kind]: next }));
      updateDraft(kind, next);
      if (version === null) setVersions((current) => ({ ...current, [kind]: [next] }));
    });
  }

  function runTest(event) {
    event.preventDefault();
    perform('추출 및 분류 테스트 중…', async () => {
      const result = await call('runAiTest', {
        description, extraction_body: drafts.extraction.body, classification_body: drafts.classification.body,
        extraction_version: drafts.extraction.version, classification_version: drafts.classification.version,
      });
      setRuns((current) => [result, ...current]);
      setLeftId(runs.find((run) => run.description === result.description)?.id ?? rightId);
      setRightId(result.id);
    });
  }

  const left = runs.find((run) => run.id === leftId);
  const right = runs.find((run) => run.id === rightId);
  return <>
    <div className="admin-heading"><div><h1>AI Settings</h1></div>
      {active && <button className="admin-button secondary" type="button" disabled={Boolean(busy)}
        onClick={() => { setActive(null); setError(''); setReload((value) => value + 1); }}>저장된 설정 다시 불러오기</button>}
    </div>
    {error && <p className="admin-notice error" role="alert">{error}</p>}
    {!active ? error ? <button className="admin-button secondary" type="button" onClick={() => {
      setError(''); setReload((value) => value + 1);
    }}>다시 불러오기</button> : <p role="status">AI 설정을 불러오는 중입니다…</p> : <>
      {busy && <p className="admin-notice" role="status">{busy}</p>}
      <div className="admin-form-grid admin-ai-prompts">
        {promptKinds.filter(([kind]) => kind !== 'followup' || active[kind]).map(([kind, title]) => active[kind] ? <PromptEditor key={kind} {...{ kind, title }}
          active={active[kind]} versions={versions[kind]} draft={drafts[kind]} busy={Boolean(busy)}
          onDraft={updateDraft}
          onSave={() => updatePrompt(kind, { body: drafts[kind].body }, drafts[kind].body.trim())}
          onRestore={(_, version) => setRestore({ kind, version })} />
          : <MissingPrompt key={kind} title={title} versions={versions[kind]} busy={Boolean(busy)}
            onActivate={(version) => activatePrompt(kind, version)} />)}
      </div>
      {drafts.followup ? <FollowupPromptTest call={call} artworks={artworks} draft={drafts.followup} />
        : <p className="admin-notice">후속 질문 설정을 사용하려면 Supabase에 10_followup_questions.sql을 적용해 주세요.</p>}
      {restore && <div className="admin-card admin-stack">
        <p>선택한 v{restore.version.version}을 활성 버전으로 복원할까요?</p>
        <div className="admin-actions">
          <button className="admin-button" type="button" disabled={Boolean(busy)} onClick={() =>
            updatePrompt(restore.kind, { restore_version: restore.version.version }, restore.version.body.trim())}>복원</button>
          <button className="admin-button secondary" type="button" disabled={Boolean(busy)} onClick={() => setRestore(null)}>취소</button>
        </div>
      </div>}
      <form className="admin-card admin-stack" onSubmit={runTest}>
        <h2>프롬프트 테스트</h2>
        <small>테스트 결과는 실제 작품과 Unit에 반영되지 않습니다.</small>
        {artworks.some((artwork) => artwork.description?.trim()) && <label className="admin-field">
          <span>기존 작품 Description 불러오기</span>
          <select value="" disabled={Boolean(busy)} onChange={(event) => {
            const artwork = artworks.find((item) => item.id === event.target.value);
            if (artwork) setDescription(artwork.description);
          }}>
            <option value="">작품 선택</option>
            {artworks.filter((artwork) => artwork.description?.trim()).map((artwork) =>
              <option key={artwork.id} value={artwork.id}>{artwork.name}</option>)}
          </select>
        </label>}
        <label className="admin-field"><span>테스트 Description</span>
          <textarea className="admin-description" value={description} maxLength={100000} required
            onChange={(event) => setDescription(event.target.value)} disabled={Boolean(busy)} />
        </label>
        <div className="admin-actions"><button className="admin-button" type="submit"
          disabled={Boolean(busy) || !description.trim() || !drafts.extraction?.body.trim() || !drafts.classification?.body.trim()}>테스트 실행</button></div>
      </form>
      <section className="admin-card admin-stack">
        <h2>테스트 결과 비교</h2>
        {left && right && left.description !== right.description && <p className="admin-notice">두 테스트의 Description이 다릅니다.</p>}
        <div className="admin-form-grid">
          {[['이전 결과', leftId, setLeftId, left], ['비교 결과', rightId, setRightId, right]].map(([label, id, select, run]) =>
            <div className="admin-stack" key={label}>
              <label className="admin-field"><span>{label}</span>
                <select value={id} onChange={(event) => select(event.target.value)}>
                  <option value="">테스트 선택</option>
                  {runs.map((item) => <option key={item.id} value={item.id}>{describeRun(item)}</option>)}
                </select>
              </label>
              <RunResult run={run} />
            </div>)}
        </div>
      </section>
    </>}
  </>;
}
