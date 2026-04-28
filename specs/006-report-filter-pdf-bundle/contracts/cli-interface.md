# CLI Interface Contract: report bundle

## Command

```
tube-scout report bundle [OPTIONS]
```

## Options

| Option | Type | Default | Description | Status |
|--------|------|---------|-------------|--------|
| `--keyword` | TEXT | None | 제목 키워드 필터 (substring) | 기존 |
| `--published-after` | TEXT | None | 게시일 시작 (YYYY-MM-DD, inclusive) | 기존 |
| `--published-before` | TEXT | None | 게시일 종료 (YYYY-MM-DD, inclusive) | 기존 |
| `--video-ids` | TEXT | None | 쉼표 구분 영상 ID 목록 | 기존 |
| `--sort` | TEXT | date_asc | 정렬: date\|date_asc\|course\|views | **변경** (기본값 date→date_asc) |
| `--format` | TEXT | pdf | 출력 형식: pdf\|html | **신규** |
| `--title` | TEXT | None | 표지 사용자 지정 제목 | 기존 |
| `--output` | TEXT | auto | 출력 파일 경로 | 기존 |
| `--from-html` | TEXT | None | 기존 HTML 보고서 디렉터리 (수확 모드) | 기존 |
| `--dry-run` | FLAG | False | 미리보기만 표시 (생성 없음) | 기존 |
| `--no-confirm` | FLAG | False | 대화형 확인 생략 | **신규** |
| `--data-dir` | TEXT | ./data | 데이터 저장 디렉터리 | 기존 |
| `--project-dir` | TEXT | ./projects | 프로젝트 루트 | 기존 |
| `--project` | TEXT | latest | 프로젝트 경로 | 기존 |

## Behavior Flow

```
1. 필터 조건 파싱 (VideoFilter 생성)
2. 영상 메타데이터 로드 (videos_meta.json)
3. 필터 적용 (VideoFilterService.filter_videos)
4. 정렬 적용 (VideoFilterService.sort_videos)
5. 결과 0건 → 메시지 출력 + exit(0)
6. --dry-run → 미리보기 테이블 + exit(0)
7. 미리보기 테이블 표시 (제목, 게시일, 조회수)
8. --no-confirm이 아니면 → typer.confirm("Generate report?")
   - 취소 → exit(0)
9. 보고서 생성
   - --format pdf → HTML 생성 → render_pdf()
     - weasyprint 미설치 → 에러 메시지 + HTML 폴백
   - --format html → HTML만 생성
10. 출력 경로 표시 + exit(0)
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | 성공 (생성 완료, 미리보기, 취소 포함) |
| 1 | 에러 (프로젝트 미설정, 데이터 누락 등) |

## Preview Table Format (Rich)

```
┌──────────────┬──────────────────────────┬────────────┬──────────┐
│ Video ID     │ Title                    │ Published  │ Views    │
├──────────────┼──────────────────────────┼────────────┼──────────┤
│ abc123       │ 감염미생물학 3주차 1차시  │ 2025-10-01 │ 1,234    │
│ def456       │ 감염미생물학 3주차 2차시  │ 2025-10-02 │ 987      │
└──────────────┴──────────────────────────┴────────────┴──────────┘
15 videos matched. Total duration: 12h 34m.
Generate report? [y/N]
```
