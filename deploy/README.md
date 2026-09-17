# 서버에 올리기 — 어떤 방법이 있나

내 PC 에서 돌리면 **PC 가 꺼지거나 절전으로 들어가면 녹화가 안 됩니다.**
서버로 옮기는 선택지를 실제 한도·비용과 함께 정리했습니다. (2026년 9월 기준)

## 한눈에 비교

| 방식 | 비용 | 24시간 켜짐 | Zoom 녹화 | 설치 난이도 |
|---|---|---|---|---|
| 내 PC (지금) | 무료 | ✗ PC 끄면 못 함 | O | 쉬움 |
| **Oracle Cloud 무료 VM** | **0원 (영구)** | O | O | 보통 ← **추천** |
| GCP e2-micro 무료 VM | 0원 (영구) | O | △ 메모리 부족 | 보통 |
| Cloud Run Job + Scheduler | 월 ~30시간 무료 | 필요할 때만 | O | 어려움 |
| 소형 VPS (국내/해외) | 월 5,000원~ | O | O | 쉬움 |
| 무료 웹호스팅 (카페24 등) | 무료 | O | **✗ 불가능** | — |

### 무료 웹호스팅이 안 되는 이유

카페24·닷홈 같은 무료 웹호스팅은 **PHP 와 정적 파일만** 돌릴 수 있습니다.
ffmpeg 를 실행하거나 브라우저를 띄울 수 없고, 1시간짜리 프로세스를 계속 돌릴 수도 없습니다.
"웹호스팅" 과 "서버(VM)" 는 다른 물건입니다.

---

## 1. Oracle Cloud 무료 VM — 추천

신용카드 등록은 필요하지만 **평생 무료(Always Free)** 구간이 있고, 이 프로그램을 그대로 돌릴 수 있습니다.

- 2026년 6월부터 무료 한도가 **2 OCPU / 12GB (ARM)** 로 줄었습니다(이전 4 OCPU / 24GB).
- 그래도 이 프로그램에는 충분합니다. Zoom 브라우저 캡처(크로뮴 + 화면 인코딩)가 2코어면 720p 로 무리 없습니다.

```bash
# 우분투 22.04/24.04 서버에 접속한 뒤
git clone <저장소> webrec && cd webrec
bash deploy/setup-server.sh
```

끝나면 systemd 서비스로 등록되어 **재부팅해도 자동으로 살아납니다.**
웹 화면은 보안상 서버 내부에서만 열리므로, 내 PC 에서 터널로 접속합니다.

```bash
ssh -L 8765:127.0.0.1:8765 사용자@서버주소
# 브라우저에서 http://127.0.0.1:8765
```

## 2. GCP e2-micro 무료 VM

구글 클라우드에도 평생 무료 VM 이 있습니다. `us-west1` / `us-central1` / `us-east1` 리전에서만
무료이고, 디스크 30GB 를 줍니다.

다만 **1 vCPU(공유) / 1GB RAM** 이라 크로뮴을 띄우고 화면을 인코딩하는 Zoom 녹화는 버겁습니다.
YouTube 같은 **스트림 녹화 전용**이면 충분합니다(ffmpeg 가 그대로 복사만 하므로 CPU 를 거의 안 씁니다).

## 3. Cloud Run Job + Cloud Scheduler — 진짜 서버리스

"녹화할 때만 컨테이너가 떴다가 끝나면 사라지는" 구조입니다.

- Cloud Run **Job** 의 최대 실행 시간은 **168시간(7일)** 이라 1~2시간 녹화는 문제없습니다.
  (Cloud Functions 나 AWS Lambda 는 15분~1시간 제한이라 부적합합니다)
- 무료 한도: 월 **240,000 vCPU-초 + 450,000 GiB-초**.
  2 vCPU / 4GiB 로 잡으면 **월 약 30시간 녹화까지 무료**입니다.
  주 1회 1시간 웨비나면 월 4~5시간이니 충분히 무료 범위입니다.

구성은 이렇게 됩니다.

```
Cloud Scheduler (예약 시각) → Cloud Run Job 실행
    → 컨테이너가 떠서 webrec once --url ... --duration ... 수행
    → 녹화 파일을 Cloud Storage 에 업로드
    → 결과 메일 발송 후 컨테이너 종료
```

```bash
# 이미지 빌드 & 등록
gcloud builds submit --tag gcr.io/<프로젝트>/webrec .
gcloud run jobs create webrec-record \
  --image gcr.io/<프로젝트>/webrec --region us-central1 \
  --cpu 2 --memory 4Gi --task-timeout 3h \
  --command python --args "-m,webrec,once,--url,<주소>,--duration,1h,--no-preflight"
# 예약
gcloud scheduler jobs create http webrec-weekly \
  --schedule "0 23 * * wed" --time-zone Asia/Seoul \
  --uri "https://<리전>-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/<프로젝트>/jobs/webrec-record:run" \
  --oauth-service-account-email <서비스계정>
```

**단점**: 지금의 웹 화면(예약 추가/삭제)이 Cloud Scheduler 와 연동되어야 해서
추가 개발이 필요합니다. 녹화물도 컨테이너와 함께 사라지므로 Cloud Storage 업로드가 필수입니다.

## 4. 컨테이너로 돌리기 (VM + Docker)

VM 을 직접 손대기 싫으면 컨테이너로 띄워도 됩니다.

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml logs -f
```

---

## 서버로 옮기기 전에 확인할 것

**1) YouTube 는 클라우드에서 잘 막힙니다.**
유튜브는 데이터센터 IP 를 강하게 차단합니다. 새 클라우드 IP 4개 중 1개꼴로 즉시
"로그인해서 사람임을 확인하라" 는 벽에 막힌다는 보고가 있습니다.
**Zoom 웨비나는 이런 차단이 없으므로 서버 운영에 적합합니다.**
서버에서 YouTube 를 녹화하려면 쿠키를 넣어주는 등 추가 작업이 필요합니다.

**2) 저장 공간**
720p 기준 **1시간에 약 1GB** 입니다. 무료 VM 디스크(30~200GB)는 금방 찹니다.
오래된 파일을 지우거나 구글 드라이브 등으로 옮기세요.

```bash
# 30일 지난 녹화 파일 정리 (crontab -e 에 추가)
0 4 * * * find /home/ubuntu/webrec/recordings -name '*.mkv' -mtime +30 -delete
```

**3) 웹 화면을 인터넷에 그대로 열지 마세요**
`--host 0.0.0.0` 으로 열면 예약 목록과 녹화 파일이 누구에게나 보입니다.
기본값(127.0.0.1) 그대로 두고 SSH 터널로 접속하는 것이 안전합니다.

**4) GitHub Actions 는 쓰지 마세요**
6시간까지 무료로 돌릴 수 있어 가능해 보이지만, "소프트웨어 개발과 무관한 용도" 를
금지하는 약관 위반입니다. 계정이 정지될 수 있습니다.

**5) 사내 정책**
회사 Zoom 웨비나를 외부 클라우드 서버로 녹화·저장하는 것이 사내 보안 정책에
문제되지 않는지 확인해 주세요.
