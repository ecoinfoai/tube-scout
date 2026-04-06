# Layer 7: Security & Robustness Audit Results

## 요약

| 검사 항목 | 결과 | 심각도 |
|----------|------|--------|
| OAuth 토큰 파일 권한 | **FAIL** | High |
| 시크릿 노출 | **PASS (conditional)** | Low |
| Path traversal | **PASS (partial)** | Medium |
| HTML injection / XSS | **PASS** | — |
| Excel formula injection | **FAIL** | Medium |
| 네트워크 타임아웃 | **FAIL** | High |
| 환경변수 미설정 처리 | **PASS** | — |
| Atomic write 무결성 | **PASS** | — |

---

## 상세 결과

### 1. OAuth 토큰 파일 권한

**결과: FAIL (High)**

**코드 위치:**
- `src/tube_scout/services/auth.py:100` — `token_path.write_text(creds.to_json())`
- `src/tube_scout/services/auth.py:254` — `token_file.write_text(creds.to_json())`
- `src/tube_scout/services/auth.py:307` — `token_file.write_text(creds.to_json(), encoding="utf-8")`

**현재 동작:** `Path.write_text()`는 `umask`에 따라 파일 권한을 설정합니다. 일반적인 Linux umask(022)에서는 `0644`(owner rw, group/other r)로 생성되어 **다른 사용자도 토큰 파일을 읽을 수 있습니다**.

**위험:** OAuth 토큰(access_token + refresh_token)이 세계 읽기 가능 상태로 저장됩니다. 공유 서버 환경에서 다른 사용자가 토큰을 탈취하여 YouTube 채널에 무단 접근할 수 있습니다.

**권장 수정:**
```python
import os, stat
fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
with os.fdopen(fd, 'w') as f:
    f.write(creds.to_json())
```

또한 `save_registry()` (`auth.py:179`)의 `channels.json`도 동일한 문제가 있습니다. 이 파일은 `token_path` 경로를 포함하므로 간접적 정보 노출.

**영향받는 함수:** `authenticate()`, `authenticate_channel()`, `register_channel()`, `save_registry()`

---

### 2. 시크릿 로깅/노출

**결과: PASS (conditional) — Low**

**분석:**
- **로깅**: `logger.warning()` 호출은 모두 `video_id`, HTTP status 등 비민감 정보만 포함합니다. f-string이 아닌 `%s` 포맷을 사용하지 않지만, 민감 데이터를 로깅하지 않으므로 안전합니다.
- **에러 메시지**: CLI에서 `console.print(f"[red]{e}[/red]")` 패턴으로 예외를 출력합니다 (`collect.py:101,221,267-271`, `report.py:469-472`). Google API의 `HttpError` 예외에는 간혹 인증 관련 세부 정보가 포함될 수 있으나, Tube Scout은 사용자 본인이 CLI를 실행하는 구조이므로 실질적 위험은 낮습니다.
- **코드 내 시크릿**: API 키는 환경변수에서 읽어 SDK 클라이언트에 전달합니다 (`llm_adapter.py:51-57`). 하드코딩된 시크릿 없음.
- **traceback**: 일반 Exception 핸들러에서 `str(e)`를 출력하는데, OAuth 관련 예외가 전파되면 이론적으로 토큰 일부가 노출될 수 있지만, Google OAuth 라이브러리는 토큰을 예외 메시지에 포함하지 않으므로 현실적 위험은 낮습니다.

**조건부 경고:** 디버그 로깅(DEBUG 레벨)이 활성화된 경우 `google-api-python-client` 내부에서 HTTP 헤더(Authorization 포함)를 로깅할 수 있습니다. 운영 환경에서 `logging.DEBUG`를 사용하지 않도록 주의해야 합니다.

---

### 3. Path Traversal

**결과: PASS (partial) — Medium**

**분석:**

| 입력 | 사용 위치 | 방어 여부 |
|------|----------|----------|
| `--data-dir` | 모든 CLI 명령 (`collect.py`, `main.py`) | **미방어** — `Path(data_dir)` 그대로 사용 |
| `--project-dir` | `project.py:26` | **미방어** — `Path(project_dir)` 그대로 사용 |
| `--output-dir` | `report.py:184,346,493` | **미방어** — `Path(output_dir)` 그대로 사용 |
| `--channel` | `report.py:465` 파일명에 사용 | **방어됨** — `report.py:51-70`의 `_sanitize_filename_part()` 함수가 `../`, `/`, `\` 제거 |
| `--keyword` | `report.py:676` 파일명에 사용 | **방어됨** — `_sanitize_filename_part()` 적용 |
| `--from-html` | `report.py:688` | **미방어** — `Path(from_html)` 그대로 사용 |

**현재 동작:** `--data-dir`, `--project-dir`, `--output-dir`은 사용자가 CLI에서 직접 지정하는 경로입니다. `--channel` 인자가 `report_department_command`에서 파일 경로의 일부로 사용될 때(`report.py:465,508`)에는 `_sanitize_filename_part()`가 적용됩니다.

**위험 평가:** Tube Scout은 CLI 도구로, 사용자 본인이 직접 실행합니다. `--data-dir ../ --output-dir /tmp/evil` 같은 입력은 사용자 자신의 권한 범위 내에서만 작동합니다. 웹 서비스가 아니므로 **현실적 공격 벡터는 매우 제한적**입니다.

**그러나** `--channel` 값이 파일 경로 구성에 사용되는 곳(`collect.py:173`, `report.py:465,476`)에서 `_sanitize_filename_part()`가 일관되게 적용되지 않습니다. `collect.py:173`의 `channel_config.channel_id`는 Pydantic 검증(`^UC[a-zA-Z0-9_-]+$`)을 통과하므로 안전하지만, `report_department_command`의 `--channel` 인자(`report.py:465`)는 채널 alias(한글 포함)도 받으며, 해당 값이 `mgr.analyze_dir / "parsed" / channel`로 바로 사용됩니다.

---

### 4. HTML Injection / XSS

**결과: PASS**

**코드 위치:** 모든 Jinja2 Environment 초기화에서 `autoescape=True` 설정 확인:

| 모듈 | 라인 | autoescape |
|------|------|-----------|
| `reporting/video_report.py` | 43-45 | `True` |
| `reporting/comment_report.py` | 20-22 | `True` |
| `reporting/channel_report.py` | 317-319 | `True` |
| `reporting/bundle_report.py` | 56-58 | `True` |
| `reporting/department_report.py` | 31-33 | `True` |

**분석:** 5개 리포트 생성 모듈 모두 `autoescape=True`로 설정되어 있어, 영상 제목, 교수명 등 사용자 데이터가 HTML에 삽입될 때 자동으로 이스케이핑됩니다. XSS 위험 없음.

**주의:** `channel_report.py:376`에서 `trend_chart_html`이 Plotly가 생성한 HTML이므로 `{{ trend_chart_html | safe }}` 필터로 렌더링될 수 있습니다. 이는 Plotly 라이브러리가 생성한 신뢰할 수 있는 HTML이므로 허용 가능하나, 템플릿 파일에서 `| safe` 사용 여부를 확인해야 합니다.

---

### 5. Excel Formula Injection

**결과: FAIL (Medium)**

**코드 위치:** `src/tube_scout/reporting/excel_export.py:140,172`

**현재 동작:** `ExcelExporter`가 `openpyxl`로 Excel을 생성할 때, 영상 제목(`detail.professor_name`), 코스명(`detail.courses`), 주차 상태값(`status`) 등을 셀에 직접 쓰고 있습니다:

```python
ws.cell(row=row_idx, column=1, value=detail.professor_name)  # line 140
ws.cell(row=row_idx, column=3, value=", ".join(detail.courses))  # line 142
ws.cell(row=row_idx, column=1, value=entry.professor_name)  # line 172
```

**위험:** YouTube 영상 제목이 `=CMD|'/C calc'!A0` 형태인 경우, Excel에서 해당 셀 선택 시 외부 명령이 실행될 수 있습니다 (CSV/Formula Injection, CWE-1236).

교수명은 관리자가 설정하므로 위험이 낮으나, **영상 제목은 외부 데이터**이며 현재 제목이 Excel 셀에 직접 들어가는 경로는 `department_report`의 `courses` 필드(제목에서 파싱된 과목명)입니다.

**방어 방법:** `=`, `+`, `-`, `@`, `\t`, `\r`로 시작하는 셀 값 앞에 작은따옴표(`'`)를 prefix하여 텍스트로 강제 처리.

---

### 6. 네트워크 타임아웃

**결과: FAIL (High)**

**분석:**

| 서비스/SDK | 타임아웃 설정 | 위치 |
|-----------|-------------|------|
| `google-api-python-client` | **없음** | `auth.py:111,121,131` (`build()` 호출) |
| `youtube-transcript-api` | **없음** | `transcript.py:59` (`self._api.list()`) |
| `anthropic` SDK | **없음** (SDK 기본값 사용) | `llm_adapter.py:72` |
| `openai` SDK | **없음** (SDK 기본값 사용) | `llm_adapter.py:76` |
| `Whisper` | **없음** | `transcript.py:149-150` |

**현재 동작:**
- `google-api-python-client`의 `build()` 및 `.execute()` 호출에 명시적 timeout이 설정되지 않았습니다. Google HTTP 라이브러리의 기본 timeout에 의존하며, 이는 상황에 따라 매우 길거나 무한할 수 있습니다.
- `youtube-transcript-api`는 내부적으로 `requests`를 사용하며, 기본 timeout이 없을 수 있습니다.
- `anthropic` SDK의 기본 timeout은 10분(600초), `openai` SDK는 10분(600초)이므로 합리적이지만 명시적으로 설정되지 않았습니다.

**위험:** 네트워크 문제나 서버 무응답 시 CLI가 무한 대기할 수 있습니다. `collect all` 파이프라인에서 하나의 요청이 행(hang)되면 전체 파이프라인이 멈춥니다.

**권장 수정:**
```python
# google-api-python-client
from google.auth.transport.requests import Request
import httplib2
http = httplib2.Http(timeout=60)
build("youtube", "v3", credentials=creds, http=http)
```

---

### 7. 환경변수 미설정 처리

**결과: PASS**

**분석:**

| 환경변수 | 처리 위치 | 미설정 시 동작 |
|---------|----------|--------------|
| `TUBE_SCOUT_CLIENT_SECRET` | `auth.py:36-41` | `ValueError` with clear message |
| `TUBE_SCOUT_TOKENS_DIR` | `auth.py:66-69` | Falls back to `~/.config/tube-scout/tokens/` |
| `TUBE_SCOUT_DEVICE` | `config.py:23-31` | Falls back to `"cpu"`, validates if set |
| `TUBE_SCOUT_PROJECTS_DIR` | `output/manager.py:34-35` | Falls back to `./projects` |
| `TUBE_SCOUT_OUTPUT_DIR` | `output/manager.py:138-139` | Falls back to `./output` |
| `TUBE_SCOUT_LLM_PROVIDER` | `llm_adapter.py:39` | Falls back to `"claude"` |
| `ANTHROPIC_API_KEY` | `llm_adapter.py:50-55` | `ValueError` with clear message naming the env var |
| `OPENAI_API_KEY` | `llm_adapter.py:50-55` | Same clear `ValueError` |

**평가:** 모든 필수 환경변수에 대해 명확한 에러 메시지 또는 합리적인 기본값이 제공됩니다. Cryptic traceback 없이 사용자에게 무엇을 설정해야 하는지 안내합니다.

---

### 8. Atomic Write 무결성

**결과: PASS**

**코드 위치:** `src/tube_scout/storage/json_store.py:24-44`

**분석:**
```python
fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp", prefix=".json_")
try:
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    Path(tmp_path).replace(filepath)
except Exception:
    Path(tmp_path).unlink(missing_ok=True)
    raise
```

**검증:**
1. **같은 파일시스템**: `tempfile.mkstemp(dir=filepath.parent)` — 임시 파일이 대상과 같은 디렉터리에 생성되어 `replace()`가 원자적 rename입니다. **올바름.**
2. **실패 시 정리**: `except` 블록에서 임시 파일을 삭제합니다. **올바름.**
3. **부분 쓰기 보호**: 쓰기가 완료된 후에만 `replace()`가 호출됩니다. **올바름.**
4. **기존 파일 보존**: 쓰기 실패 시 기존 파일은 손상되지 않습니다. **올바름.**

**주의:** `auth.py`의 토큰/레지스트리 파일 저장은 `write_json()`이 아닌 `Path.write_text()`를 직접 사용하므로, atomic write의 보호를 받지 못합니다. 토큰 쓰기 중 프로세스가 종료되면 손상된 토큰 파일이 남을 수 있습니다. 이는 보안보다는 안정성 이슈이며 심각도는 Low입니다.

---

## 취약점 목록 (심각도순)

### Critical
- 없음

### High
1. **[H-01] OAuth 토큰 파일 권한 미설정** (`auth.py:100,254,307,179`) — 토큰 파일이 `umask` 기본값(0644)으로 저장되어 공유 서버에서 타 사용자가 읽을 수 있음. `os.open()` + `0600` 권한 또는 `os.chmod()` 적용 필요.
2. **[H-02] 네트워크 타임아웃 미설정** (`auth.py:111,121,131`, `transcript.py:59`, `llm_adapter.py:72,76`) — 모든 외부 API 호출에 명시적 timeout이 없어 CLI가 무한 대기 가능. `httplib2.Http(timeout=60)` 또는 SDK 생성자에 timeout 파라미터 추가 필요.

### Medium
3. **[M-01] Excel formula injection 미방어** (`excel_export.py:140,142,172`) — 외부 데이터(영상 제목 유래 과목명)가 Excel 셀에 직접 입력되어 formula injection 가능. 셀 값이 `=+\-@\t\r`로 시작하면 prefix 처리 필요.
4. **[M-02] `--channel` alias의 path 미검증** (`report.py:465`) — `report department --channel` 인자가 파일 경로에 그대로 사용. 채널 alias에 `../` 포함 시 디렉터리 탈출 가능 (CLI 도구이므로 실질적 위험은 제한적).

### Low
5. **[L-01] auth.py의 토큰 쓰기가 non-atomic** (`auth.py:100,254,307`) — `Path.write_text()` 사용으로 쓰기 중 중단 시 토큰 파일 손상 가능. `write_json()`의 atomic pattern 재사용 권장.
6. **[L-02] 디버그 로깅 시 OAuth 헤더 노출 가능** — `google-api-python-client`가 DEBUG 로그에 Authorization 헤더를 출력할 수 있음. 운영 환경에서 DEBUG 레벨 금지 안내 필요.
