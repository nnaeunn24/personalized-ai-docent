# WHY·HOW 프롬프트 실험 준비 보고서

## 구현 파일

- [docent_personalization_prompt_experiment.py](backend/app/docent_personalization_prompt_experiment.py): 현재 서비스의 전략·생성 프롬프트를 기준선으로 조합하고, 제안된 WHY·HOW 지침을 덧붙인 개선안을 생성한다. 서비스 코드에서는 import하지 않는다.
- [test_docent_personalization_prompt_experiment.py](backend/tests/test_docent_personalization_prompt_experiment.py): 8개 WHY×HOW 조합, 기준선 보존, 선택 근거 유지, Mock 입력 처리 등을 검증한다.

## 기존 대비 변경

- 기준선은 서비스와 같은 조합이다: 생성은 `DOCENT_PROMPT + HOW_FOCUS`; 전략을 적용한 경우에는 `STRATEGY_GENERATION_RULES + CONTENT_RULES`가 더해진다. 계획 프롬프트 기준선은 `AUTOMATIC_PROMPT + DOCENT_PLANNING_RULES`다.
- 개선안은 기준선을 삭제하거나 교체하지 않고, WHY별 관찰 목적·전개·행동, HOW별 난이도·깊이·Core 보존 지침을 추가한다.
- 제안된 길이( Basic 450–750자, Advanced 700–1,100자 및 문장 수)는 프롬프트 안에서도 **실험 가설**로 표시하며 Core 보존이나 근거 충실도보다 우선하지 않는다.
- 선택된 Core/Supporting, supporting links, 필수 내용은 비교 조건마다 입력에서 보존한다. 개선안은 Unit 선정 로직에 관여하지 않는다.

## 오프라인 검증 범위

Mock 테스트는 4 WHY×2 HOW의 8개 프로필을 만들고 각 프로필의 기준선·개선안을 비교한다. 프롬프트 문자열과 입력 데이터 구성 및 evidence 보존만 검증한다. 생성 호출을 수행하지 않으므로 결과 품질이나 WHY/HOW 차별성 자체를 증명하지 않는다.

실행 명령:

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest tests.test_docent_personalization_prompt_experiment -v
```

## 서비스 반영 전 검증 사항

1. 생성문과 선택·사용 Unit을 함께 수집해 같은 조건에서 기준선과 개선안을 비교한다.
2. WHY별 적합성·구분성, Basic/Advanced 적합성, 검수된 REQUIRED Core 보존, Unit에 근거하지 않은 주장을 사람이 평가한다. 표면적 문장 차이만으로 성공을 판정하지 않는다.
3. 선택 evidence를 고정한 HOW 비교와, HOW가 Semantic Plan의 선택에도 영향을 주는 end-to-end 비교를 분리한다.
4. 제안한 분량 범위가 실제 작품별 Core 정보를 담는지 확인하고 조정한다. 길이 목표를 위해 Core 누락을 허용하지 않는다.
5. 새로운 지침이 기존 생성 스키마, Unit ID 검증 및 Core Coverage 검증과 충돌하지 않는지 서비스 통합 단계에서 별도 확인한다.

현재 구현은 오프라인 문자열·Mock 입력 검증에 한정된다. 실제 Gemini 생성, 근거의 의미적 정확성, 개인화 품질은 검증하지 않았다.
