# Quickstart: 보고서 필터링 및 PDF 종합 출력

## Prerequisites

1. 데이터 수집 완료 (`tube-scout collect videos`)
2. 분석 완료 (`tube-scout analyze retention` 등)
3. weasyprint 시스템 라이브러리 (flake.nix에 포함)

## 필터링된 영상 보고서 (HTML)

```bash
# 키워드로 필터링
tube-scout report video --keyword "감염미생물학"

# 기간 + 키워드
tube-scout report video --keyword "홍길동" --published-after 2025-09-01 --published-before 2026-02-28

# 미리보기만
tube-scout report video --keyword "인체구조와기능" --dry-run
```

## PDF 종합 보고서

```bash
# 데이터에서 직접 PDF 생성
tube-scout report bundle --keyword "감염미생물학" --output 감염미생물학_보고서.pdf

# 기존 HTML 수거 → PDF
tube-scout report bundle --from-html data/reports/video/ --keyword "감염미생물학" --output 보고서.pdf

# 정렬 변경
tube-scout report bundle --keyword "홍길동" --sort course --output 홍길동_교과목순.pdf

# 표지 제목 지정
tube-scout report bundle --keyword "홍길동" --title "2025학년도 2학기 강의 영상 분석" --output report.pdf
```

## Development

```bash
# 테스트 실행
pytest tests/unit/test_video_filter.py -v
pytest tests/unit/test_bundle_report.py -v
pytest tests/integration/test_bundle_flow.py -v

# weasyprint 동작 확인
python -c "from weasyprint import HTML; print('weasyprint OK')"
```
