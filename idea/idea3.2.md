# tube-scout v3.2 — OAuth 전환, Rate Limiting, 파이프라인 개선, GPU 지원

## Background

tube-scout v3.1까지 구현된 기능은 정상 동작하나, 실제 운영 환경에서 다음 문제가 발생했다.
교무과에서 모든 학과의 YouTube 채널 계정을 관리하고 있어 API 키가 불필요하며,
다중 학과 분석을 위해 OAuth 기반 인증이 핵심이 되었다.
또한 214개 영상 수집 시 YouTube가 IP를 차단하는 문제, `collect all` 파이프라인의
멀티채널 미지원, 다중 머신 배포 시 OAuth 시크릿 동기화 부재 등이 확인되었다.

## Problem

- **DX지원센터 운영자**가 다수 학과의 YouTube 강의 영상을 분석할 때,
  API 키와 OAuth가 혼재하여 인증 경로가 복잡하고 오류가 발생한다.
- 영상 214개에 대해 transcript를 수집하면 YouTube가 IP를 즉시 차단한다.
  요청 간 지연이 없어 과도한 호출로 인식된다.
- `collect all` 명령이 `--channel` 옵션을 지원하지 않아,
  OAuth가 필요한 채널의 전체 수집 파이프라인을 한 번에 실행할 수 없다.
- 다른 머신에서 프로젝트를 사용할 때 OAuth 클라이언트 시크릿이 없어
  인증을 처음부터 다시 수행해야 한다.
- 감성분석, STT 등 ML 작업이 CPU에서만 실행되어 대량 영상 처리 시 병목이 된다.

## Desired Outcome

운영자가 학과 alias 하나만 지정하면 전체 수집-분석-리포트 파이프라인이
IP 차단 없이 완주되고, 어느 머신에서든 동일한 OAuth 시크릿으로 작업을 시작할 수 있다.
GPU가 있는 환경에서는 ML 분석이 자동으로 GPU를 활용한다.

### User Scenarios

- **DX지원센터 운영자**는 `tube-scout collect all --channel dept-nursing-science`
  한 줄로 해당 학과의 전체 데이터를 수집하고 싶다.
  왜냐하면 현재는 5개 명령을 개별 실행해야 하기 때문이다.
- **DX지원센터 운영자**는 214개 영상의 transcript를 IP 차단 없이 수집하고 싶다.
  왜냐하면 현재는 수집 시작 수십 초 만에 YouTube가 차단하기 때문이다.
- **다른 머신의 운영자**는 `nixos-rebuild switch` 후 바로 tube-scout를 사용하고 싶다.
  왜냐하면 OAuth 클라이언트 시크릿이 agenix로 동기화되어야 하기 때문이다.
- **GPU 서버 운영자**는 감성분석과 STT를 GPU로 실행하여 처리 시간을 단축하고 싶다.
  왜냐하면 214개 영상을 CPU로 분석하면 수 시간이 걸리기 때문이다.

## Constraints

- API 키 관련 코드는 레거시로도 남기지 않고 완전히 제거한다
- OAuth 클라이언트 시크릿은 agenix로 관리한다. 런타임 토큰(refresh 시 갱신)은
  agenix 대상이 아니며 `~/.config/tube-scout/tokens/`에 그대로 유지한다
- Rate limiting은 모든 외부 API 호출에 적용하되, 설정 가능해야 한다
- GPU 사용은 선택적이어야 한다 (GPU 없는 환경에서도 동작)

## Success Criteria

- SC-1: API 키 제거 — 코드베이스에 `YOUTUBE_API_KEY` 참조가 0건
- SC-2: `collect all --channel` — 단일 명령으로 5단계 수집 완주
- SC-3: Rate limiting — 214개 영상 transcript 수집 시 IP 차단 없이 완료
- SC-4: 다중 머신 — `nixos-rebuild switch` 후 OAuth client_secret 사용 가능
- SC-5: GPU — `TUBE_SCOUT_DEVICE=cuda` 설정 시 현재 및 향후 ML 작업이 GPU에서 실행
  - 현재: 감성분석(KR-FinBert), Whisper STT
  - v4 예정: sentence-transformers 임베딩(ko-sroberta-multitask), KoBERT/KoELECTRA
  - 모든 ML 서비스가 공통 device 설정을 참조

## Discussion Notes

> API 키는 교무과가 모든 학과 계정을 관리하므로 불필요하다는 결론.
> OAuth client_secret은 앱 자체의 시크릿이라 agenix로 관리 적합하지만,
> token.json은 런타임에 refresh되므로 agenix 부적합 — 머신별 독립 유지로 합의.
> IP 차단 문제는 youtube-transcript-api가 rate limit 없이 연속 호출하여 발생.
> collect all에 --channel을 추가하면 OAuth 기반 전체 파이프라인이 가능해진다.
> GPU는 sentiment(KR-FinBert), whisper STT, 향후 KoBERT/KoELECTRA에 활용 가능.
> 현재 코드에 device 지정이 전혀 없어 torch 자동감지에 의존하는 상태.
> Rate limiting: 바람직한 방안대로 적용. 요청 간 적절한 지연 + exponential backoff.
> OAuth 토큰: 머신별 독립 유지. client_secret만 agenix로 공유.
> idea4.md 검토 결과, v4의 sentence-transformers 임베딩 생성도 GPU 대상.
> v3.2에서 device 설정 인프라를 만들면 v4에서 바로 활용 가능.
> v4의 데이터 저장 경로는 projects/ 구조(v3.2에서 도입)를 따라야 한다.
