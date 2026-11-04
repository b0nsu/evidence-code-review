# Prompt audit: evidence-code-review 0.4.0

감사일 2026-11-04. 제안 diff는 [prompt-audit-v0.4.0.patch](prompt-audit-v0.4.0.patch)에 있고 적용하지 않았다.

## 가정

- **범위**: `SKILL.md`, `references/` 4개 파일. `scripts/validate_review.py`는 모델에 들어가는 텍스트가 아니어서 제외했다. `README.md`와 `tests/`는 스킬 실행 때 읽히지 않는다.
- **대상 모델**: Claude Opus 5.5. 스킬이 모델을 고정하지 않아서 이 감사를 실행한 모델로 잡았다.
- **이력**: git 저장소는 커밋이 없다. 대신 `~/.claude/skills/evidence-code-review-workspace/`의 0.2.8–0.3.4 스냅샷과 eval grader로 각 줄이 들어온 시점과 이유를 추적했다.
- **모델별 API 근거**: `shared/model-migration.md`가 로컬에 없다. 그래서 모델별 동작에 기대는 주장은 낮은 확신도의 flag로만 남겼다.

## 요약

가장 영향이 큰 발견은 0.4.0에서 snapshot 리뷰를 추가하면서 생긴 내부 모순이다. `SKILL.md`는 snapshot 리뷰에서 지정 영역에 이미 있는 결함을 범위로 정의한다. 그런데 `references/`와 `SKILL.md`의 검사 규칙은 여전히 "changed tests", "changed test lines", "pre-existing 제외"로 쓰여 있다. 이대로면 snapshot 리뷰에서 assertion 깨보기와 `test_defect` 보고가 규칙상 불가능하다.

구식 프롬프트 패턴은 거의 없다. 대문자 강조, think-step-by-step, 출력 길이 상한, 갱신 억제 문구는 0건이다. 반복되는 금지 규칙에는 대부분 이유가 붙어 있고, 실제로 지켜야 할 제약이다.

| 그룹 | 결과 |
|---|---|
| 1 Dated prompt text | 0건 (flag 2) |
| 2 Skill/config files | 2건 (high 1, medium 1), flag 2 |
| 3 Tool descriptions | 해당 없음 (frontmatter `description`은 trigger 텍스트로 2그룹에서 봤다) |
| 4 Request config | 해당 없음 (요청 생성 코드, 서브에이전트 정의 없음) |

## 발견

### A1 — snapshot 리뷰와 diff 전용 문구의 충돌

- **위치**:
  - 범위 정의: `SKILL.md:20`, `SKILL.md:37`
  - diff 전용 문구: `SKILL.md:54`, `SKILL.md:64`, `SKILL.md:70`, `references/three-quality-lenses.md:23`, `references/test-quality.md:11`, `references/verification-playbook.md:3`, `:19`, `:25`
- **근거**:
  - `SKILL.md:20`은 "in a snapshot review they are defects present in the named code area as it stands"라고 정의한다.
  - 반면 `three-quality-lenses.md:23`은 "Require changed test lines and concrete counterexample"을 요구한다.
  - `test-quality.md:11`은 "Actionable `test_defect` if the erroneous test is within the review change"로 제한한다.
  - `verification-playbook.md:25`는 "unrelated pre-existing issues"를 결함에서 뺀다.
  - `SKILL.md:54`는 "For changed tests, try to break each assertion"으로, 바뀐 테스트에만 이 검사를 적용한다.
- **패턴**: Group 2, 같은 사안에 서로 다른 규칙을 두는 지시 파일.
- **이유**: snapshot 리뷰에는 바뀐 줄이 없다. 지금 문구대로면 verification 축의 핵심 검사(assertion 깨보기)가 돌지 않고, `test_defect`는 보고 자체가 막힌다. 어느 쪽이 최신인지는 이력으로 알 수 있다. snapshot 규칙은 0.4.0에서 추가됐고, diff 전용 문구는 0.2.8 스냅샷부터 있었다. 파일 수정 시각이 아니라 버전 스냅샷 간 diff로 판단했다.
- **확신도**: High. 저장소 안의 두 문장이 직접 모순된다.
- **조치**: `rewrite`. 파일 8곳을 각각 고치는 대신, `SKILL.md:49`의 리뷰 종류 규칙에 다음 한 문장을 붙인다.
  - "In a snapshot review, read "the change", "changed tests" and "changed entry point" in this file and in `references/` as the named area, the tests that cover it, and its entry points; defects already present in the named area are in scope."
  - `SKILL.md`는 스킬이 실행될 때 항상 읽히므로 references를 나중에 열어도 이 해석 규칙이 함께 적용된다.
  - diff 리뷰의 기존 규칙은 그대로 둔다. 이 문장은 금지를 풀지 않고, snapshot에서 그 규칙이 무엇을 가리키는지만 정한다.

### A2 — 최종 응답 범위 항목의 "exact base"

- **위치**: `SKILL.md:80`
- **근거**: "Scope, performed checks, and limitations: exact base, files, ..."
- **패턴**: Group 2, Volatile specifics. 같은 변경 안에서 문구가 서로 어긋났다.
- **이유**: snapshot 리뷰에는 base가 없다. `references/finding-contract.md:11`은 이미 "exact diff or reviewed revision"으로 고쳐져 있어서 두 파일의 범위 보고 지시가 다르다.
- **확신도**: Medium.
- **조치**: `rewrite`. "exact base (or the reviewed revision in a snapshot review), files, ..."

## Flag (diff 없음)

### L1 — 단일 사건에서 나온 규칙의 과적합 가능성

- **위치**: `SKILL.md:51`, `SKILL.md:52`, `SKILL.md:54`
- **패턴**: Group 1d Patch accretion, Group 2 recency trap.
- **내용**:
  - producer 추적(`:51`)에 대응하는 grader는 sentry 04다.
  - 형제 outcome 열거(`:52`)에 대응하는 grader는 sentry 02·03이다.
  - assertion 깨보기(`:54`)에 대응하는 grader는 sentry 05와 analytics 01–03이다.
  - 대응 관계는 grader 이름과 스냅샷 추가 시점으로 추정했다. 인과는 확인하지 않았다.
  - 세 규칙 모두 문구는 일반 원칙으로 쓰였다. 다만 규칙과 대응하는 사례가 곧 eval 사례다. 표본 밖 근거는 admin 커밋 하나뿐이다.
- **판단**: 지금 eval 집합으로는 일반화된 규칙인지 과적합인지 구분할 수 없다. 삭제 근거도 없다.
- **확인 방법**: 규칙을 만들게 하지 않은 실제 커밋 2–3건을 hold-out으로 두고, 각 줄을 빼고 돌려 본다.
- **확신도**: Low.

### L2 — 탐색 범위를 줄이는 문장

- **위치**: `SKILL.md:26` "Read the smallest relevant ... and deepen on risk", `SKILL.md:57` "Stop expanding when material candidates have been checked"
- **패턴**: Group 1d, 모델 세대별 scope·over-verification 지시.
- **내용**: 이 문장들이 어느 모델을 겨냥해 쓰였는지 근거가 없다.
  - iteration-9 결과는 반대 방향을 가리킨다. effort를 medium으로 낮추자 가장 어려운 항목의 recall이 떨어졌다(sentry 01: 2/3 → 0/3).
  - 탐색을 줄이라는 문장이 recall을 깎는지는 측정하지 않았다.
- **확인 방법**: 두 문장을 뺀 ablation을 돌린다.
- **확신도**: Low.

### L3 — frontmatter description의 trigger 겹침 (프로젝트 밖)

- **위치**: `SKILL.md:5-13`
- **내용**: 같은 세션에 "code review"로 발동하는 스킬이 셋 더 있다. `code-review`, `engineering:code-review`, `oh-my-claudecode:review`는 사용자 레벨 설정이라 이 감사 범위 밖이다.
- **판단**: description에 들어 있는 판정 목록(`confirmed / plausible / rejected / unverified`)은 어느 스킬로 보낼지 정하는 데 쓰이지 않는다. 다른 스킬과 구분해 주는 것은 "evidence-first, test-oracle" 같은 차별점이다. trigger eval 없이 문구를 바꾸면 추측이 된다.
- **확신도**: Low.

### L4 — 모델에 필요 없는 문장

- **`references/three-quality-lenses.md:3`**: "not a validated three-factor quality law or an existing project's formal standard"는 아무도 하지 않은 반박에 답하는 문장이다. 사람 독자를 향한 말이고, 모델이 리뷰 결과에 이 단서를 옮겨 적을 수 있다.
- **`references/finding-contract.md:115`**: 1.1 하위 호환을 설명하는 문장은 소비자용 정보다. 모델에 필요한 것은 "Emit 1.2" 하나다.
- **확신도**: Low. 해가 확인되지 않았다.

## 지적하지 않고 둔 것

- **금지 목록** (`SKILL.md:24`, `:25`, `references/verification-playbook.md:29`): 읽기 전용 경계, prompt injection 방어, migration·설치·외부 호출 금지. 실제 안전 제약이고 이유가 붙어 있다.
- **mutation testing 승인 조건 3회 반복** (`SKILL.md:28`, `references/test-quality.md:37`, `references/verification-playbook.md:29`): 세 곳 내용이 일치한다. 작동하는 중복이므로 둔다.
- **"테스트가 없는 것은 결함이 아니다" 다중 서술** (`SKILL.md:55`, `references/test-quality.md:13`, `:52`, `references/verification-playbook.md:25`, `references/finding-contract.md:13`): 서로 어긋나지 않는다.
- **JSON 예시와 verify 예시** (`references/finding-contract.md`): 형식이 중요한 출력을 고정하는 예시다. "example document"라고 표기돼 있다.
- **고정 문구 `확인 가능한 결함을 발견하지 못했습니다`** (`SKILL.md:80`): 작성자가 정한 출력 형식이다.

## 검증

- A1·A2 관련 경로와 문구는 파일을 직접 읽어 확인했다. `references/*.md` 4개와 `scripts/validate_review.py`, `references/test-quality.md`의 "Matcher traps" 절이 모두 존재한다.
- `git apply --check`로 patch가 깨끗하게 적용되는 것을 확인했다.
- 모델 행동 비교(patch 적용 전과 후)는 돌리지 않았다. A1이 snapshot 리뷰를 실제로 바꾸는지는 snapshot eval 사례를 만들어야 확인할 수 있다.
