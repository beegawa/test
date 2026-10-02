# AX 앱 센터

법인·팀이 AI 코딩 도구로 만든 업무 프로그램을 한 곳에 등록하고, 위험 등급에 따라 검토하고, 전 법인이 찾아 쓸 수 있게 하는 SharePoint 기반 시스템이다.
새 화면 개발 없이 SharePoint 커뮤니케이션 사이트 + Microsoft Lists + Lists 양식 + Power Automate(표준 커넥터)로 만든다.

- 기획서: [docs/spec.md](docs/spec.md)
- 작업 지침: [CLAUDE.md](CLAUDE.md)
- 직원용 안내: [docs/user-guide.md](docs/user-guide.md) · GBI팀용 안내: [docs/admin-guide.md](docs/admin-guide.md)
- 양식 만들기: [docs/manual-form.md](docs/manual-form.md) · 흐름: [F1](docs/flows/F1-intake.md), [F2](docs/flows/F2-change-request.md), [F3](docs/flows/F3-review-reminder.md)
- 검증 기록: [docs/verification-log.md](docs/verification-log.md)

## 준비

| 항목 | 요구 사항 |
|---|---|
| PowerShell | 7.4.0 이상 |
| 모듈 | `Install-Module PnP.PowerShell -Scope CurrentUser` |
| 앱 등록 | IT가 한 번: `Register-PnPEntraIDAppForInteractiveLogin -ApplicationName "PnP.PowerShell" -Tenant <tenant>.onmicrosoft.com` → Application(client) ID를 받는다 |
| 권한 | SharePoint 사이트를 만들 수 있는 계정 |

## 실행 순서

```powershell
cd ax-app-center
Copy-Item config/config.sample.json config/config.json   # 값을 채운다 (기획서 9장). environment 는 test 로 시작
cd scripts

./99-verify.ps1 -Offline          # 연결 없이 설정·설계·등급 수식 점검
./deploy.ps1 -WhatIf              # 연결 없이 실행 계획 확인
./deploy.ps1                      # 대화형 로그인 → 01 사이트 ~ 05 페이지
./06-seed-test-data.ps1           # 등급 테스트 항목 7건 (test 환경만)
./99-verify.ps1                   # 완료 기준 점검
```

그다음 사람이 화면에서:

1. [docs/manual-form.md](docs/manual-form.md) 대로 Lists 양식 2개를 만들고 홈 버튼 링크를 바꾼다.
2. [docs/flows/](docs/flows/) 대로 흐름 F1~F3을 만든다.
3. 기획서 7.2·7.3의 사람 확인 항목을 점검하고 [docs/verification-log.md](docs/verification-log.md)에 적는다.

전수 조사 결과를 넣을 때:

```powershell
./07-import-survey.ps1 -CsvPath ../data/<파일>.csv -WhatIf   # 파일 검사만
./07-import-survey.ps1 -CsvPath ../data/<파일>.csv
```

운영 배포: 사람이 `config.json`의 `environment`를 `prod`로 바꾼 뒤 `./deploy.ps1 -ConfirmProd`.

## 설정 (`config/config.json`)

`config.sample.json`의 항목에 더해 다음을 쓸 수 있다.

| 키 | 기본 | 뜻 |
|---|---|---|
| `permissions.visitorsCanSubmit` | `false` | 8장 대안. 읽기 권한만으로 양식 제출이 안 될 때 `true`로 바꾸면 방문자에게 등록부·변경 신청 기여 권한을 주고 쓰기 보안을 `WriteOnlyMyItems`로 둔다. 이때 F1에 되돌림 처리가 필요하다 |
| `includeRpa` | `true` | D9. `false`면 `형태` 선택지에서 RPA를 뺀다 (이미 만든 선택지는 지우지 않음) |
