# Docent 관리자 API와 Supabase 설정

관리자 React 화면은 `/admin`에서 FastAPI에 연결됩니다. `/admin/preview`는 독립된 로컬 미리보기입니다. FastAPI 호출과 화면별 데이터 변환은 [React API 모듈](../frontend/src/pages/admin/adminApi.js)에 있습니다.

## 데이터 모델

| 테이블 | 용도 |
| --- | --- |
| `admin_users` | Supabase Auth 사용자 UUID와 관리자 표시 이름을 연결하는 허용 목록 |
| `exhibitions` | 전시명, 소개, 공개 여부, 서버 생성 전시 코드, 선택적 대표 이미지 경로 |
| `artworks` | 소속 전시, 작가 및 작품 정보, 원본 Description, 출처, 언어, 선택적 이미지 경로 |
| `content_units` | 소속 작품, 단위 번호, 본문, WHAT 카테고리, 검수 상태, 추출·분류 방식과 모델 |

관리자 화면 요구에 맞춰 단일 워크스페이스를 전제로 합니다. 등록된 관리자는 같은 전시 목록을 공유합니다. 작품은 전시 하나에 속하고, Unit은 작품 하나에 속합니다. 전시나 작품을 삭제하면 해당 하위 레코드도 삭제됩니다.

Unit은 `pending`으로 생성됩니다. 명시적으로 검수하면 `reviewed`가 되고, 작품별 게시 요청이 검수 완료 Unit을 `published`로 바꿉니다. 본문이나 카테고리를 변경하면 DB 트리거가 검수 대기로 돌립니다. 수동 등록은 추출·분류 방식이 `manual`이고 모델은 비어 있습니다. `automatic`에는 모델명이 필요합니다. 카테고리를 편집하면 분류 방식은 `manual`로 기록하고 추출 정보는 유지합니다. 전시 공개 여부와 Unit 게시 상태는 독립적입니다.

## Supabase 설정 순서

1. 대시보드에서 작업 대상 프로젝트와 프로젝트 URL을 확인합니다. 기존 DB 백업을 확보하고 복구 방법을 확인합니다. 가능하면 별도 테스트 프로젝트에서 설정 순서를 먼저 점검합니다. [Supabase 백업 문서](https://supabase.com/docs/guides/platform/backups)
2. 대상 프로젝트의 SQL Editor에 [최종 초기화 SQL](sql/02_reset_schema.sql) 전체를 붙여 넣습니다. 백업을 확인하고 초기화를 결정한 뒤 한 번 실행합니다. 이 파일이 삭제와 생성을 한 트랜잭션으로 처리합니다. [삭제 구간](sql/00_drop_legacy.sql)과 [생성 구간](sql/01_create_schema.sql)은 검토용입니다. 최종 파일을 실행한 뒤 이 두 파일을 따로 실행할 필요가 없습니다. 외부 의존성이나 순환 외래 키가 발견되면 전체 작업이 롤백되므로 SQL Editor에 표시된 오류와 Detail을 확인하세요.
3. 대시보드에서 Authentication의 Email/Password 로그인을 활성화하고 관리자 계정을 생성합니다. 관리자 전용 프로젝트라면 공개 가입을 비활성화합니다. Auth 사용자의 UUID를 복사하고, 확인된 사용자를 아래 SQL로 관리자 허용 목록에 등록합니다. 기존 Auth 계정을 유지하거나 사용할 계정을 새로 만드는 것은 별도 결정입니다. 제공된 삭제 SQL은 `auth.users`나 Storage의 객체를 건드리지 않습니다. [Supabase 이메일·비밀번호 인증](https://supabase.com/docs/guides/auth/passwords)
4. 프로젝트의 Connect 또는 Settings → API Keys에서 Project URL과 **publishable key**를 확인합니다. Data API가 활성화되어 있고 `public`이 노출 스키마에 포함되어 있어야 합니다. FastAPI는 모든 관리자 요청에서 Supabase Auth의 사용자 정보와 `admin_users`를 검사합니다. 같은 사용자 토큰으로 Data API에 접근하고 RLS가 권한을 한 번 더 확인합니다. publishable key를 우선 사용합니다. `backend/.env`에 서버 전용 `SUPABASE_SECRET_KEY`만 설정된 경우에도 관리자 Data API 요청에는 검증된 사용자 JWT를 함께 전달합니다. [Supabase API 키](https://supabase.com/docs/guides/api/api-keys) · [Supabase Data API 보호](https://supabase.com/docs/guides/api/securing-your-api)
5. 아래 환경변수와 실행 명령으로 로컬 API를 실행합니다. `/health`는 FastAPI 프로세스만 확인합니다. 실제 연결은 `/docs`에서 로그인한 뒤 받은 access token으로 `GET /api/admin/me`와 목록을 요청해 확인합니다. 관리자에 등록하지 않은 정상 Auth 사용자는 403, 토큰이 없는 요청은 401을 받아야 합니다.

관리자 한 명을 등록하거나 기존 표시 이름을 수정하는 예입니다. 실제 Auth UUID와 표시 이름으로 바꿔서 사용합니다.

```sql
insert into public.admin_users (user_id, display_name)
values ('AUTH_USER_UUID', '관리자 표시 이름')
on conflict (user_id) do update set display_name = excluded.display_name;
```

## 로컬 실행

Python 3.11 이상을 준비합니다. 프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
Set-Location backend
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`backend/.env`의 값을 설정합니다.

| 변수 | 값 |
| --- | --- |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_PUBLISHABLE_KEY` | 프로젝트의 publishable key (우선 사용) |
| `SUPABASE_SECRET_KEY` | publishable key가 없을 때 사용하는 서버 전용 키 |
| `CORS_ORIGINS` | React 주소를 담은 JSON 배열. 기본값은 `localhost:5173`, `127.0.0.1:5173`의 HTTP 주소입니다. |

프론트엔드 환경변수는 `frontend/.env.example`을 `frontend/.env`로 복사한 뒤 설정합니다. `VITE_ADMIN_API_URL`에는 기본적으로 `http://127.0.0.1:8000`을 사용합니다. `VITE_` 변수는 브라우저에 노출됩니다. 설정 변경 후 Vite를 다시 시작합니다.

## 관리자 화면 확인

`frontend`에서 `npm.cmd run dev`를 실행하고 `http://localhost:5173/admin`을 엽니다. 관리자 계정으로 로그인한 뒤 전시와 작품을 등록합니다. 작품 상세의 Content Unit 검수 화면에서 수동 추가를 선택하면 Unit을 저장할 수 있습니다. 새로고침 후에도 저장된 항목이 표시됩니다. 자동 추출, 이미지 업로드, 관람객 진입 링크는 준비 중입니다.

## 관리자 비밀번호 재설정

1. Supabase Dashboard에서 **Authentication → URL Configuration**을 엽니다.
2. **Site URL**에 프론트엔드 기본 주소를 설정합니다. 로컬에서만 사용한다면 `http://localhost:5173`입니다. 배포 서비스가 있다면 배포 프론트엔드 주소를 Site URL로 유지합니다.
3. **Redirect URLs**에 `http://localhost:5173/admin/reset-password`를 추가합니다. 브라우저에서 `127.0.0.1`도 사용하면 `http://127.0.0.1:5173/admin/reset-password`도 추가합니다. 배포 환경에는 실제 프론트엔드 도메인의 같은 경로를 추가합니다. FastAPI의 `CORS_ORIGINS`에는 경로 없이 각각의 프론트엔드 origin을 넣습니다.
4. **Authentication → Email Templates → Reset Password**에서 기본 복구 링크인 `{{ .ConfirmationURL }}`을 사용합니다. 기존 링크의 주소는 바뀌지 않으므로 설정을 저장한 뒤 관리자 로그인 화면의 **비밀번호 찾기**에서 새 메일을 요청합니다.
5. 메일 링크를 열고 새 비밀번호를 저장합니다. 변경이 완료되면 관리자 로그인 화면에서 새 비밀번호로 로그인합니다.

[Supabase Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls) · [Supabase 비밀번호 재설정](https://supabase.com/docs/guides/auth/passwords)

메일 발송을 요청한 브라우저의 같은 주소에서 링크를 열어 주세요. `localhost`와 `127.0.0.1`은 별도의 브라우저 주소입니다. 예전에 발송된 링크가 만료되었거나 다른 브라우저에서 열려 복구할 수 없으면 같은 주소에서 새 메일을 요청하세요.

## Gemini Content Unit 추출

1. Supabase SQL Editor에서 [03 추출용 마이그레이션](sql/03_artwork_unit_extraction.sql)이 적용된 상태에서 [04 추출 결과 검증 마이그레이션](sql/04_verify_artwork_unit_extraction.sql)을 한 번 실행합니다. 처음 설치한다면 03 → 04 순서로 실행합니다. 기존 작품과 Unit을 초기화하지 않습니다.
2. `backend/.env`에 `GEMINI_API_KEY`를 설정합니다. `GEMINI_MODEL` 기본값은 `gemini-3.5-flash-lite`입니다. `GEMINI_CLASSIFICATION_MODEL`을 비워 두면 같은 모델을 사용합니다. 설정 후 FastAPI를 다시 시작합니다.
3. 관리자 화면에서 작품 정보와 Description을 입력하고 **작품 등록**을 누릅니다. 이미 등록한 작품에서 다시 추출하려면 **저장 및 Unit 추출**을 누릅니다. 작품이 먼저 저장되고 Description이 Gemini로 전달됩니다. 검증된 결과를 검수 대기로 저장하면 작품별 Content Unit 검수로 이동합니다. 실패하면 작품 상세에서 **추출 재시도**를 사용할 수 있습니다.

작품에 저장된 Description 내용이 동일하면 완료된 추출을 다시 저장하지 않습니다. Description이 바뀐 경우 기존 Unit과 본문이 같은 항목은 건너뛰고 새 항목만 추가합니다. 검수·게시 상태는 기존 Unit에 그대로 남습니다. 저장된 Unit이 한 개도 확인되지 않는 이전 추출 기록은 재시도할 수 있습니다.

[Gemini 3.5 Flash-Lite 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)

## 관리자 AI Settings

Supabase SQL Editor에서 기존 03과 04가 적용된 상태로 [05_admin_ai_settings.sql](sql/05_admin_ai_settings.sql)을 한 번 실행합니다. 이 마이그레이션은 프롬프트 버전, 활성 설정, 테스트·추출 기록과 근거 필드를 추가합니다. 기존 Unit과 검수 상태는 유지됩니다.

- 관리자 **AI Settings**에서 추출·분류 프롬프트를 각각 편집하고 새 버전으로 저장합니다. 이전 버전은 편집기에 불러와 테스트하거나 활성 버전으로 복원할 수 있습니다.
- 기존 작품의 Description을 불러오거나 직접 입력하고 **테스트 실행**을 누릅니다. 현재 편집기 내용을 사용하며 테스트 기록만 저장합니다. 이전 결과와 새 결과를 비교 목록에서 선택할 수 있습니다.
- 작품 정보의 **저장**은 기존 작품을 재추출하지 않습니다. 기존 작품의 **저장 및 Unit 추출**을 눌렀을 때만 활성 프롬프트로 재추출합니다. 새 Unit은 검수 대기로 추가되며 기존 Unit과 본문이 같으면 기존 행을 유지합니다.
- Gemini 설정은 기존 `GEMINI_MODEL`과 `GEMINI_CLASSIFICATION_MODEL`을 사용합니다. 추출 결과와 분류 결과를 별도로 기록하고 사용한 프롬프트와 모델을 함께 보관합니다.

## 관람객 공개 조회 및 개인화 도슨트

1. 대상 Supabase의 SQL Editor에서 [06_public_visitor_catalog.sql](sql/06_public_visitor_catalog.sql), [07_visitor_catalog_images.sql](sql/07_visitor_catalog_images.sql), [08_exhibition_artwork_order.sql](sql/08_exhibition_artwork_order.sql)을 순서대로 적용합니다. 이미 적용된 파일은 건너뜁니다. FastAPI의 공개 조회에는 `SUPABASE_PUBLISHABLE_KEY`를 사용합니다.
2. 백엔드와 프론트엔드를 실행합니다. 관람객과 관리자 API가 같은 FastAPI 서버에 있으면 기존 `VITE_ADMIN_API_URL`을 사용합니다. 관람객 API 주소가 별도라면 `VITE_VISITOR_API_URL`을 프론트엔드 환경에 설정하고 Vite를 재시작합니다.
3. 관리자 전시 상세에서 **전시 작품**의 화살표로 작품 순서를 조정하고 **순서 저장**을 누릅니다. 지정하지 않은 작품은 등록 순서대로 뒤에 표시됩니다. 전시를 공개하고 작품의 Unit을 검수 완료한 뒤 게시합니다.
4. 로그인하지 않은 브라우저에서 `http://localhost:5173/visitor`를 열고 전시 상세 하단의 **전시 관람하기**를 선택합니다. 상세의 작품 목록은 전시 순서 안내용입니다. 설문을 마치면 전시의 첫 번째 작품에서 도슨트 생성을 시작합니다. **다음 작품**은 저장된 전시 순서를 따르며 현재 탭의 응답을 재사용합니다. 관리자 전시 상세의 **관람객 화면에서 열기**로도 공개 화면을 열 수 있습니다.
5. 전시를 다시 비공개로 바꿉니다. 관람객 화면을 새로고침하면 목록에서 전시가 사라지고 기존 상세 URL은 이용할 수 없다고 표시됩니다. 화면은 포커스 복귀와 15초 간격으로도 공개 상태를 확인합니다.

도슨트 생성 요청은 선택한 작품의 게시 Unit을 다시 조회합니다. 핵심 후보가 있고 중복 제거 후 후보가 둘 이상이면 Gemini에 근거 구성을 요청합니다. WHAT이 같은 Unit을 핵심으로 삼고, 그 핵심을 관찰·기법·배경 등으로 직접 설명하는 다른 카테고리의 Unit을 최대 2개 고릅니다. 백엔드는 후보 ID, 카테고리, 핵심과 보조의 연결, 전체 개수를 검증합니다. 근거 구성에 실패하면 단어 겹침 기준으로 선택합니다. 전체 상한은 `VISITOR_DOCENT_UNIT_LIMIT`으로 설정하며 기본값은 6입니다. 핵심 근거가 없으면 다른 게시 Unit을 최대 2개 전달하고, 요청 주제를 직접 설명할 자료가 제한적임을 밝히도록 지시합니다.

게시 Unit이 없거나 작품 ID가 `VISITOR_DOCENT_REVIEW_ARTWORK_IDS`에 포함되면 생성 없이 빈 응답을 반환합니다. 기본 검토 목록에는 작품 정보와 게시 Unit의 출처가 상충하는 〈인테리어〉가 포함됩니다. 검토 완료 후 JSON 배열 설정에서 해당 ID를 제외할 수 있습니다. [해설 작성 프롬프트](app/docent.py)는 선택된 근거를 받아 관찰, 설명, 선택 주제로 이어지는 도슨트를 생성합니다. 근거 구성까지 실행하면 Gemini 요청은 총 두 건입니다. `GEMINI_DOCENT_MODEL`이 비어 있으면 `GEMINI_MODEL`을 사용합니다.

개발 환경에서 `APP_ENV=development`와 `VISITOR_DOCENT_DEBUG=true`를 함께 설정하면 응답과 Vite 개발 서버 콘솔에 설문, 모델, 생성 텍스트, 선택 방식, 핵심·보조 후보와 연결 유형, 제외 사유, Gemini가 사용했다고 보고한 Unit ID, 문장 수 추정치, 글자 수, 근거 부족 여부가 표시됩니다. 서버는 보고된 ID가 해당 역할의 후보인지 검증합니다. 근거 부족은 핵심 근거 부재 또는 모델 판정으로 표시합니다. 기본 설정은 `APP_ENV=production`, `VISITOR_DOCENT_DEBUG=false`이며 운영과 테스트 환경에서는 디버그 값을 켜도 노출되지 않습니다.

`VISITOR_DOCENT_STRATEGY_ENABLED`의 기본값은 `true`입니다. 선택이 끝난 Core·Supporting Unit을 고정한 상태에서 필수 개념과 설명 전략을 계획해 해설 요청에 추가합니다. 기존 경로가 필요하면 `VISITOR_DOCENT_STRATEGY_ENABLED=false`로 설정하세요. 새 경로에서는 CONTEXT 원문을 계획 요청에만 사용합니다. CONTEXT의 적절한 연결이 없으면 관찰 행동을 필수로 요구하지 않습니다. 계획이 실패하거나 Core가 없으면 기존 프롬프트로 확인 가능한 자료를 설명합니다.

전략 플래그와 디버그 설정을 함께 켜면 `debug.strategy_details`에 적용 상태, 필수 개념과 Core ID, 설명 전략과 Unit 참조, 그리고 생성 본문을 대조한 모델 평가가 표시됩니다. 서버는 계획의 인용 구절이 참조한 Unit 원문에 포함되는지 확인합니다. 평가는 개념별 반영 여부, 관찰 행동 실행 여부, 행동의 작품 근거 유무를 구분합니다. `assessment: null`은 평가를 받지 못했다는 뜻이고, 평가 내부의 `observation_action: null`은 필수 관찰 행동이 없었다는 뜻입니다. 전략 계획에는 Gemini 요청 1건이 추가되며, 본문 평가는 디버그에서만 1건을 추가합니다. 평가에 실패해도 응답을 자동 수정 생성하지 않습니다.

비교 실험 JSON의 문장별 근거를 점검하려면 `backend`에서 `python -m app.evaluate_docent ../docent-stability-comparison.json ../docent-sentence-audit.json`을 실행합니다. 이 명령은 기록된 답변과 선택 Unit을 동일 Gemini 모델에 보내 의미를 대조하고, 부분 근거·근거 없음·감상 안내와 미사용 Core를 구분합니다. 사용량 제한 등으로 일부 평가가 실패하면 같은 명령에 `--resume`을 붙여 입력이 동일한 성공 결과를 재사용할 수 있습니다. 모델의 평가는 별도 검토 자료이며 관람객 요청에서는 실행되지 않습니다.

## 저장된 도슨트 결과의 오프라인 평가

팀원이 이미 확보한 결과를 `docent-evaluation/v1` JSONL 형식으로 정리하면 생성 API를 다시 호출하지 않고 Core Coverage와 개인화 조건 간 표면 차이를 평가할 수 있습니다. JSONL은 한 줄에 생성 결과 하나를 저장합니다. `data_origin`은 `actual` 또는 `mock`으로 구분하며, 실제 여부는 입력 기록에 선언된 값으로 평가기가 독립 검증하지 않습니다. 확인할 수 없는 모델·프로필·Unit ID는 `null` 또는 `"unknown"`으로 남길 수 있습니다. 실제로 만든 결과가 없는 상태에서 테스트용 문장을 `actual`로 표시하지 마세요.

```json
{
  "schema_version": "docent-evaluation/v1",
  "record_id": "run-241624-why-discover",
  "data_origin": "actual",
  "comparison": {
    "pair_id": "241624-why-relax-01",
    "role": "baseline",
    "changed_factor": "why"
  },
  "artwork": {"id": "241624", "name": "Les Mains libres"},
  "profile": {"why": "discover", "what": "MEANING", "how": "Basic"},
  "selection": {
    "strategy": "unknown",
    "selected_core_unit_ids": ["241624_CU06"],
    "selected_supporting_unit_ids": ["241624_CU05"],
    "core_units": [
      {"id": "241624_CU06", "category": "MEANING", "content": "선택 당시 Core 원문"}
    ],
    "supporting_units": [
      {"id": "241624_CU05", "category": "VISUAL", "content": "선택 당시 Supporting 원문"}
    ]
  },
  "generation": {
    "status": "completed",
    "text": "기존에 저장된 실제 도슨트 설명문",
    "model": null,
    "requested_model": null,
    "used_core_unit_ids": ["241624_CU06"],
    "used_supporting_unit_ids": ["241624_CU05"],
    "evidence_insufficient": null
  },
  "provenance": {"captured_from": "existing browser response", "captured_at": null}
}
```

WHAT별 필수 Core 검수 CSV와 Supporting 쌍 검수 CSV는 작품별로 반복 지정합니다. 출력 파일이 이미 있으면 덮어쓰지 않습니다.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m app.evaluate_saved_docent_results `
  ..\docent-results.jsonl ..\docent-evaluation-report.json `
  --core-review ..\docent-241624-core-coverage-review_1차검수.csv `
  --supporting-review ..\docent-241624-core-supporting-review_1차검수.csv
```

이 평가는 저장된 선택 ID와 생성기가 보고한 사용 ID 각각의 REQUIRED Core Coverage, 선택·보고 사용 Unit ID의 일관성, 사람이 검수한 Core–Supporting 쌍 라벨을 정리합니다. `comparison.pair_id`를 공유하는 `baseline`·`variant` 두 레코드는 작품과 WHY·WHAT·HOW 중 변경 요소 하나가 일치할 때만 비교합니다. 본문 차이는 문자열 유사도·토큰 겹침 등 표면 지표로만 보고하며 의도된 개인화나 의미 품질을 판정하지 않습니다. Supporting 검수 라벨은 후보 쌍의 관련성이지 본문이 실제 근거를 사용했다는 증거가 아닙니다. Groundedness와 문장별 사실 근거 평가는 이 오프라인 명령에서 수행하지 않습니다. 기존 `app.evaluate_docent` 문장 감사는 Gemini 호출이므로 이 제한된 오프라인 평가와 별개입니다.

## 오프라인 평가 입력과 재현

평가 스크립트와 테스트는 외부 API를 호출하지 않습니다. `app.evaluate_saved_docent_results`는 `docent-evaluation/v1` JSONL을 입력으로 사용하며, 위 예시처럼 한 줄에 완전한 JSON 객체 하나를 둡니다. `data_origin`은 `actual` 또는 `mock`이고, 확인되지 않은 선택 ID·모델·프로필 값은 `null` 또는 `"unknown"`으로 기록합니다. 평가기는 `actual` 표기를 독립적으로 증명하지 않으므로 결과 출처를 확인해 입력해야 합니다.

Supporting 검수 CSV는 최소한 `artwork_id`, `core_unit_id`, `supporting_unit_id`, `relevance_label` 열이 필요합니다. 라벨은 `RELEVANT`, `NOT_RELEVANT`, `REVIEW_NEEDED`, `PENDING` 중 하나를 사용합니다. Core Coverage 검수 CSV는 `artwork_id`, `artwork_name`, `what_category`, `core_unit_id`, `core_content`, `essential_label`, `semantic_aspect`, `redundancy_group`, `review_reason`, `review_status` 열이 필요합니다. `essential_label`은 `REQUIRED`, `OPTIONAL`, `REVIEW_NEEDED`, `EXCLUDE`, `PENDING` 중 하나입니다. 평가기에 전달하는 검수 CSV는 생성문 JSONL과 별도 입력이며 자동 생성되지 않습니다.

Core–Supporting 검수 CSV 생성기는 승인된 WHAT 4-class CSV를 읽습니다. 입력에 `artwork_id`, `artwork_title`, `unit_id`, `text`, `gold_category`, `human_approval`, `new_action` 열이 있어야 합니다. 대상 작품의 `APPROVED` 및 `KEEP` 행만 사용하고, 원본 ID·본문을 보존합니다. 결과의 검수 라벨은 `PENDING`이며 기존 출력 파일은 덮어쓰지 않습니다.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m app.build_docent_selection_review_dataset `
  --input ..\WHAT_4class_Gold_approved.csv `
  --artwork-id 244623 `
  --output ..\docent-244623-core-supporting-review.csv
```

`app.evaluate_docent_core_coverage.evaluate_core_coverage(review_csv, what_category, selected_core_ids)`는 검수 CSV의 선택 Core ID에 대한 Coverage를 계산하는 라이브러리 함수입니다. Semantic Plan 구조까지 평가할 때는 `evaluate_plan_application`에 Mock 또는 기록된 계획, 후보 참조, fallback 결과를 전달합니다. 이 모듈에는 별도 CLI가 없습니다. 생성된 도슨트 JSONL에 기록된 선택 ID와 검수 라벨을 평가하려면 위의 `app.evaluate_saved_docent_results` 명령을 사용합니다.

로컬 검수 CSV나 생성문 JSONL 없이도 테스트를 실행할 수 있습니다. 테스트는 입력 CSV·JSONL을 임시 디렉터리에 생성하고, 생성/API 경로가 필요한 경우 Fake provider를 사용합니다. 전체 백엔드 테스트 실행에는 `requirements.txt` 설치가 필요하지만 `.env`, Gemini 키, 검수 데이터 파일은 필요하지 않습니다.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

전시·작품 이미지를 Supabase에서 제공하려면 해당 환경의 공개 이미지 버킷 이름을 `VISITOR_IMAGE_BUCKET`에 설정하고 기존 `cover_object_key`와 `image_object_key`에 버킷 내부 객체 경로를 사용합니다. 일치하는 Figma 예시 전시와 작품은 번들 이미지를 사용할 수 있습니다.
