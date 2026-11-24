import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { askArtworkQuestion, visitorUrl } from './visitorApi';
import { artworkImage } from './visitorImages';
import chatBack from './chat-back.svg';
import chatSubmit from './chat-submit.svg';
import chatLoading from './chat-loading.svg';

const inMemoryHistory = new Map();

function readHistory(key) {
  if (inMemoryHistory.has(key)) return inMemoryHistory.get(key);
  try {
    const saved = JSON.parse(sessionStorage.getItem(key));
    if (Array.isArray(saved)) return saved;
  } catch {
    // Session storage may be unavailable.
  }
  return [];
}

export default function VisitorChat({ data, profile, nextArtwork, suggestedQuestions, suggestionsReady }) {
  const { id: artworkId, name, exhibition } = data;
  const location = useLocation();
  const navigate = useNavigate();
  const selectedQuestionId = location.state?.questionId;
  const focusComposer = location.state?.focusComposer;
  const storageKey = 'docent.visitor.chat.' + JSON.stringify([exhibition.id, artworkId]);
  const [turns, setTurns] = useState(() => readHistory(storageKey));
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const activeRequest = useRef(null);
  const viewport = useRef(null);
  const composer = useRef(null);
  const composing = useRef(false);
  const failedQuestion = turns.at(-1)?.answer === null ? turns.at(-1).question : '';
  const savedAnswerSeen = (id) => turns.some((turn) => turn.questionId === id && turn.how === profile.how);
  const sendSelectedQuestion = useEffectEvent((id) => {
    showSavedAnswer(id);
    navigate(location.pathname + location.search, { replace: true, state: null });
  });

  useEffect(() => () => activeRequest.current?.abort(), []);
  useEffect(() => {
    if (focusComposer) composer.current?.focus();
    if (!suggestionsReady || typeof selectedQuestionId !== 'string') return;
    const timer = window.setTimeout(() => sendSelectedQuestion(selectedQuestionId), 0);
    return () => window.clearTimeout(timer);
  }, [focusComposer, selectedQuestionId, suggestionsReady]);
  useEffect(() => {
    if (turns.length) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [turns, pending, error]);

  function saveTurns(updated) {
    inMemoryHistory.set(storageKey, updated);
    setTurns(updated);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(updated));
    } catch {
      // Keep the conversation in memory when storage is unavailable.
    }
  }

  function showSavedAnswer(questionId) {
    if (activeRequest.current || savedAnswerSeen(questionId)) return;
    const saved = suggestedQuestions.find((item) => item.question_id === questionId);
    if (!saved?.answer) return;
    setError('');
    saveTurns([...turns.filter(({ answer }) => answer !== null), {
      question: saved.question, answer: saved.answer, questionId, how: profile.how,
    }]);
  }

  async function send(question, retry = false) {
    if (!question || activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    const previous = retry ? turns.slice(0, -1) : turns.filter(({ answer }) => answer !== null);
    saveTurns([...previous, { question, answer: null }]);
    if (!retry) setDraft('');
    setError('');
    setPending(true);
    try {
      const history = previous.slice(-6).map(({ question, answer }) => ({ question, answer }));
      const result = await askArtworkQuestion(exhibition.id, artworkId, question, history, controller.signal);
      if (controller.signal.aborted) return;
      saveTurns([...previous, { question, answer: result.answer }]);
      if (import.meta.env.DEV) {
        console.debug('[Visitor questions]', {
          artworkId, answerStatus: result.answer_status,
          retrievedUnitIds: result.retrieved_unit_ids, usedUnitIds: result.used_unit_ids,
        });
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        if (failure.name === 'TimeoutError') setError('답변 생성 시간이 초과되었어요.');
        else if (failure instanceof TypeError) setError('도슨트 서버에 연결할 수 없어요.');
        else setError(failure.message);
      }
    } finally {
      activeRequest.current = null;
      if (!controller.signal.aborted) setPending(false);
    }
  }

  const remainingQuestions = suggestedQuestions.filter(({ question_id }) => !savedAnswerSeen(question_id));
  const suggestions = remainingQuestions.length > 0 && <section
    className="visitor-chat-suggestions visitor-question-options" aria-label="추천 질문">
    {remainingQuestions.map(({ question, question_id }) => <button className="visitor-question-option" type="button" key={question_id}
      disabled={pending} onClick={() => showSavedAnswer(question_id)}>
      {question}<span aria-hidden="true">↗</span>
    </button>)}
  </section>;
  return <div className="visitor-chat" aria-label={name + ' 질문하기'}>
    <header className="visitor-header visitor-header-lined visitor-chat-header">
      <Link className="visitor-icon" to={visitorUrl(exhibition.id, artworkId)} aria-label="작품 감상으로 돌아가기">
        <img src={chatBack} alt="" />
      </Link>
      <p className="visitor-header-title">{exhibition.name}</p>
    </header>
    <div className="visitor-chat-viewport" ref={viewport}>
      <div className="visitor-chat-artwork">
        <div className="visitor-poster visitor-chat-thumbnail">
          {artworkImage(data) && <img src={artworkImage(data)} alt="" />}
        </div>
        <div><h1>{name}</h1><p>{[data.year, data.artist].filter(Boolean).join(' · ')}</p></div>
      </div>
      <div className="visitor-chat-messages" role="log" aria-label="작품 대화 내역">
        {turns.map(({ question, answer }, index) => <div className="visitor-chat-turn" key={index}>
          <p className="visitor-chat-bubble visitor-chat-question" aria-label={'관람객: ' + question}>{question}</p>
          {answer && <p className="visitor-chat-bubble visitor-chat-answer" aria-label={'AI 도슨트: ' + answer}>{answer}</p>}
        </div>)}
        {pending && <div className="visitor-chat-bubble visitor-chat-answer" role="status" aria-label="답변을 만드는 중이에요">
          <img className="visitor-chat-loading" src={chatLoading} alt="" />
        </div>}
        {!pending && failedQuestion && <div className="visitor-chat-error">
          <p role="alert">{error || '이 질문의 답변을 받지 못했어요.'}</p>
          <button className="visitor-button" type="button" onClick={() => send(failedQuestion, true)}>다시 시도</button>
        </div>}
      </div>
      {!!turns.length && !pending && suggestions}
      {nextArtwork && !!turns.length && !pending && !failedQuestion && <div className="visitor-chat-navigation">
        <Link className="visitor-button" to={visitorUrl(exhibition.id, nextArtwork.id)}>다음 작품</Link>
      </div>}
    </div>
    {!turns.length && !selectedQuestionId && suggestions}
    <form className="visitor-chat-composer" onSubmit={(event) => {
      event.preventDefault();
      if (!composing.current) send(draft.trim());
    }}>
      <input ref={composer} aria-label={name + '에 대한 질문'} placeholder="텍스트를 입력하세요" autoComplete="off"
        maxLength={1000} value={draft} onChange={(event) => setDraft(event.target.value)}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (composing.current || event.nativeEvent.isComposing || event.keyCode === 229)) {
            event.preventDefault();
          }
        }} />
      <button type="submit" aria-label="질문 전송" disabled={pending || !draft.trim()}><img src={chatSubmit} alt="" /></button>
    </form>
  </div>;
}
