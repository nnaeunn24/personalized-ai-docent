import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { generateDocent, readSuggestedQuestions, readVisitorCatalog, visitorUrl } from './visitor/visitorApi';
import { rankSuggestedQuestions } from './visitor/followupQuestions';
import VisitorSurvey from './visitor/VisitorSurvey';
import VisitorChat from './visitor/VisitorChat';
import { firstUnanswered, readVisitorProfile, saveVisitorProfile } from './visitor/visitorProfile';
import { artworkImage, exhibitionImage, exhibitionVenue } from './visitor/visitorImages';
import homeSearch from './visitor/home-search.svg';
import exhibitionBack from './visitor/exhibition-back.svg';
import exhibitionSearch from './visitor/exhibition-search.svg';
import searchBack from './visitor/search-back.svg';
import fieldSearch from './visitor/field-search.svg';
import artworkBack from './visitor/artwork-back.svg';
import DocentAudio from './visitor/DocentAudio';
import docentLoading from './visitor/docent-loading.svg';
import './visitor/visitor.css';

const searchUrl = '/visitor?view=search';
const codeUrl = '/visitor?view=code';
const recentSearchKey = 'docent.visitor.recentSearches';

function IconLink({ to, icon, label, back = false }) {
  return <Link className="visitor-icon" to={to} aria-label={label}><img className={back ? "visitor-back-icon" : undefined} src={icon} alt="" /></Link>;
}

function Header({ title, back, artwork = false, search = true }) {
  return <header className={'visitor-header' + (artwork ? ' visitor-header-lined' : '')}>
    {back ? <IconLink to={back} icon={artwork ? artworkBack : exhibitionBack} label="뒤로" back />
      : <Link to="/visitor" className="visitor-brand">docent.</Link>}
    {title && <p className="visitor-header-title">{title}</p>}
    {search && <IconLink to={searchUrl} icon={back ? exhibitionSearch : homeSearch} label="전시 검색" />}
  </header>;
}

function Poster({ className = '', imageUrl, children }) {
  const [failedUrl, setFailedUrl] = useState(null);
  return <div className={'visitor-poster ' + className} aria-hidden="true">
    {imageUrl && imageUrl !== failedUrl
      ? <img src={imageUrl} alt="" onError={() => setFailedUrl(imageUrl)} />
      : children}
  </div>;
}

function ExhibitionHome({ exhibitions }) {
  const [selection, setSelection] = useState(null);
  const selectedIndex = exhibitions.findIndex((item) => item.id === selection);
  const index = selectedIndex < 0 ? 0 : selectedIndex;
  const exhibition = exhibitions[index];
  if (!exhibition) return <><Header /><p className="visitor-message">공개된 전시가 없습니다.</p></>;

  const multiple = exhibitions.length > 1;
  const previous = exhibitions[(index + exhibitions.length - 1) % exhibitions.length];
  const next = exhibitions[(index + 1) % exhibitions.length];
  const poster = exhibitionImage(exhibition);
  const venue = exhibitionVenue(exhibition);
  return <>
    <Header />
    <section className="visitor-home" aria-label="공개 전시 목록">
      <div className="visitor-carousel">
        {multiple && <button className="visitor-side-poster visitor-previous" type="button"
          aria-label={'이전 전시: ' + previous.name} onClick={() => setSelection(previous.id)}>
          <Poster imageUrl={exhibitionImage(previous)}>{previous.name}</Poster>
        </button>}
        <Poster className="visitor-home-poster" imageUrl={poster}>{exhibition.name}</Poster>
        {multiple && <button className="visitor-side-poster visitor-next" type="button"
          aria-label={'다음 전시: ' + next.name} onClick={() => setSelection(next.id)}>
          <Poster imageUrl={exhibitionImage(next)}>{next.name}</Poster>
        </button>}
        {poster && <div className="visitor-poster-pocket" aria-hidden="true" />}
      </div>
      <h1>{exhibition.name}</h1>
      {venue && <p className="visitor-muted visitor-home-venue">{venue}</p>}
      <Link className="visitor-button" to={visitorUrl(exhibition.id)}>관람 시작하기</Link>
    </section>
  </>;
}

function CatalogRow({ to, title, subtitle, imageUrl, onSelect }) {
  const content = <>
    <Poster className="visitor-thumbnail" imageUrl={imageUrl} />
    <div><strong>{title}</strong>{subtitle && <p className="visitor-muted">{subtitle}</p>}</div>
  </>;
  return <li>{to
    ? <Link className="visitor-catalog-row" to={to} onClick={onSelect}>{content}</Link>
    : <div className="visitor-catalog-row">{content}</div>}
  </li>;
}

function ExhibitionSearch({ exhibitions }) {
  const [query, setQuery] = useState('');
  const [recent, setRecent] = useState(() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(recentSearchKey));
      return Array.isArray(stored) ? stored.filter((value) => typeof value === 'string') : [];
    } catch {
      return [];
    }
  });
  const term = query.trim();
  const keyword = term.toLocaleLowerCase();
  const results = exhibitions.filter((item) => [item.name, item.code, exhibitionVenue(item)]
    .some((value) => value?.toLocaleLowerCase().includes(keyword)));

  function rememberSearch() {
    if (!term) return;
    const updated = [term, ...recent.filter((value) => value !== term)].slice(0, 5);
    setRecent(updated);
    try {
      sessionStorage.setItem(recentSearchKey, JSON.stringify(updated));
    } catch {
      // Recent terms can still be used on this screen.
    }
  }

  return <>
    <form className="visitor-search-header" onSubmit={(event) => {
      event.preventDefault();
      rememberSearch();
    }}>
      <IconLink to="/visitor" icon={searchBack} label="뒤로" back />
      <div className="visitor-search-field"><input type="search" placeholder="전시명 또는 미술관명" aria-label="전시명 또는 미술관명"
        value={query} onChange={(event) => setQuery(event.target.value)} />
        <button className="visitor-search-submit" type="submit" aria-label="검색"><img src={fieldSearch} alt="" /></button></div>
    </form>
    {keyword ? <section className="visitor-search-results">
      <h1>검색 결과 {results.length}개</h1>
      {results.length ? <ul className="visitor-catalog">
        {results.map((item) => <CatalogRow key={item.id} to={visitorUrl(item.id)} onSelect={rememberSearch}
          title={item.name} subtitle={exhibitionVenue(item)} imageUrl={exhibitionImage(item)} />)}
      </ul> : <p className="visitor-muted">검색 결과가 없습니다.</p>}
    </section> : <section className="visitor-search-results visitor-search-method">
      {!!recent.length && <div>
        <h1>최근 검색어</h1>
        <div className="visitor-search-chips">
          {recent.map((value) => <button type="button" key={value} onClick={() => setQuery(value)}>{value}</button>)}
        </div>
      </div>}
      <Link className="visitor-button" to={codeUrl}>전시 코드로 검색하기</Link>
    </section>}
  </>;
}

function ExhibitionCode({ exhibitions }) {
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [failed, setFailed] = useState(false);

  function findExhibition(event) {
    event.preventDefault();
    const match = exhibitions.find((item) => item.code.toLocaleLowerCase() === code.trim().toLocaleLowerCase());
    if (match) navigate(visitorUrl(match.id));
    else setFailed(true);
  }

  return <>
    <Header title="전시 코드 입력" back={searchUrl} search={false} />
    <form className="visitor-code" onSubmit={findExhibition}>
      {!failed && <p>전시장 안내에 표시된 코드를 입력해 주세요.</p>}
      <input aria-label="전시 코드 입력" placeholder="전시 코드 입력" autoComplete="off" spellCheck={false}
        disabled={failed} value={code} onChange={(event) => setCode(event.target.value)} />
      {failed ? <>
        <p role="alert" className="visitor-code-error">전시 코드를 찾을 수 없어요.<br />코드를 확인한 후 다시 입력해 주세요.</p>
        <button className="visitor-button" type="button" onClick={() => {
          setCode('');
          setFailed(false);
        }}>다시 입력하기</button>
      </> : <button className="visitor-button visitor-primary" type="submit" disabled={!code.trim()}>전시 찾기</button>}
    </form>
  </>;
}

function Exhibition({ data }) {
  const venue = exhibitionVenue(data);
  return <div className="visitor-exhibition-page">
    <Header title="전시 안내" back="/visitor" />
    <section className="visitor-exhibition">
      <Poster className="visitor-exhibition-poster" imageUrl={exhibitionImage(data)}>{data.name}</Poster>
      <div className="visitor-exhibition-info">
        <h1>{data.name}</h1>
        {venue && <p className="visitor-muted">{venue}</p>}
      </div>
      <div className="visitor-exhibition-info">
        {data.description && <p className="visitor-text">{data.description}</p>}
        <p className="visitor-muted">작품 {data.artworks.length}점</p>
      </div>
      <section className="visitor-exhibition-list" aria-label="만나볼 작품">
        <h2>만나볼 작품</h2>
        {data.artworks.length ? <ol className="visitor-catalog visitor-exhibition-works" role="list">
          {data.artworks.map((item) => <CatalogRow key={item.id}
            title={item.name} subtitle={artworkMetadata(item)} imageUrl={artworkImage(item)} />)}
        </ol> : <p className="visitor-muted">등록된 작품이 없습니다.</p>}
      </section>
    </section>
    <footer className="visitor-exhibition-footer">
      {data.artworks.length
        ? <Link className="visitor-button visitor-primary" to={visitorUrl(data.id, null, 1)}>전시 관람하기</Link>
        : <button className="visitor-button visitor-primary" type="button" disabled>전시 관람하기</button>}
    </footer>
  </div>;
}

function artworkMetadata({ year, artist }) {
  return [year, artist].filter(Boolean).join(' · ');
}

function Artwork({ data, profile, nextArtwork, suggestedQuestions, visible }) {
  const { id: artworkId, exhibition: { id: exhibitionId } } = data;
  const metadata = artworkMetadata(data);
  const questionsUrl = visitorUrl(exhibitionId, artworkId, null, 'questions');
  const [result, setResult] = useState({ state: 'loading' });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    // Let React's development effect replay clean up before spending a Gemini request.
    const timer = window.setTimeout(async () => {
      try {
        const generated = await generateDocent(exhibitionId, artworkId, profile, signal);
        if (!signal.aborted) {
          setResult({ state: 'ready', text: generated.text });
          if (import.meta.env.DEV && generated.debug) {
            console.debug('[Visitor docent]', { ...generated.debug, artworkId, text: generated.text });
          }
        }
      } catch (error) {
        if (!signal.aborted) {
          const message = error instanceof TypeError ? '도슨트 서버에 연결할 수 없습니다.' : error.message;
          setResult({ state: 'failed', message });
        }
      }
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [exhibitionId, artworkId, profile, retry]);

  if (result.state === 'loading') return <div className="visitor-docent-loading">
    <header className="visitor-survey-header">
      <Link to={visitorUrl(exhibitionId)} className="visitor-icon visitor-survey-back" aria-label="전시 안내로 돌아가기" />
    </header>
    <div role="status" className="visitor-docent-loading-copy">
      <img src={docentLoading} alt="" />
      <div><h1>나에게 맞는 도슨트를 준비하고 있어요</h1>
        <p>선택한 답변을 바탕으로<br />작품마다 나에게 맞는 이야기를 들려드릴게요</p></div>
    </div>
  </div>;

  return <div className="visitor-artwork-page">
    <Header title={data.exhibition.name} back={visitorUrl(data.exhibition.id)} artwork search={false} />
    <section className="visitor-artwork">
      <div className="visitor-artwork-identity">
        <Poster className="visitor-artwork-image" imageUrl={artworkImage(data)} />
        <div><h1>{data.name}</h1>{metadata && <p className="visitor-muted">{metadata}</p>}</div>
      </div>
      {result.state === 'ready' && result.text && <DocentAudio
        key={JSON.stringify([result.text, profile.why])} text={result.text} why={profile.why} visible={visible} />}
      <section className="visitor-docent" aria-label="개인화 도슨트 설명">
        {result.state === 'failed' && <>
          <p role="alert">{result.message}</p>
          <button className="visitor-button" type="button" onClick={() => {
            setResult({ state: 'loading' });
            setRetry((value) => value + 1);
          }}>다시 시도</button>
        </>}
        {result.state === 'ready' && (result.text
          ? <p className="visitor-text">{result.text}</p>
          : <p className="visitor-muted">아직 게시된 작품 해설이 없습니다.</p>)}
      </section>
      <section className="visitor-question-preview" aria-labelledby="visitor-question-preview-title">
        <div className="visitor-question-preview-heading">
          <h2 id="visitor-question-preview-title">더 궁금한 점이 있나요?</h2>
          {suggestedQuestions.length > 0 && <p className="visitor-muted">추천 질문을 선택하거나 직접 질문해 보세요.</p>}
        </div>
        <div className="visitor-question-options">
          {suggestedQuestions.map(({ question, question_id }) => <Link key={question_id} to={questionsUrl}
            state={{ questionId: question_id }} className="visitor-question-option">
            <span className="visitor-question-label">{question}</span><span aria-hidden="true">↗</span>
          </Link>)}
          <Link to={questionsUrl} state={{ focusComposer: true }} className="visitor-question-option visitor-question-custom">궁금한 점을 직접 입력해 주세요.<span aria-hidden="true">↗</span></Link>
        </div>
      </section>
    </section>
    <footer className="visitor-artwork-footer">
      <Link className="visitor-button visitor-primary" to={questionsUrl}>질문하기</Link>
      {nextArtwork && <Link className="visitor-button" to={visitorUrl(exhibitionId, nextArtwork.id)}>다음 작품</Link>}
    </footer>
  </div>;
}

function VisitorCatalog({ exhibitionId, artworkId, surveyStep, view, profile, onProfileChange }) {
  const [result, setResult] = useState({ state: 'loading' });
  const [retry, setRetry] = useState(0);
  const [savedQuestions, setSavedQuestions] = useState(null);
  const interest = profile.what;
  const how = profile.how;
  const suggestionsReady = savedQuestions?.how === how;
  const suggestions = suggestionsReady ? rankSuggestedQuestions(savedQuestions.items, interest) : [];
  useEffect(() => {
    if (!exhibitionId || !artworkId) return;
    const controller = new AbortController();
    let pending = false;
    function refreshQuestions() {
      if (pending) return;
      pending = true;
      readSuggestedQuestions(exhibitionId, artworkId, how, controller.signal)
        .then((questions) => {
          if (!controller.signal.aborted) setSavedQuestions({ how, items: questions });
        })
        .catch(() => {
          if (!controller.signal.aborted) setSavedQuestions((current) => current?.how === how ? current : { how, items: [] });
        })
        .finally(() => { pending = false; });
    }
    refreshQuestions();
    window.addEventListener('focus', refreshQuestions);
    return () => {
      window.removeEventListener('focus', refreshQuestions);
      controller.abort();
    };
  }, [exhibitionId, artworkId, how]);
  const showQuestions = view === 'questions';

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let loading = false;

    async function refresh() {
      if (loading || document.visibilityState === 'hidden') return;
      loading = true;
      try {
        const [data, exhibition] = await Promise.all([
          readVisitorCatalog(exhibitionId, artworkId, signal),
          artworkId ? readVisitorCatalog(exhibitionId, null, signal) : undefined,
        ]);
        if (!signal.aborted) setResult(data === null || exhibition === null
          ? { state: 'unavailable' } : { state: 'ready', data, exhibition });
      } catch {
        if (!signal.aborted) setResult({ state: 'failed' });
      } finally {
        loading = false;
      }
    }

    refresh();
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    const interval = window.setInterval(refresh, 15000);
    return () => {
      controller.abort();
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
      window.clearInterval(interval);
    };
  }, [exhibitionId, artworkId, retry]);

  if (result.state === 'ready') {
    if (artworkId) {
      const { artworks } = result.exhibition;
      const index = artworks.findIndex(({ id }) => id === result.data.id);
      const nextArtwork = index >= 0 ? artworks[index + 1] : null;
      return <>
        <div hidden={showQuestions}>
          <Artwork data={result.data} profile={profile} nextArtwork={nextArtwork} suggestedQuestions={suggestions} visible={!showQuestions} />
        </div>
        {showQuestions && <VisitorChat data={result.data} profile={profile} nextArtwork={nextArtwork}
          suggestedQuestions={suggestions} suggestionsReady={suggestionsReady} />}
      </>;
    }
    if (exhibitionId) {
      const first = result.data.artworks[0];
      if (surveyStep && first) return <VisitorSurvey key={surveyStep} exhibitionId={exhibitionId}
        firstArtworkId={first.id} step={surveyStep} profile={profile} onChange={onProfileChange} />;
      return <Exhibition data={result.data} />;
    }
    if (view === 'search') return <ExhibitionSearch exhibitions={result.data} />;
    if (view === 'code') return <ExhibitionCode exhibitions={result.data} />;
    return <ExhibitionHome exhibitions={result.data} />;
  }

  return <><Header back={exhibitionId || view ? '/visitor' : null} />
    <div className="visitor-message">
      {result.state === 'loading' && <p role="status">공개 전시 정보를 불러오는 중입니다…</p>}
      {result.state === 'unavailable' && <>
        <p role="alert">공개된 전시 또는 작품을 찾을 수 없습니다.</p>
        <Link className="visitor-button" to="/visitor">전시 목록으로 돌아가기</Link>
      </>}
      {result.state === 'failed' && <>
        <p role="alert">공개 데이터를 불러올 수 없습니다.</p>
        <button className="visitor-button" type="button" onClick={() => {
          setResult({ state: 'loading' });
          setRetry((value) => value + 1);
        }}>다시 불러오기</button>
      </>}
    </div>
  </>;
}

export default function Visitor() {
  const [params] = useSearchParams();
  const [profile, setProfile] = useState(readVisitorProfile);
  const exhibitionId = params.get('exhibition');
  const artworkId = exhibitionId ? params.get('artwork') : null;
  const view = params.get('view');
  const step = Number(params.get('step'));
  const surveyStep = Number.isInteger(step) && step >= 1 && step <= 4 ? step : 0;
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [exhibitionId, artworkId, surveyStep, view]);

  const missing = firstUnanswered(profile);
  if (artworkId && (missing || surveyStep)) {
    return <Navigate to={visitorUrl(exhibitionId, null, surveyStep || missing)} replace />;
  }
  if (exhibitionId && missing && surveyStep > missing) {
    return <Navigate to={visitorUrl(exhibitionId, null, missing)} replace />;
  }

  function updateProfile(key, value) {
    const updated = { ...profile, [key]: value };
    saveVisitorProfile(updated);
    setProfile(updated);
  }

  return <main className="visitor">
    <VisitorCatalog key={JSON.stringify([exhibitionId, artworkId])} exhibitionId={exhibitionId} artworkId={artworkId}
      surveyStep={surveyStep} view={view} profile={profile} onProfileChange={updateProfile} />
  </main>;
}
