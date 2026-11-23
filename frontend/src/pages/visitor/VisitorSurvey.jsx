import { Link, useNavigate } from 'react-router-dom';
import { visitorUrl } from './visitorApi';
import { contextHint, intro, questions } from './visitorProfile';

export default function VisitorSurvey({ exhibitionId, firstArtworkId, step, profile, onChange }) {
  const navigate = useNavigate();
  const { key, title, options } = questions[step - 1];
  const previous = visitorUrl(exhibitionId, null, step > 1 ? step - 1 : undefined);
  const next = step === 4 ? visitorUrl(exhibitionId, firstArtworkId) : visitorUrl(exhibitionId, null, step + 1);

  function skipContext() {
    onChange('context', '');
    navigate(next);
  }

  return <form className="visitor-survey" onSubmit={(event) => {
    event.preventDefault();
    if (profile[key].trim()) navigate(next);
  }}>
    <div>
      <header className="visitor-survey-header">
        <Link to={previous} className="visitor-icon visitor-survey-back" aria-label="이전 화면" />
      </header>
      <progress className="visitor-survey-progress" value={step} max={4} aria-label={`사전 질문 ${step}/4`} />
      <div className="visitor-survey-body">
        <h1 id="visitor-survey-title">{title[0]}<br />{title[1]}</h1>
        <p id="visitor-survey-hint">{options ? intro : contextHint}</p>
        {options ? <fieldset aria-labelledby="visitor-survey-title" aria-describedby="visitor-survey-hint">
          {options.map(([value, label]) => <label className="visitor-survey-choice" key={value}>
            <span>{label}</span>
            <input type="radio" name={key} value={value} checked={profile[key] === value}
              onChange={() => onChange(key, value)} />
          </label>)}
        </fieldset> : <>
          <textarea aria-labelledby="visitor-survey-title" aria-describedby="visitor-survey-hint" maxLength={1000}
            placeholder="예: 시험이 끝나서 홀가분해요. / 최근 새로운 시작을 앞두고 있어요."
            value={profile.context} onChange={(event) => onChange(key, event.target.value)} />
          <button className="visitor-button" type="button" onClick={skipContext}>건너뛰기</button>
        </>}
      </div>
    </div>
    <div className="visitor-survey-actions">
      {step > 1 && <Link className="visitor-button" to={previous}>이전</Link>}
      <button className="visitor-button visitor-primary" type="submit" disabled={!profile[key].trim()}>다음</button>
    </div>
  </form>;
}
