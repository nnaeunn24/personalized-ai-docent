import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { adminApi } from './adminApi';
import { createAdminSession } from './adminSession';
import { clearVerifier, prepareRecovery, readVerifier, recoveryCallback } from './passwordRecovery';
import './admin.css';

const invalidLink = '복구 링크가 만료되었거나 유효하지 않습니다. 새 링크를 요청해 주세요.';

async function verifyCallback(callback) {
  if (callback.kind === 'token') {
    await adminApi.me(callback.value);
    return callback.value;
  }
  if (callback.kind === 'hash') return (await adminApi.verifyRecoveryHash(callback.value)).access_token;
  const session = await adminApi.exchangeRecoveryCode(callback.value, callback.verifier);
  clearVerifier(callback.verifier);
  return session.access_token;
}

export default function AdminPasswordReset() {
  const location = useLocation();
  const navigate = useNavigate();
  const [callback, setCallback] = useState(() => {
    const value = recoveryCallback(location);
    return value.kind === 'code' ? { ...value, verifier: readVerifier() } : value;
  });
  const missingVerifier = callback.kind === 'code' && !callback.verifier;
  const needsVerification = ['token', 'hash', 'code'].includes(callback.kind) && !missingVerifier;
  const [token, setToken] = useState(null);
  const [error, setError] = useState(() => {
    if (missingVerifier) return '이 링크는 이메일을 요청한 브라우저와 같은 주소에서 열어 주세요. 새 링크를 요청할 수도 있습니다.';
    return callback.kind === 'invalid' ? invalidLink : '';
  });
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verificationFailed, setVerificationFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const submitting = useRef(false);
  const verification = useRef(null);

  useLayoutEffect(() => {
    if (location.hash || location.search) {
      window.history.replaceState(window.history.state, '', location.pathname);
    }
  }, [location.hash, location.pathname, location.search]);

  useEffect(() => {
    if (!needsVerification) return;
    let active = true;
    // Strict Mode can mount the effect twice. Do not exchange a one-time code twice.
    if (verification.current?.attempt !== attempt) {
      verification.current = { attempt, result: verifyCallback(callback) };
    }
    verification.current.result.then((accessToken) => {
      if (!active) return;
      setToken(accessToken);
      setCallback({ kind: 'none' });
      verification.current = null;
    }).catch((failure) => {
      if (!active) return;
      if ([401, 403, 422].includes(failure.status)) {
        setCallback({ kind: 'none' });
        setError(invalidLink);
        verification.current = null;
      } else {
        setError('복구 링크를 확인할 수 없습니다. 서버 연결을 확인하고 다시 시도해 주세요.');
        setVerificationFailed(true);
      }
    });
    return () => { active = false; };
  }, [attempt, callback, needsVerification]);

  async function submit(event) {
    event.preventDefault();
    if (submitting.current) return;
    const data = new FormData(event.currentTarget);
    const password = data.get('password');
    setError('');
    setSent(false);
    if (token && password !== data.get('confirmation')) {
      setError('새 비밀번호와 비밀번호 확인이 일치해야 합니다.');
      return;
    }

    submitting.current = true;
    setBusy(true);
    try {
      if (token) {
        await adminApi.resetPassword(token, password);
        // The recovery session is separate from the administrator's normal sign-in.
        void adminApi.logout(token).catch(() => {});
        createAdminSession().clear();
        setToken(null);
        navigate('/admin', { replace: true, state: { passwordReset: true } });
      } else {
        const { challenge, verifier } = await prepareRecovery();
        try {
          await adminApi.recoverPassword(data.get('email').trim(), challenge);
        } catch (failure) {
          if (verifier) clearVerifier(verifier);
          throw failure;
        }
        setSent(true);
      }
    } catch (failure) {
      if (token && (failure.status === 401 || failure.status === 403)) {
        setToken(null);
        setError(invalidLink);
      } else if (failure.status === 429) {
        setError('요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.');
      } else if (token && failure.status === 422) {
        setError('비밀번호를 변경할 수 없습니다. 기존 비밀번호와 다른 값으로 프로젝트의 비밀번호 요건을 충족해 주세요.');
      } else if (!token && failure.status === 403) {
        setError('현재 주소는 복구 요청에 사용할 수 없습니다. 관리자 프론트엔드 주소를 확인해 주세요.');
      } else {
        setError(failure.status === 0 ? failure.message
          : token ? '비밀번호 변경에 실패했습니다. 다시 시도해 주세요.'
            : '재설정 이메일 요청에 실패했습니다. 다시 시도해 주세요.');
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  if (needsVerification) return <main className="admin admin-login">
    <div className="admin-login-card">
      <div className="admin-stack">
        <div className="admin-brand"><strong>docent.</strong><small>Admin</small></div>
        <h1>복구 링크 확인</h1>
        {verificationFailed ? <>
          <p className="admin-notice error" role="alert">{error}</p>
          <button className="admin-button" type="button" onClick={() => {
            setError('');
            setVerificationFailed(false);
            setAttempt((value) => value + 1);
          }}>다시 확인</button>
          <button className="admin-button ghost" type="button" onClick={() => {
            verification.current = null;
            setError('');
            setCallback({ kind: 'none' });
          }}>새 링크 요청</button>
        </> : <p role="status">복구 링크를 확인하고 있습니다…</p>}
      </div>
    </div>
  </main>;

  return <main className="admin admin-login">
    <div className="admin-login-card">
      <form onSubmit={submit}>
        <div className="admin-brand"><strong>docent.</strong><small>Admin</small></div>
        <h1>{token ? '새 비밀번호 설정' : '비밀번호 찾기'}</h1>
        {token ? <>
          <p className="admin-blue">새 비밀번호를 입력하세요.</p>
          <label className="admin-field"><span>새 비밀번호</span>
            <input name="password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required />
          </label>
          <label className="admin-field"><span>새 비밀번호 확인</span>
            <input name="confirmation" type="password" autoComplete="new-password" minLength={8} maxLength={72} required />
          </label>
        </> : <>
          <p className="admin-blue">관리자 이메일로 비밀번호 재설정 링크를 요청하세요.</p>
          <label className="admin-field"><span>관리자 이메일</span>
            <input name="email" type="email" autoComplete="email" maxLength={320} placeholder="관리자 이메일 입력" required />
          </label>
        </>}
        {error && <p className="admin-notice error" role="alert">{error}</p>}
        {sent && <p className="admin-notice" role="status">등록된 이메일이라면 재설정 링크가 전송됩니다. 메일함을 확인해 주세요.</p>}
        <button className="admin-button" type="submit" disabled={busy}>
          {busy ? '처리 중…' : token ? '비밀번호 변경' : '재설정 이메일 보내기'}
        </button>
        <Link className="admin-recovery-link" to="/admin" replace>관리자 로그인으로 돌아가기</Link>
      </form>
    </div>
  </main>;
}
