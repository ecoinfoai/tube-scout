# 2026-05-17 audit v3 follow-ups — next session 작업 인계

**상태**: branch `fix/audit-v3-20260517-incident` (master +24 commits) 푸시 완료 후 작성.

본 문서는 audit v3 Phase C 22 commit + cross-spec DB symlink follow-up + multi-output derivation 패치(commit 6450398)를 모두 적용한 직후, 10 mp4 사용성 테스트(GPU `gpu-quantized` preset, RTX 3060 Laptop 6 GB) 실행 결과 드러난 잔여 결함과, plan v3 §13.3 "next cycle 권고" 항목을 묶어 다음 세션이 한 번에 처리할 수 있게 정리한 인계서다.

본 인계서가 다루는 항목은 전부 **본 PR의 정합성에 영향을 주지 않는다**. 운영 안정성·재발 방지·UX 후속 작업이다.

---

## 1. 사용성 테스트 결과 요약 (2026-05-17)

| 항목 | 결과 |
|---|---|
| Takeout archive | `data/takeout-20260511T130817Z-3-001/`, mp4 10개 (박연경 6주차 + 7주차 cp 복제본 포함) |
| 자막(ASR) | **10/10 PASS** — `gpu-quantized` (large-v3 + int8_float16), 938 s |
| 음원 지문 (chromaprint fpcalc) | **10/10 PASS** |
| `retry_pending.json` 해소 | 10건 모두 (F-14 정상) |
| `content_reuse.db` symlink 자동 생성 | OK (F-25 정상) |
| nC2 페어 (10C2 = 45) | 모두 비교, 결과는 §2 |

박연경 6주차 ↔ 7주차 cp 페어가 normalized hamming **0.0000** / caption text **100 %** 일치로 1위 정확 식별. 나머지 44 페어는 0.4681–0.4878 (random baseline 0.5 근방) 분포로 명확히 분리. 본 사용성 테스트는 **PASS**.

다만 **첫 시도는 실패**했고, 그 원인이 §2 항목이다.

---

## 2. 발견 결함 인벤토리

### 2.1 ★ F-1 multi-output derivation 함정 — `commit 6450398` 으로 해소됨

**증상**: ASR 첫 시도가 10건 모두 `RuntimeError: Library libcublas.so.12 is not found or cannot be loaded` 로 실패. F-3a 의 CUDA error classification + LD_LIBRARY_PATH 힌트가 정확히 점화됨 (이게 진단의 결정적 단서였다).

**근본 원인**: `flake.nix` 의 `gpuLibPath` 가 `cudaPackages.cudnn`, `cudaPackages.cuda_nvrtc`, `cudaPackages.libcublas` 를 default `out` output으로 가리키지만, 이 3 derivation의 default `out` 은 `nix-support/` + `LICENSE` 만 가지고 실제 `.so` 는 별도 `.lib` output 에 격리되어 있다. `cuda_cudart` 는 default `out` 이 `lib/` 를 포함하는 일반 multi-output 구조라 단독으로는 동작.

**해소 commit**: `6450398 fix(flake): pick .lib output for cuda multi-output derivations (F-1 follow-up)`. `gpuLibPath` 의 모든 항목을 `(p.lib or p)` fallback 으로 변경. `nix flake check` 통과, fresh `nix develop .#gpu` shell 에서 4개 CUDA `.so` 모두 resolve 확인.

**다음 세션 작업**: 본 follow-up 의 발견이 향후 재발하지 않도록 2.2 / 2.3 의 가드를 추가한다.

### 2.2 F-12 `doctor` 의 `LD_LIBRARY_PATH (CUDA)` 검증이 너무 약하다 ★ 차기 PATCH

**증상**: §2.1 실패 시점에 `tube-scout doctor` 는 `LD_LIBRARY_PATH (CUDA)` 항목을 **PASS** 로 보고했다. 그러나 실제 `LD_LIBRARY_PATH` 에 등재된 store path 가 빈 디렉터리(LICENSE만) 였고, `libcublas.so.12` 는 어디에도 없었다.

**원인**: `cli/doctor.py` 가 `echo $LD_LIBRARY_PATH | tr ':' '\n' | grep cuda` 의 코드화에 머물고, "그 경로가 실제 디렉터리인지 + `libcublas.so.12` / `libcudnn.so.9` / `libnvrtc.so.12` / `libcudart.so.12` 가 그 안에 있는지" 를 검증하지 않는다. multi-output 함정 + nix-store GC 일부 회수 시나리오 모두 false PASS.

**권고 fix (F-12-followup)**:
1. `_check_ld_library_path_cuda()` 에 file existence 검사 추가. `LD_LIBRARY_PATH` 의 각 cuda-related path 에 대해 다음 중 1개 이상 존재 여부 확인:
   - `libcudnn.so.9`
   - `libnvrtc.so.12`
   - `libcublas.so.12` / `libcublasLt.so.12`
   - `libcudart.so.12`
2. 4 라이브러리 모두 확인되면 PASS, 부분이면 WARN, 0건이면 FAIL.
3. `--verbose` 시 어떤 path 가 비어 있는지 출력.
4. 신규 unit test: 임시 디렉터리에 mock store path 만들고 `tube-scout doctor` 가 각 케이스(전부 OK / 일부 missing / 전부 missing)에 대해 정확한 상태를 보고하는지 확인.

운영 영향 추정: 동일 false PASS 시나리오가 cudnn EULA upgrade / nixpkgs 업그레이드 / nix store GC 후 반복될 가능성 매우 높음. 1 시간 작업 가치 높음.

### 2.3 `flake.nix` + `CLAUDE.md` Consistency Invariants 보강

**현 상태**: `CLAUDE.md` Consistency Invariants(commit 44f3737, F-6)는 다음 3건만 명시:
1. devShell variant parity (`commonBuildInputs` ↔ `shellHook` LD_LIBRARY_PATH)
2. pyproject extras ↔ flake.nix co-change
3. PR self-check (`nix flake check` + dependency dlopen)

**누락된 invariant**: `cudaPackages.*` (그리고 일반적인 multi-output nixpkgs derivation) 를 `gpuLibPath` / `commonLibPath` 에 추가할 때 **default `out` output 이 lib/ 를 포함하는지 검증** 의무. §2.1 함정이 정확히 이 항목 부재 때문에 발생.

**권고 fix (F-6-followup)**:
1. `flake.nix` 의 `gpuLibPath` 주석 블록 위에 invariant 한 줄 추가:
   ```
   # NOTE: Multi-output derivations (cudaPackages.cudnn, cuda_nvrtc,
   # libcublas) store .so files in the .lib output, not default `out`.
   # Always use ``(p.lib or p)`` here. Verify with
   #   nix-build --no-out-link --expr '(... .lib).outPath'
   # after adding any new CUDA package.
   ```
2. `CLAUDE.md` Consistency Invariants §4 신설:
   ```
   4. **cudaPackages 의 multi-output 함정.** `cudaPackages.{cudnn,
      cuda_nvrtc, libcublas}` 등은 default `out` 이 LICENSE 만 갖고
      실제 `.so` 는 `.lib` output 에 있다. `gpuLibPath` 에 추가 시
      반드시 `.lib or .` fallback 패턴을 사용하고, fresh shell 에서
      `ls $LD_LIBRARY_PATH/libcublas.so.12` 등으로 실측 검증한다.
   ```

이 두 fix 는 같은 PR (또는 같은 commit) 으로 묶어 처리한다.

### 2.4 F-11 BUX-1 잔여 — plan v3 §13.3 "next cycle"

**커밋된 영역 (010c003)**:
- `signal.signal(SIGINT, handler)` 등록 + 종료 시 핸들러 복원
- `.partial` transcript 삭제
- `aborted_by_user` audit row (`ingest_orchestrator` stage)
- `sys.exit(130)`

**미구현 영역 (본 PR 범위 종료, 별도 사이클)**:
1. SIGINT 핸들러 내 `retry_manifest.add_or_update_failures(video_id=…, mp4_filename=…, failed_stage="aborted_by_user", failure_reason="aborted_by_user")` 직접 호출. 현재는 audit row 만 기록.
2. 잔여 작업 안내 print — Ctrl+C 시 stdout 에 "남은 video N건 / retry_pending entry M건 / 재개 명령: `tube-scout collect ingest --resume`" hint.
3. Progress bar 라벨 — "처리 중" 단일 spinner 대신 ASR vs fingerprint 단계별 구분 + per-video elapsed time. stall 오인 reduction.

**우선순위**: 1 = 중요(retry queue 적재 누락), 2/3 = UX 개선. 1을 다음 세션 PATCH 1 commit 으로, 2/3 은 옵션.

### 2.5 nC2 분석 자체의 CLI 정합성 — 별도 spec 후보

**관찰**: 본 사용성 테스트의 1:1 비교는 `_workspace/pairwise_compare.py` ad-hoc 스크립트로 수행했다. 정식 명령은:
- `tube-scout content scan --mode legacy --year-from <Y> --year-to <Y>` — year-pair 모델
- `tube-scout content scan --mode nc2 --professor <PID>` — professor pool 모델

본 사용성 시나리오("교수 무관 모든 영상 1:1 비교")가 두 mode 어디에도 깔끔히 들어맞지 않았다. 자교 채널의 일반적 운영 케이스이므로 별도 mode 가 필요할 수 있다.

**권고**: spec 019 (가속) 와는 별개로, "all-pair within channel" CLI 모드를 spec 020 후보로 검토. 또는 `--mode legacy` 의 year filter 를 optional 화. 사용자 결정 필요.

---

## 3. 가속 spec (참고)

`~/.claude/projects/-home-kjeong-localgit-tube-scout/memory/project_analysis_acceleration_candidates.md` 에 spec 019 시드로 Rust/Julia 후보 영역이 정리되어 있다:

- 우선순위 1: GPU pool 실효성 검증 (멀티 GPU 머신 필요)
- 우선순위 2: nC2 pair iteration PyO3 (Layer A culling Rust)
- 우선순위 3: chromaprint align SIMD/Rust
- 우선순위 4: find_match_spans 텍스트 매칭 Rust/Julia
- 우선순위 5: Layer C IDF Julia

진입 조건: ① 새 `gpu-pool` preset 멀티 GPU 실측 가속 검증 + ② nC2 실 운영 wallclock 측정 결과. 두 조건 모두 충족된 후에야 spec 019 작성 가치가 있다. 그 전 가속 작업은 premature optimization 위험.

본 인계서 §2 의 F-12 / F-1 / F-6 / F-11 follow-up 은 spec 019 와는 별개 흐름으로 다음 세션에서 우선 처리한다.

---

## 4. 다음 세션 진입 즉시 작업 순서 권고

1. 본 인계서 (`docs/incidents/2026-05-17-audit-v3-followups.md`) read.
2. F-12-followup (`cli/doctor.py` LD_LIBRARY_PATH 강화 + test) — 1 시간.
3. F-6-followup (`flake.nix` 주석 + `CLAUDE.md` invariant §4) — 30 분.
4. F-11-followup (SIGINT 시 retry_manifest add 호출, +잔여작업 print 옵션) — 1–2 시간.
5. (사용자 결정 시) spec 020 또는 `--mode legacy` 옵션 확장 — 2.5 항목.
6. (사용자 결정 시) 0.6.0 release / master merge / GitHub PR 절차.

진입 조건: 본 branch (`fix/audit-v3-20260517-incident`) 가 origin 에 push 되어 있고, 다음 세션이 이를 기준으로 추가 commit 을 쌓는다.
