import { useEffect, useRef, useState } from 'react';
import { generateVisitorSpeech } from './visitorApi';
import playIcon from './player-play.svg';
import pauseIcon from './player-pause.svg';
import replayIcon from './player-replay.svg';

const preparing = { state: 'loading', elapsed: 0, duration: 0 };
const controls = {
  playing: [pauseIcon, '일시정지'],
  paused: [playIcon, '이어 듣기'],
  ended: [replayIcon, '처음부터 다시 재생'],
  failed: [replayIcon, '음성 준비 다시 시도'],
};

function formatTime(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

export default function DocentAudio({ text, why, visible }) {
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState(preparing);
  const player = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let audio;
    let url;

    // Avoid a duplicate request when React replays the effect in development.
    const timer = window.setTimeout(async () => {
      try {
        const blob = await generateVisitorSpeech(text, why, signal);
        if (signal.aborted) return;
        url = URL.createObjectURL(blob);
        audio = new Audio();
        player.current = audio;
        const update = (state) => {
          if (signal.aborted) return;
          const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
          setStatus((current) => ({
            state: state ?? current.state,
            elapsed: state === 'ended' ? duration : audio.currentTime,
            duration,
          }));
        };
        audio.addEventListener('loadedmetadata', () => update('ready'), { once: true, signal });
        audio.addEventListener('timeupdate', () => update(), { signal });
        audio.addEventListener('playing', () => update('playing'), { signal });
        audio.addEventListener('pause', () => {
          if (!audio.ended) update('paused');
        }, { signal });
        audio.addEventListener('ended', () => update('ended'), { signal });
        audio.addEventListener('error', () => {
          setStatus({ ...preparing, state: 'failed', message: '음성 파일을 재생할 수 없어요. 다시 준비해 주세요.' });
        }, { signal });
        audio.preload = 'auto';
        audio.src = url;
      } catch (error) {
        if (!signal.aborted) setStatus({ ...preparing, state: 'failed',
          message: error instanceof TypeError ? '음성 서버에 연결할 수 없어요.' : error.message });
      }
    }, 0);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
      player.current = null;
      audio?.pause();
      if (url) URL.revokeObjectURL(url);
    };
  }, [text, why, attempt]);

  useEffect(() => {
    if (!visible) player.current?.pause();
  }, [visible]);

  async function togglePlayback() {
    if (status.state === 'failed') {
      setStatus(preparing);
      setAttempt((value) => value + 1);
      return;
    }
    const audio = player.current;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (audio.ended) audio.currentTime = 0;
    try {
      await audio.play();
    } catch (error) {
      if (player.current === audio && !audio.error && error.name !== 'AbortError') {
        setStatus((current) => ({ ...current, state: 'paused', message: '음성을 재생할 수 없어요. 다시 눌러 주세요.' }));
      }
    }
  }

  const [icon, label] = controls[status.state] ?? [playIcon, '음성 재생'];
  return <div className="visitor-audio" aria-label="음성 안내">
    <div className="visitor-audio-player">
      <button type="button" disabled={status.state === 'loading'} aria-label={label} onClick={togglePlayback}>
        <img src={icon} alt="" />
      </button>
      <span>{formatTime(status.elapsed)}</span>
      <progress className="visitor-audio-track" value={status.elapsed} max={status.duration || 1} aria-label="음성 재생 진행률" />
      <span>{status.duration ? formatTime(status.duration) : '–:–'}</span>
    </div>
    {status.state === 'loading' && <p role="status" className="visitor-muted">음성을 준비하고 있어요…</p>}
    {status.message && <p role="alert" className="visitor-muted">{status.message}</p>}
  </div>;
}
