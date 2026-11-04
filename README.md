# evidence-code-review

Claude Code 스킬. 코드와 테스트를 근거 중심으로 리뷰한다. 결함(defect), 검증 공백(assurance gap), 요구사항 불명(contract unknown)을 섞지 않고 따로 보고한다.

리뷰는 세 축으로 본다.

| 축 | 묻는 것 |
|---|---|
| direction | 변경이 근거 있는 계약(요구사항·API·보안 불변조건)에 맞는가 |
| execution | 정상·부정·경계·동시성·오류 경로에서 실제로 맞게 동작하는가 |
| verification | 테스트가 맞는 동작과 틀린 동작을 구분해 내는가 |

저장소를 고치지 않는다. 수정, 테스트 추가, 커밋, 설치를 하지 않고 읽기와 안전한 로컬 검사만 한다.

## 리뷰 종류와 모드

- **diff 리뷰**: PR, 커밋, diff, base/target을 받는다. 변경이 새로 만들었거나 새로 드러낸 결함만 보고한다.
- **snapshot 리뷰**: 변경 없이 파일·모듈·함수를 지정받는다. 지정 영역의 현재 코드를 보고, 결함이 어느 변경에서 생겼는지는 주장하지 않는다.
- **Verify 모드**: 다른 리뷰어나 도구가 낸 후보 결함을 하나씩 코드로 확인한다. 판정은 네 가지다.

| 판정 | 조건 |
|---|---|
| `confirmed` | 전제가 참이고, 도달 가능하며, 근거 있는 계약에 어긋난다 |
| `plausible` | 전제와 도달 경로는 확인했지만 계약이 불명확하거나 트리거가 증명되지 않았다 |
| `rejected` | 전제가 거짓이거나, 도달할 수 없거나, 독립 근거가 있는 계약이 그 동작을 허용한다 |
| `unverified` | 확인에 필요한 근거(저장소, 커밋, 파일, 호출 경로)에 접근하지 못했다 |

## 구성

```
SKILL.md                              스킬 본문
references/finding-contract.md        보고 형식, JSON 스키마 1.2
references/three-quality-lenses.md    세 축의 판단 기준과 예시
references/test-quality.md            테스트 오라클, matcher 함정, 반례
references/verification-playbook.md   위험 유형별 확인 경로, 허용되는 실행 범위
scripts/validate_review.py            JSON 결과 구조 검증기
tests/test_validate_review.py         검증기 회귀 테스트
```

## 설치

`~/.claude/skills/evidence-code-review/`에 이 폴더를 복사한다. 리뷰를 요청하거나 `/evidence-code-review`로 부른다.

```bash
rsync -a --delete --exclude .git --exclude tests ./ ~/.claude/skills/evidence-code-review/
```

## JSON 결과 검증

자동화용 결과는 `references/finding-contract.md`의 스키마 `1.2`를 따른다. 검증기는 필드 구조와 내부 일관성만 검사한다. 주장한 결함이 실제로 있는지는 검사하지 않는다.

```bash
python3 scripts/validate_review.py review.json
```

종료 코드는 0(유효), 1(구조 오류), 2(파일을 읽을 수 없음)이다. 1.1 문서도 1.1 규칙으로 받지만, 새로 만드는 결과는 1.2로 쓴다.

검증기 테스트는 계약 문서의 JSON 예시를 픽스처로 쓴다. 문서와 검증기가 어긋나면 테스트가 깨진다.

```bash
python3 -m unittest discover -s tests
```

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

eval 작업 공간은 `~/.claude/skills/evidence-code-review-workspace/`에 있다. 실제 커밋 2건과 픽스처 1건으로 블라인드 채점을 했다. 마지막 기록은 iteration-9(0.3.5, effort medium/high 비교)다.

0.4.0은 iteration-10에서 측정했다. Verify 모드에서 확인하지 못한 후보를 `plausible`로 올리는 경우가 13건에서 2건으로 줄었고, JSON-only 결과는 후보를 빠짐없이 담았다. 단일 리뷰 품질은 n=3에서 구분되지 않았다. 같은 날 다시 돌린 0.3.5도 외부에서 SDK 소스를 받아 왔으므로, 이 동작은 버전이 아니라 실행 환경 변화에서 왔다(iteration-13). 0.4.1은 이를 막는 문장을 추가했고, 0.4.1 run 9건에서 웹 호출은 0건이었다.
