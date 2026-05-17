# 2026-05-17 ASR/Ingest 인시던트 — 다음 세션 인계서 (sonnet 진입용)

**작성 시점**: 2026-05-17, opus 세션 종료 시점 (token 810K 도달)
**다음 세션 의도**: sonnet 으로 일괄 fix 수행 — **반복 행동 금지**, 한 번에 plan 의 모든 fix 단위를 의존관계 순서대로 처리

---

## 1. 본 세션 결과 — 무엇이 완료되었고 무엇이 남았는가

### 완료 (read-only audit only, 코드 0 수정)
- audit 4 agent (audit-nix-policy / audit-runtime / audit-ux / adversary) 가 SCOPE-EXPAND 까지 모두 종료
- qa-engineer cross-validation 1차 완료
- pair-programmer first pass + minor revision 완료 (plan v1)
- 인시던트 문서 §3 first pass 통합 (21건) + 일부 audit-nix-policy 의 직접 in-place 갱신

### plan v2 부분 반영 (pair-programmer shutdown 직전 commit, fix 단위 10건)
- ✅ F-1 cuRAND 제거 정정
- ✅ F-3 → F-3a (asr.py) + F-3b (unified_ingest.py reason collapse, ADV-1 R-7.a) 분리
- ✅ F-8 신설 (`audio_extract.py` ffmpeg timeout — ADV-15 만, **stdin=DEVNULL 미포함**)
- ✅ §4 OPEN-I (spec 019) + OPEN-J (ADV-15 ffmpeg timeout) 신설
- ✅ §3 sub-bullets +18건 추가 (E/I/SB/R 일부)

### 미반영 — 다음 세션 sonnet 이 진입 즉시 처리할 항목

#### plan 보강 (fix 단위 추가 ~4건)
- **F-8 확장 → ADV-29**: `audio_extract.py:51` 에 `stdin=subprocess.DEVNULL` 한 줄 추가 (현재 plan F-8 은 timeout 만, 같은 줄이라 1 commit 으로 묶음)
- **F-11 신설 (P0+)**: `unified_ingest.py` SIGINT 핸들러 (ADV-22) — 현재 plan 은 "사용자 결정" 으로 deferral. F-3b 와 같은 파일이지만 회귀 위험 분리
- **F-12 신설 (P1)** 또는 F-5 흡수 결정: `tube-scout doctor` CLI (E-2.a + D-1.b + ADV-28 + C-4 → 5 finding 동시 해소). 현재 plan 은 "F-5 문서로 대체" 로 우회
- **F-14 신설 (P0+, ★ 매우 중요)**: retry_pending.json manifest PK 확장 — ADV-34 + ADV-35 silent failure 동시 해소. **현재 plan 누락. §4 의 F-14 항목 참조**
- **F-3b 확장**: ADV-31 worker_pool.py:169 device 하드코딩 정정 — 현재 plan 미포함
- **F-* 신규 (옵션)**: ADV-33 content_report.py plotly silent except — 별도 작은 fix

#### 인시던트 문서 §4 OPEN 추가
- **OPEN-K (신설)**: ADV-22 SIGINT 핸들러 — 현재 plan deferral 사유 자체가 OPEN
- **OPEN-L (신설)**: ADV-34/35 manifest PK silent failure
- (옵션) OPEN-M: ADV-33 plotly silent except

#### 코드/문서 fix
- **0건** (read-only audit only)

---

## 2. 산출물 위치 — 다음 세션이 진입 즉시 read 할 파일

| 우선순위 | 경로 | 역할 |
|---|---|---|
| 1 | `docs/incidents/2026-05-17-asr-ingest-inconsistency.md` | 인시던트 본문 (시드, §3 first-pass 통합 + 일부 audit 결과) |
| 2 | 이 파일 | 인계서 |
| 3 | `_workspace/audit_consistency_20260517_qa_cross.md` | **누락 통합 53건 + 정정 3건 + 신규 H 9건** 권위 매트릭스 |
| 4 | `_workspace/audit_consistency_20260517_remediation_plan.md` | plan v1 — **revision v3 필요** (아래 §4 참조) |
| 5 | `_workspace/audit_consistency_20260517_g_d_c.md` | G-4/G-5 binary analysis 패치 매트릭스 (cuBLAS+cudart 확정, cuRAND 제거) |
| 6 | `_workspace/audit_consistency_20260517_adversary.md` | ADV-1~33 (특히 ADV-1/15/22/28/29/30/31 가 plan 미반영) |
| 7 | `_workspace/audit_consistency_20260517_e_i.md` | E+I+SB 18 findings (SB scale 그룹 미통합) |
| 8 | `_workspace/audit_consistency_20260517_r.md` | R 22 findings (BUX-1 H 미통합) |
| 9 | `_workspace/audit_consistency_20260517_final_report.md` | first-pass only (참고용, 산출물 미반영 노트 명시) |

---

## 3. 본 세션 동안 적용된 코드/설정 변경 (commit 안 함)

| 파일 | 변경 |
|---|---|
| `flake.nix` | `commonBuildInputs` 에 `sqlite` 추가 (line 60~) |
| `.envrc` | `source_env_if_exists .envrc.local` 추가 |
| `.gitignore` | `.envrc.local` 추가 |
| `.envrc.local` (사용자 신규) | `use flake .#gpu` |
| `data/takeout-.../동영상 메타데이터/동영상(99).csv` (assistant 신규) | DUPTEST00001 fake row 한 줄 |
| `data/takeout-.../동영상/42- 2. … 7주차 …mp4` (사용자 신규) | 박연경 6주차 mp4 의 cp 복제본 |
| `docs/incidents/2026-05-17-asr-ingest-inconsistency.md` (신규) | 인시던트 본문 |
| `docs/incidents/2026-05-17-handoff-to-next-session.md` (신규) | 본 인계서 |
| `_workspace/audit_consistency_20260517_*.md` (신규 7개) | audit 산출물 |

---

## 4. 다음 세션 sonnet 의 작업 명세 — 순서대로 한 번에

### Phase A. plan revision v3 (Read-only)
인시던트 §3·§4 + remediation_plan.md 를 **한 번에** in-place revision. 이는 fix 시작 전 절대 선행. 작업 종료 시점 — plan 이 완전체가 되어야 함.

#### A-1. 인시던트 §3 추가 통합 (53건)
- qa-cross 의 권위 finding 매트릭스 참조
- 정정: **E-3.a (asr.py:344 false-attribution) 부분 부정 격하**. 진짜 위치는 ADV-1 (`unified_ingest.py:269/316/361` reason collapse) — 권위 승격
- R 그룹 High 0→4 반영 (R-4.a/b, R-7.a, BUX-1)
- SB 그룹 §3.7 신설 또는 §3.2 sub-section

#### A-2. §4 OPEN 갱신
- OPEN-G 확장: ADV-1 + R-7.a
- OPEN-H 확장: ADV-20 + SB-4.a/b
- **OPEN-I 신설**: ADV-30 (`nc2_matcher.py:627` 4 micro-opt, spec 019 시드 — 사용자 결정 필요)
- **OPEN-J 신설**: ADV-15 + ADV-29 (`audio_extract.py:51` timeout + stdin=DEVNULL)
- **OPEN-K 신설** (옵션): ADV-22 SIGINT 핸들러

#### A-3. plan fix 단위 revision (현재 7건 → 10건 추정)

**F-1 정정 (audit-nix-policy G-4/G-5 binary analysis 기반)**:
- ❌ cuRAND **제거** (ctranslate2 dlopen 안 함)
- ✅ `cudaPackages.libcublas` + `cudaPackages.cuda_cudart` **만 추가**
- buildInputs (flake.nix:101-104) + shellHook LD_LIBRARY_PATH (flake.nix:106-109) **양쪽 동시 수정**
- G-1.c (gpuLibPath 헬퍼) + C-2.a (inline dlopen 주석) + G-3.a (extra 대응 주석) 함께
- **"반복 금지" 보장: flake.nix 는 이 1 fix 로 끝**

**F-2**: `pyproject.toml` `[asr]` extra 에 `ctranslate2>=4.7.0,<5.0.0` 핀 (G-2.a). 독립.

**F-3 묶음 확장**: **{asr.py + unified_ingest.py + worker_pool.py} → 1 fix 단위 (또는 2-3 단위로 분리)**:
- `asr.py:563` broad-except 분류 (E-3.a 격하분, 부분 보완)
- `unified_ingest.py:269/316/361` reason collapse 정정 (**ADV-1 — cascade 5건 해소**)
- `worker_pool.py:169` device 하드코딩 → `--device cuda|cpu|auto` flag (ADV-31)
- **분리 권장**: F-3a (asr.py + unified_ingest.py reason collapse) / F-3b (worker_pool.py device flag) — signal handler (F-11) 와 같은 파일이지만 회귀 위험 분리

**F-4**: `src/tube_scout/cli/collect.py` ingest CLI R-1.a (`--takeout-dir ""` 빈 문자열 명확 에러). 독립.

**F-5**: `docs/quickstart.md` GPU/direnv/doctor 섹션 신설 (D-1.a, D-1.b, D-2.a, D-3.a, E-1.a, E-2.a, R-2.a). F-1~F-3+F-8+F-11 결과 반영 → **직렬**.

**F-6**: project `CLAUDE.md` Consistency Invariants 섹션 신설 (C-1.a, C-3.a, C-4). F-5 와 병렬 가능.

**F-7 (정책 결정 — 사용자 대기)**: I-1.a, I-2.a, I-3.a, G-2.b, OPEN-H 묶음 — `already_transcribed` 모델 메타 검증 정책. **사용자 결정 후 별도 사이클**.

**F-8 신설 (P0+, 2 줄 fix)**: `audio_extract.py:51` subprocess.run 에 `timeout=<X>` + `stdin=subprocess.DEVNULL` 동시 추가 — ADV-15 + ADV-29 한 fix 로 2 hang 해소.

**F-11 신설 (P0+)**: `unified_ingest.py` SIGINT 핸들러 (ADV-22 — Ctrl+C 시 (a) 처리 중 video_id retry_pending.json `aborted_by_user` 사유 박음, (b) audit CSV 종료 행, (c) 부분 transcript JSON 신뢰 마커 제거).
- F-3 과 같은 파일 — **F-3a (reason collapse) 와 분리 권장** (signal handling 회귀 위험)

**F-12 신설 (P1)**: `tube-scout doctor` CLI 신설 — `src/tube_scout/cli/doctor.py` 새 모듈.
검증: active Python path, devShell variant, faster_whisper import, LD_LIBRARY_PATH (cuDNN/cuBLAS/cudart), `shutil.which("fpcalc")`, `shutil.which("ffmpeg")`, `shutil.which("sqlite3")`.
**1 fix 가 5 finding 동시 해소**: E-2.a + D-1.b + ADV-28 + C-4 + 가능 ADV-31.
단 새 CLI 모듈 — 사용자 결정 시 OPEN-K 로 보류 가능.

**F-13 (P3, spec 신설 — 사용자 대기)**: SB-1 + ADV-30 = spec 019 nc2 가속. 사용자 결정 후 별도 spec.

**F-14 신설 (P0+, ★ 매우 중요 — silent failure 직격)**: retry_pending.json manifest PK 확장 — `video_id` 단독에서 `(video_id, mp4_filename)` 합성 키 또는 둘 중 하나 허용으로 변경. 단일 fix 가 ADV-34 + ADV-35 동시 해소.
- **ADV-34 (H)**: `evidence_score.py:334-341` score < threshold(40) 시 `MappingDecision(video_id=None)` → `takeout_ingest.py:506` 의 `if vid` 가 None 매핑 mp4 silent drop. archive 의 실제 mp4 가 fuzzy 점수 한 점 부족으로 **영구 제외, retry 큐 진입 불가**.
- **ADV-35 (H)**: `takeout_ingest.py:507-524` `no_mp4_in_archive` skip — video_id 는 있지만 mp4 없을 때도 retry entry 미생성. multi-part Takeout 일부만 풀린 케이스 시 archive 보완 후 자동 재시도 신호 부재 → **영구 stale**.
- 공통 근본원인: spec 018 idempotency 가 retry-driven 인데 entry 경로 자체가 차단됨. 본 인시던트의 "사용자 모르게 영상이 빠짐" 위험과 직결.
- 영향: spec 003 의 "교수 매핑 실수 검출" 시나리오에서 이 silent drop 이 그대로 잠재.

#### A-4. DAG (반복 금지 보장)
```
F-1 (flake.nix)              ┐
F-2 (pyproject.toml)         ├ 모두 병렬 가능 (다른 파일)
F-3a (asr.py + unified_ingest reason collapse)
F-3b (worker_pool.py device)
F-4 (collect.py)             │
F-8 (audio_extract.py)       │
F-11 (unified_ingest SIGINT) ┘
        ↓
F-5 (quickstart.md)          ┐ 위 결과 반영 — 직렬
F-6 (CLAUDE.md)              ┘
        ↓
F-12 (doctor CLI) — 옵션, 사용자 결정 시
        ↓
F-7 / F-13 — 사용자 정책 결정 대기
```

#### A-5. plan revision 완료 시 검증
- `_workspace/audit_consistency_20260517_remediation_plan.md` 의 fix 단위 ≥ 10건
- 인시던트 §3 sub-bullets ≥ 60건 (first pass 21 + 추가 ~40)
- §4 OPEN ≥ 10건 (A-H + I-J-K)

### Phase B. 사용자 승인 받기
plan revision v3 완료 시 사용자에게 한 페이지 요약 보고 + **명시 승인** 받기. 다음 항목 확인:
- F-7 (already_transcribed 모델 메타 검증 정책) — warn vs reprocess 결정
- F-13 (spec 019 신설) — 진행 vs 보류
- F-12 (doctor CLI 신설) — F-5/F-6 의 수동 검증 가이드로 대체 vs 신설
- 본 세션 임시 산출물 (`동영상(99).csv`, `42- 2 … 7주차 …mp4`) — 테스트 후 삭제 시점

### Phase C. 일괄 fix (사용자 승인 후)
F-1 → F-2 → F-3a → F-3b → F-4 → F-8 → F-11 → F-5 → F-6 → (F-12 옵션) 순서.
각 fix 후 즉시 검증 (pytest + 실행 테스트), 회귀 0 확인 후 다음 fix.
**같은 파일 두 번 안 건드림**.

---

## 5. "반복 행동 금지" 원칙 명시 (사용자 비판 핵심)

본 세션 ACT-1 (assistant 가 sqlite 한 줄만 추가, GPU shell 완결성 미점검) 이 정확한 반복 위반 사례. 다음 세션에서:

- 같은 파일 (flake.nix, asr.py, unified_ingest.py 등) 는 **1 commit 1 fix 단위** 로 묶어 한 번에 수정
- audio_extract.py 의 ADV-15 (timeout) 와 ADV-29 (stdin=DEVNULL) 가 같은 줄이므로 **반드시 한 fix 로 묶음**
- 부분 fix → 검증 실패 → 또 fix 의 사이클을 금지. 사전 plan 의존관계 (DAG) 그대로 일괄 진행

---

## 6. 다음 세션 진입 즉시 실행 명령 (sonnet 용)

```bash
cd /home/kjeong/localgit/tube-scout

# 1) 인계서 + plan 읽기
cat docs/incidents/2026-05-17-handoff-to-next-session.md
cat _workspace/audit_consistency_20260517_qa_cross.md
cat _workspace/audit_consistency_20260517_remediation_plan.md
cat _workspace/audit_consistency_20260517_g_d_c.md     # G-4/G-5 패치 매트릭스
cat _workspace/audit_consistency_20260517_adversary.md # ADV-1/15/22/28/29/30/31 권위

# 2) plan revision v3 진행 (위 §4 Phase A)
# 3) 사용자 승인 (Phase B)
# 4) 일괄 fix (Phase C)
```

---

## 7. 본 세션 token 사용 현황

- 시작 token: ~0
- 종료 token: ~810K
- 주요 소비: 6 agent 병렬 + cross-validation 메시지 + 4 audit 산출물 (16+28+26+29=99k 외부 저장)
- 다음 세션 sonnet 예상: plan revision ~50k + 일괄 fix ~100k = 총 150k 내외 (opus 대비 1/5)

본 세션 종료 시점에 6 agent shutdown 트리거 발송.
