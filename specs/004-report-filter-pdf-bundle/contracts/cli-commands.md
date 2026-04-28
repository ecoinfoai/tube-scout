# CLI Contracts: 보고서 필터링 및 PDF 종합 출력

## Modified Command: `report video`

기존 명령에 필터 옵션 추가. 출력 형식은 기존과 동일 (개별 HTML 파일).

```
tube-scout report video [OPTIONS]

기존 옵션:
  --data-dir TEXT       Data storage directory [default: ./data]
  --video-id TEXT       Specific video ID
  --format TEXT         Output format: html/notebook [default: html]
  --output-dir TEXT     Output directory

신규 옵션:
  --keyword TEXT           제목 키워드 필터 (부분 문자열 매칭)
  --published-after TEXT   게시일 시작 (YYYY-MM-DD, inclusive)
  --published-before TEXT  게시일 종료 (YYYY-MM-DD, inclusive)
  --video-ids TEXT         쉼표 구분 영상 ID 목록
  --dry-run                필터 결과만 표시, 보고서 생성 안 함
```

### 동작 규칙

- `--keyword`, `--published-after`, `--published-before`는 AND 조합
- `--video-ids` 지정 시 다른 필터와 AND 조합
- `--video-id` (단수, 기존)와 `--video-ids` (복수, 신규)는 상호 배타
- `--dry-run` 지정 시 대상 영상 목록을 Rich table로 표시하고 종료
- 필터 결과 0개: 안내 메시지 표시, exit code 1

### 출력 예시 (dry-run)

```
Found 24 videos matching filters:
┌──────────────────┬────────────────────────────────────────────┬────────────┐
│ Video ID         │ Title                                      │ Published  │
├──────────────────┼────────────────────────────────────────────┼────────────┤
│ private_vid_001      │ 홍길동 2025 감염미생물학 13주차 1차시       │ 2025-12-15 │
│ private_vid_002      │ 홍길동 2025 감염미생물학 11주차 2차시       │ 2025-11-28 │
│ ...              │                                            │            │
└──────────────────┴────────────────────────────────────────────┴────────────┘
```

---

## New Command: `report bundle`

필터링된 영상의 종합 PDF 보고서 생성.

```
tube-scout report bundle [OPTIONS]

필터 옵션 (report video와 동일):
  --keyword TEXT           제목 키워드 필터
  --published-after TEXT   게시일 시작 (YYYY-MM-DD)
  --published-before TEXT  게시일 종료 (YYYY-MM-DD)
  --video-ids TEXT         쉼표 구분 영상 ID 목록

생성 옵션:
  --output TEXT            PDF 출력 파일 경로 [default: auto-generated]
  --title TEXT             보고서 표지 제목 [default: 채널명 + 필터 조건]
  --sort TEXT              정렬: date/course/views [default: date]
  --from-html TEXT         기존 HTML 보고서 디렉터리 (수거 모드)
  --dry-run                필터 결과만 표시

공통 옵션:
  --data-dir TEXT          Data storage directory [default: ./data]
```

### 동작 규칙

- 기본 모드: 데이터에서 직접 Jinja2 렌더링 → 단일 HTML → weasyprint → PDF
- `--from-html` 모드: 기존 HTML에서 body 추출 → bundle 템플릿에 삽입 → PDF
- `--from-html` + 필터: HTML 파일명(video_id.html)과 videos_meta.json 매칭하여 필터링
- 200개 초과 시 경고 표시 후 진행 여부 확인
- 필터 결과 1개: 목차 생략, 표지 + 단일 영상 보고서
- 필터 결과 0개: 안내 메시지, exit code 1

### 출력 파일명 규칙 (auto-generated)

```
bundle_{keyword}_{date}.pdf
예: bundle_감염미생물학_20260404.pdf
    bundle_홍길동_20260404.pdf
    bundle_all_20260404.pdf
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | 성공 |
| 1 | 필터 결과 0개 또는 설정 오류 |
| 2 | PDF 생성 실패 (weasyprint 에러) |
