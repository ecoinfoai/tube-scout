# Quickstart: yt-dlp 자막·음원·지문 어댑터 (운영자 가이드)

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)
**Audience**: 운영자(DX센터장) — 단일 사용자, 자교 22채널 owner

---

## 1회 셋업 (spec X1 머지 직후)

### 1.1 의존성 sync

```bash
cd ~/localgit/tube-scout
git checkout master && git pull
nix develop                       # devShell 진입 — yt-dlp / chromaprint / ffmpeg / LD 자동
uv sync                           # Python 의존성 (yt-dlp + pyacoustid 추가됨)
tube-scout --version              # v0.4.0 확인
```

### 1.2 Brave 인증 확인

```bash
yt-dlp --cookies-from-browser brave --write-auto-subs --skip-download \
       --output /tmp/auth-test.%(ext)s \
       "https://youtu.be/<자교 영상 ID>"
# stdout 에 "Extracted N cookies from brave" 가 N>500 이면 OK.
# "Failed to decrypt cookies" 면 1.3 으로.
```

### 1.3 (조건부) cookies.txt 폴백 준비

Brave keyring 디크립션 실패하거나 cron(headless) 환경에서:

1. Brave에 "Get cookies.txt LOCALLY" 확장 설치.
2. youtube.com 방문 → 확장 아이콘 → "Export"
3. 저장:
   ```bash
   mkdir -p ~/.config/tube-scout
   mv ~/Downloads/youtube.com_cookies.txt ~/.config/tube-scout/cookies.txt
   chmod 600 ~/.config/tube-scout/cookies.txt
   ```
4. 검증: `tube-scout collect transcripts --source ytdlp --channel <alias> --cookies-file ~/.config/tube-scout/cookies.txt --force`

### 1.4 (선택) v0.4 운영 디폴트 환경변수

quota 미승인 동안 매번 `--source ytdlp` 작성 friction 제거:

```bash
# ~/.envrc (direnv) 또는 cron MAILTO 위에
export TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp
```

quota 승인 후 line 제거하면 자동으로 spec 010 (api) 디폴트 복귀.

### 1.5 alias 등록 확인

```bash
tube-scout admin channel list
# nursing, dental, pharmacy, ... 22개 출력 확인.
```

미등록 채널은 `tube-scout admin channel add --alias <name> --channel-id <UC...>` 로 등록.

---

## 주간 cron 백필

### 2.1 cron 스크립트 (4 줄)

```bash
#!/usr/bin/env bash
# scripts/weekly-backfill.sh
set -euo pipefail
cd ~/localgit/tube-scout
exec nix develop -c bash -c '
  tube-scout collect videos       --all-channels                    # spec 003 — 메타 (Data API ~22 unit)
  tube-scout collect transcripts  --all-channels --source ytdlp     # 본 spec — quota 0
  tube-scout collect fingerprint  --all-channels                    # 본 spec — 음원 추출 + 지문 + 삭제
'
```

cron entry (매주 토요일 02:00):

```cron
0 2 * * 6 ~/localgit/tube-scout/scripts/weekly-backfill.sh > ~/log/tube-scout-backfill.log 2>&1
```

### 2.2 1회 실행 시간 예상

| 단계 | 채널당 시간 | 22채널 합산 |
|---|---|---|
| `collect videos` (메타) | ~10초 (1편당 ~0.05초) | ~4분 |
| `collect transcripts` | ~12분/채널 (180편 × ~4초 평균) | ~4시간 (sleep 30~60s 포함) |
| `collect fingerprint` | ~3시간/채널 (180편 × ~60s 평균) | ~67시간 |
| **총 1회 백필** | — | **~71시간** (≈ 3일) |

이후 weekly cron은 신규 영상만 idempotent 처리 — 보통 채널당 5~20편 신규 → 22채널 약 2~6시간.

---

## 일상 디버깅

### 3.1 audit CSV 검사

```bash
# 가장 최근 job-id
JOB=$(ls -1 projects/ | sort -r | head -1)

# 자막 처리 결과 요약
csvkit -c result projects/$JOB/01_collect/transcripts_audit.csv \
  | sort | uniq -c
# 예시 출력:
#   3450 success
#   320  skip_existing
#   24   no_captions_available
#   6    cookies_expired
#   2    rate_limit

# 지문 처리 요약 (동일 패턴)
csvkit -c result projects/$JOB/01_collect/fingerprint_audit.csv \
  | sort | uniq -c

# 실패 영상만 보기
awk -F, '$2=="fail" {print $1, $3}' \
    projects/$JOB/01_collect/fingerprint_audit.csv
```

### 3.2 cookies 만료 / keyring lock 회복

증상: 여러 채널에서 `cookies_expired` 또는 `Brave keyring is locked` 메시지.

```bash
# 1. Brave 실행 + youtube.com 로그인 상태 확인
brave-browser https://youtube.com

# 2. keyring unlock (NixOS gnome-keyring 사용 시)
secret-tool lookup ...   # unlock 트리거

# 3. 또는 cookies.txt 폴백 갱신 (1.3 절차 반복)

# 4. 실패한 채널만 재시도 (cron 진입 없이)
tube-scout collect transcripts --source ytdlp --channel <alias> --force
```

### 3.3 rate limit 회복

증상: 채널 처리 중 `rate_limit` 다수 + cron 종료 비정상.

```bash
# 즉시 재시도 금지 — IP reputation 손상 가능
# 1) 30분~1시간 대기
# 2) 실패한 채널만:
tube-scout collect transcripts --source ytdlp --channel <alias>
#    --sleep-min 60 --sleep-max 120  # 더 보수적으로
```

지속되면: 다른 IP / VPN 사용 또는 Data API quota 승인 우선 (spec 010 fallback).

### 3.4 audio_temp 잔재 정리 (비정상 종료)

증상: `01_collect/audio_temp/` 에 mp3 파일 남음.

```bash
# 정상 종료 검증: 디렉터리 비어야 함 (SC-004)
ls projects/$JOB/01_collect/audio_temp/

# 잔재 발견 시 audit-log 에 "interrupted" 항목 검사
grep -E "interrupted" projects/$JOB/01_collect/fingerprint_audit.csv

# 다음 실행이 자동 정리 + 해당 영상 재처리하므로 보통 수동 cleanup 불필요
# 강제 정리:
rm -f projects/$JOB/01_collect/audio_temp/*.mp3
```

### 3.5 v3 schema migration 검증

spec X1 첫 실행 시 자동 v2 → v3 migration. 검증:

```bash
sqlite3 projects/$JOB/02_analyze/content/content_reuse.db <<EOF
PRAGMA user_version;          -- 3 출력 기대
.schema audio_fingerprint     -- 테이블 정의 출력
SELECT count(*) FROM audio_fingerprint;
EOF
```

`user_version != 3` 이면 spec 011 v2 schema 누락 가능 — `tube-scout admin db migrate --to 3` 수동 실행.

---

## 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| `ImportError: couldn't find libchromaprint` | LD_LIBRARY_PATH 미설정 (devShell 외부) | `nix develop` 진입 후 재실행 |
| `ImportError: libstdc++.so.6 not found` | numpy c-ext LD 의존 누락 | flake.nix `stdenv.cc.cc.lib` 확인, devShell 재진입 |
| `WARNING: Post-Processor arguments given without specifying name` | yt-dlp `--postprocessor-args` 에 ffmpeg: prefix 누락 | dev-squad 버그 — code patch 요청 (spike 검증된 prefix 강제) |
| `ERROR: Failed to extract any cookies from brave` | Brave keyring locked | secret-tool unlock 또는 cookies.txt 폴백 (3.2 절차) |
| 비공개 영상 자막 fetch 실패 (인증 OK인데 401) | 운영자가 채널 owner 아님 | spec X1 영구 scope OUT — 운영자 인증 권한 확인 |
| `audio_decode_failed` 반복 (특정 영상) | 비표준 codec / DRM | per-video skip + audit 기록만, 운영자 수동 검토 후 `--force` 시도 |
| `tube-scout collect transcripts` 가 spec 010 (api) 흐름으로 가는데 quota 0 | 환경변수 `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp` 미설정 | 1.4 절차 또는 매 호출 `--source ytdlp` 명시 |

---

## Constitution / Boundary 검증 (운영자 self-audit)

본 spec X1 실행 시 다음 invariants 가 항상 성립해야 함 (위반 시 dev-squad bug):

- [ ] **SC-004**: 명령 종료 후 `audio_temp/` 디렉터리 잔재 0건.
- [ ] **SC-008**: alias 미등록 채널 호출 시 yt-dlp 네트워크 호출 0건 (tcpdump으로 검증 가능).
- [ ] **SC-001**: `collect transcripts --source ytdlp` 실행 시 Data API quota 사용량 0 unit (Google Cloud Console 모니터링).
- [ ] **B-X1-2**: `content_reuse.db` 의 v2 테이블(videos, segments, matches 등) row 수가 spec X1 실행 전후 변경 0.
- [ ] **B-X1-9**: `services/fingerprint.py` (텍스트 SHA — spec 011) 와 `services/audio_fingerprint.py` (본 spec) 가 동시 import 가능 + 작동.
- [ ] **Constitution VI**: cookies 평문 string 이 git repo 또는 stdout 에 출력 0건.

위반 발견 시 `bug` 라벨 GitHub issue + spec/plan 인용.

---

## References

- spec: [spec.md](./spec.md)
- plan: [plan.md](./plan.md)
- 운영 정책 메모리: `project_data_acquisition_strategy`, `project_caption_survey`, `project_no_comments`
- spec 003 alias 등록: `specs/003-multichannel-admin/`
- spec 009 인증 갱신: `specs/009-runtime-auth-fix/`
