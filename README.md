# evidence-code-review

코드와 테스트를 근거로 리뷰하는 Claude Code 스킬이다. 리뷰 결과를 세 묶음으로 나눠 보고한다.

| 묶음 | 뜻 |
|---|---|
| Findings | 재현 경로와 계약 근거가 있는 결함 |
| Assurance gaps | 버그라고 단정할 근거는 없지만, 어떤 테스트도 맞고 틀림을 가려내지 못하는 동작 |
| Contract unknowns | 요구사항이 없거나 서로 어긋나서 판단할 수 없는 지점 |

"테스트가 없다"는 assurance gap이고, "이 입력에서 다른 사용자 주문이 보인다"는 finding이다.

스킬은 저장소를 고치지 않는다. 읽기, 이미 있는 테스트 같은 안전한 로컬 검사만 하고 수정·테스트 추가·커밋·의존성 설치·네트워크 조회는 하지 않는다.

## 설치

```bash
rsync -a --delete --exclude .git --exclude tests --exclude docs ./ ~/.claude/skills/evidence-code-review/
```

설치된 버전은 `~/.claude/skills/evidence-code-review/SKILL.md`의 `metadata.version`에서 확인한다.

## 사용

리뷰를 요청하거나 `/evidence-code-review`로 부른다. 요청에 무엇을 넣느냐에 따라 동작이 셋으로 갈린다.

| 요청 | 동작 | 보고 범위 |
|---|---|---|
| PR, 커밋, diff, base/target, "작업 중인 변경" | diff 리뷰 | 변경이 새로 만들었거나 새로 드러낸 결함 |
| 파일·모듈·함수·`path:line` 범위 (변경 없음) | snapshot 리뷰 | 지정 영역에 지금 있는 결함. 어느 변경에서 생겼는지는 주장하지 않는다 |
| 다른 리뷰어·도구가 낸 후보 결함 목록 | Verify 모드 | 후보마다 판정 하나 |

```text
/evidence-code-review HEAD~1..HEAD
이 PR 리뷰해줘: https://github.com/org/repo/pull/123
src/billing/refund.ts 의 refund() 테스트 품질 봐줘
아래 리뷰 코멘트들이 진짜 버그인지 검증해줘 (목록 붙여넣기)
```

범위를 정하지 못하면 결론을 `incomplete`로 낸다. 결함을 찾지 못했다는 결과는 "확인 가능한 결함을 발견하지 못했습니다"로 나온다. 이 문구를 안전하다는 보증으로 읽으면 안 된다.

### 리뷰 축

모든 리뷰는 세 축으로 본다. 각 축의 결론은 `supported` / `risk` / `unknown` 중 하나다. `supported`는 살펴본 범위 안에서 근거가 그 주장을 뒷받침한다는 뜻이다.

| 축 | 묻는 것 |
|---|---|
| direction | 변경이 근거 있는 계약(요구사항, API, 보안 불변조건)에 맞는가 |
| execution | 정상·부정·경계·동시성·오류 경로에서 실제로 맞게 동작하는가 |
| verification | 테스트가 맞는 동작과 틀린 동작을 구분해 내는가 |

### Verify 모드 판정

| 판정 | 조건 |
|---|---|
| `confirmed` | 전제가 참이고, 도달할 수 있고, 근거 있는 계약에 어긋난다 |
| `plausible` | 전제와 도달 경로는 확인했지만 계약이 불명확하거나 트리거가 증명되지 않았다 |
| `rejected` | 전제가 거짓이거나, 도달할 수 없거나, 독립 근거가 있는 계약이 그 동작을 허용한다 |
| `unverified` | 확인에 필요한 근거(저장소, 커밋, 파일, 호출 경로)에 접근하지 못했다 |

후보의 심각도나 문구는 물려받지 않는다. `unverified` 후보가 하나라도 있으면 결론은 `no_actionable_findings`가 될 수 없다. 저장소 밖(네트워크, 다른 프로젝트의 의존성)에서 근거를 가져와 `unverified`를 메우지도 않는다.

## JSON 결과와 검증기

자동화에 넘길 결과는 [references/finding-contract.md](references/finding-contract.md)의 스키마 `1.2`를 따른다. Verify 모드 판정은 `candidate_verdicts` 배열로, 리뷰 종류는 `scope.kind`(`diff` | `snapshot`)로 들어간다.

```bash
python3 scripts/validate_review.py review.json
```

| 종료 코드 | 뜻 |
|---|---|
| 0 | 유효 |
| 1 | 구조 오류 (오류 목록 출력) |
| 2 | 파일을 읽을 수 없음 (없는 파일, JSON 아님, UTF-8 아님) |

검증기는 필드 구조와 내부 일관성만 본다. 주장한 결함이 실제로 있는지는 보지 않는다. 검사 규칙 예:

- `confirmed` 판정은 실제로 있는 finding id를 가리킨다.
- `plausible`과 `unverified`에는 `limitation`이 있다.
- snapshot 리뷰에는 `target`이 있고 `base`가 없다.

`schema_version: "1.1"` 문서도 1.1 규칙으로 받는다. 새 결과는 1.2로 쓴다.

## 프로젝트 구조

```text
SKILL.md                              스킬 본문. 리뷰 절차, Verify 모드, 최종 응답 형식
references/finding-contract.md        보고 형식, 심각도 P0–P3, JSON 스키마 1.2
references/three-quality-lenses.md    세 축의 판단 기준과 예시
references/test-quality.md            테스트 오라클, matcher 함정, 반례 작성
references/verification-playbook.md   위험 유형별 확인 경로, 허용되는 실행 범위
scripts/validate_review.py            JSON 결과 구조 검증기
tests/test_validate_review.py         검증기 회귀 테스트
docs/audits/                          프롬프트 감사 보고서와 패치
```

`tests/`와 `docs/`는 설치하지 않는다. 스킬 실행에 필요한 것은 `SKILL.md`, `references/`, `scripts/`다.

## 수정하기

### 검증기 테스트

```bash
python3 -m unittest discover -s tests
```

테스트는 `finding-contract.md`의 JSON 예시를 픽스처로 읽는다. 계약 문서의 예시나 필드를 바꾸면 검증기와 테스트를 같이 바꿔야 한다. 어느 한쪽만 바꾸면 테스트가 깨진다.

### 릴리스 순서

1. `SKILL.md`의 `metadata.version`을 올린다.
2. 스키마를 바꿨다면 `finding-contract.md`의 버전 절, `validate_review.py`의 `SCHEMA_VERSIONS`, 테스트를 함께 고친다.
3. 아래 버전 표에 한 줄을 추가한다.
4. 커밋하고 `v<버전>` 태그를 단다.
5. 설치 명령으로 `~/.claude/skills/`에 반영한다.

### eval

eval 작업 공간은 저장소 밖 `~/.claude/skills/evidence-code-review-workspace/`에 있다. 실제 커밋 리뷰 2건, Verify 모드 1건, snapshot 픽스처 1건을 블라인드로 채점한다. 결과와 판단은 `iteration-N/notes.md`에 남긴다.

eval 하위 에이전트는 설치된 스킬을 Skill 도구로 불러온다. 그래서 한 번에 한 버전만 측정할 수 있다. 비교하는 버전은 `skill-snapshot-<버전>` 디렉터리에서 차례로 설치한다.

두 버전을 비교할 때는 같은 세션에서 기준 버전도 새로 돌린다. 예전 iteration의 결과를 다시 채점해 기준으로 쓰면 그 사이 생긴 모델·도구 환경 변화가 버전 차이처럼 보인다. iteration-13에서 실제로 이 일이 있었다.

## 버전

| 버전 | 변경 |
|---|---|
| 0.4.1 | `unverified` 근거를 저장소 밖(네트워크, 다른 프로젝트 의존성)에서 채우지 않도록 명시 |
| 0.4.0 | `unverified` 판정, JSON `candidate_verdicts`, snapshot 리뷰(`scope.kind`), 스키마 1.2, 테스트 읽기 순서 강제 제거, 비 UTF-8 입력 처리 |
| 0.3.5 | 부정 테스트 예시 문장 보강 |
| 0.3.4 | 1.0 스키마 설명 정리, lenses 예시를 멱등 결제로 교체 |
| 0.3.3 | `rejected`를 독립 계약 근거로 제한, outcome 누락은 계약 근거가 있을 때만 assurance gap, outcome 목록은 검사했을 때만 보고, 검증기 enum 타입 방어 |
| 0.3.2 | 형제 outcome 열거(sibling-outcome check) |
| 0.3.1 | assertion 깨보기, Matcher traps |
| 0.3.0 | Verify 모드 |
| 0.2.8 | 초기 스냅샷 (producer/consumer 추적 포함) |

## 평가 현황

0.4.0은 iteration-10에서 측정했다. Verify 모드에서 확인하지 못한 후보를 `plausible`로 올린 경우가 13건에서 2건으로 줄었다. JSON-only 결과에는 후보가 빠짐없이 들어갔다. 단일 리뷰 품질은 n=3에서 0.3.x와 구분되지 않았다.

iteration-10–12에서 0.4.x의 admin 케이스 결과가 나빠 보였다. iteration-13에서 같은 날 0.3.5를 다시 돌렸더니 거짓 주장 증가, 심각도 과장, 외부 SDK 소스 조회가 똑같이 나왔다. 원인은 실행 환경 변화다.

0.4.1에 경계 문장을 넣은 뒤 run 9건의 웹 호출은 0건이었다. 같은 날 0.3.5는 3건 중 1건이었다.
