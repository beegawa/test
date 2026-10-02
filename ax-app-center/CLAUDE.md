# AX 앱 센터 — 작업 지침

시민개발 프로그램 등록·관리 시스템 (Microsoft 365 기반). 전체 기획은 `docs/spec.md`.
이 폴더(`ax-app-center/`)에서 작업할 때 아래 원칙을 지킨다. (기획서 0장)

## 원칙

- **새 화면을 개발하지 않는다.** 웹앱, SPFx, Power Apps, 프리미엄 커넥터를 쓰지 않는다. SharePoint 사이트, Microsoft Lists, Lists 양식, Power Automate 표준 커넥터만 쓴다.
- **스크립트는 멱등하게 쓴다.** 두 번 실행해도 결과가 같아야 한다. 대상이 있으면 건너뛰거나 갱신하고, 지우고 다시 만들지 않는다.
- **삭제는 하지 않는다.** 사이트, 목록, 열, 항목을 지우는 코드는 넣지 않는다. 필요하면 사람에게 요청한다.
- **테스트 사이트에서 먼저 돌린다.** `config.json`의 `environment`가 `test`일 때는 URL 끝에 `-test`가 붙은 사이트에만 쓴다. 운영 배포는 사람이 `prod`로 바꾼 뒤에만 한다 (`deploy.ps1 -ConfirmProd`).
- **비밀 값을 저장소에 넣지 않는다.** 로그인은 대화형으로만 한다. 인증서, 클라이언트 시크릿, 비밀번호를 파일에 쓰지 않는다. `config/config.json`은 `.gitignore` 대상이다.
- **cmdlet 매개변수는 설치된 버전에서 확인한다.** 실행 전에 `Get-Help <cmdlet> -Full`로 확인한다.
- **확인하지 못한 사항**(기획서 8장)은 구현 중 직접 검증하고 결과를 `docs/verification-log.md`에 남긴다.
- **사람이 정할 값**(기획서 9장)이 비어 있으면 추측하지 말고 물어본다. 스크립트도 `config.json`에 `<...>` 자리 표시 값이 남아 있으면 멈춘다.
- **앱 등록은 IT가 한 번만 한다.** `clientId`가 비어 있으면 멈추고 안내한다. `Register-PnPEntraIDAppForInteractiveLogin`을 대신 실행하지 않는다.

## 구조

| 경로 | 내용 |
|---|---|
| `scripts/lib/common.ps1` | 설정 읽기·검증, 연결, 로깅, 안전 장치(`Assert-AxSafeTarget`) |
| `scripts/lib/schema.ps1` | 설계 정의: 목록·열·선택지·보기·등급 수식·테스트 사례·CSV 머리글. **설계를 바꿀 때는 여기만 고친다** |
| `scripts/lib/formula.ps1` | 등급 수식 해석기 (오프라인 점검용) |
| `scripts/01~05-*.ps1` | 사이트, 목록·열, 보기, 권한, 페이지 |
| `scripts/06-seed-test-data.ps1` | 등급 테스트 항목 (test 환경에서만) |
| `scripts/07-import-survey.ps1` | 전수 조사 CSV 가져오기 |
| `scripts/99-verify.ps1` | 완료 기준 점검 (`-Offline`은 연결 없이) |
| `scripts/deploy.ps1` | 한 번 연결하고 01~05 실행 |
| `docs/` | 양식·흐름 절차서, 안내서, 검증 기록 |

## 작업 규칙

- 단계 스크립트는 모두 `-WhatIf`를 지원한다. `-WhatIf`면 연결하지 않고 실행 계획만 출력한다.
- 쓰기 전에 `Assert-AxSafeTarget`을 호출한다.
- 새 점검을 추가하면 `99-verify.ps1`에 넣고 `./99-verify.ps1 -Offline -ConfigPath ../config/config.sample.json`이 통과하는지 본다.
- 스크립트는 `Set-StrictMode -Version 3.0`에서 돈다. 해시테이블의 없는 키를 속성처럼 읽지 않는다.
- 로그는 `logs/`(저장소 제외)에 남는다.
