# 008 Admin Web UI — Deployment Guide

**Spec**: `specs/008-admin-web-ui/`
**Module**: `nix/module.nix` (re-exported as `inputs.tube-scout.nixosModules.default`)
**Audience**: 운영자(DX지원센터장) — NixOS 본 서버 1회 셋업
**Last updated**: 2026-04-29

본 문서는 `services.tube-scout-admin-web` NixOS 모듈을 운영 NixOS 호스트에
배포하는 절차를 기술한다. 모든 시크릿은 [agenix](https://github.com/ryantm/agenix)로
암호화되며, Nix store에 평문이 저장되는 일은 없다 (Constitution VI).

---

## 1. 사전 요건

| 항목 | 버전/조건 |
|------|----------|
| NixOS | 24.05+ (flakes + agenix 모듈 사용 가능) |
| agenix | flake input `github:ryantm/agenix` |
| 사내 도메인 | `tube-scout.bhug.local` (또는 동등) — TLS 인증서 발급 가능 |
| Reverse proxy | nginx 또는 Caddy (HTTPS 종단 + UDS upstream) |
| 빌드된 패키지 | `tube-scout` Python distribution — `bin/uvicorn` 진입점 노출 |

---

## 2. agenix 시크릿 등록

### 2-1. 시크릿 키 매니페스트

agenix 중앙 저장소(또는 `./secrets/secrets.nix`)에 다음 항목을 추가한다.

```nix
# secrets/secrets.nix
let
  serverHost = "ssh-ed25519 AAAA... root@tube-scout-host";
  operator   = "ssh-ed25519 AAAA... operator@workstation";
in
{
  "tube-scout-shared.age".publicKeys     = [ serverHost operator ];
  "tube-scout-physiology.age".publicKeys = [ serverHost operator ];
  "tube-scout-nursing.age".publicKeys    = [ serverHost operator ];
  # 학과 추가 시 한 줄씩 append
}
```

### 2-2. 공유 시크릿 파일 형식 (`tube-scout-shared.age`)

`agenix -e tube-scout-shared.age`로 편집. 내용은 systemd
`EnvironmentFile=` 호환 **`KEY=VALUE` 라인**이어야 한다 (`export` 키워드,
인용부호, 인라인 주석 모두 금지).

```ini
TUBE_SCOUT_ADMIN_USERNAME=moogwa
TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT=$2b$12$REPLACE_WITH_REAL_HASH_60_CHARS_TOTAL
TUBE_SCOUT_SESSION_SECRET=REPLACE_WITH_64_HEX_CHARS_FROM_OPENSSL
```

비밀번호 해시 사전 생성:

```bash
nix shell nixpkgs#python311Packages.bcrypt -c \
  python -c 'import bcrypt, getpass; \
             print(bcrypt.hashpw(getpass.getpass("pw: ").encode(), \
                                  bcrypt.gensalt(rounds=12)).decode())'
```

세션 서명 키 생성:

```bash
openssl rand -hex 32
```

### 2-3. 학과별 시크릿 파일 형식 (`tube-scout-<alias>.age`)

학과 alias가 `physiology`이면 키 접미사는 `PHYSIOLOGY` (대문자, 하이픈은
`_`로 치환).

```ini
TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY=UCxxxxxxxxxxxxxxxx
TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY={"web":{"client_id":"...apps.googleusercontent.com","client_secret":"...","redirect_uris":["http://localhost:8000/oauth/callback"]}}
TUBE_SCOUT_API_KEY_PHYSIOLOGY=AIzaSy...
```

JSON 안의 큰따옴표는 그대로 두되, 외부에 별도 따옴표를 두르지 않는다
(systemd `EnvironmentFile` 파서는 라인 첫 `=` 이후 전부를 값으로 취급).

### 2-4. Constitution VI 준수 체크

- [ ] `flake.nix` / `nix/module.nix`에 평문 시크릿 0건
- [ ] `*.age` 파일만 `secretsDir`에 존재
- [ ] `departments.json`에는 alias·표시명·env 변수**명**만 (값 0건)
- [ ] 본 문서 예시는 모두 더미 (`UCxxxx...`, `AIzaSy...`, `REPLACE_*`)

---

## 3. NixOS 모듈 활성화

### 3-1. flake input 등록

```nix
# /etc/nixos/flake.nix (운영 호스트)
{
  inputs = {
    nixpkgs.url      = "github:NixOS/nixpkgs/nixos-unstable";
    agenix.url       = "github:ryantm/agenix";
    tube-scout.url   = "github:ecoinfos/tube-scout";  # 또는 path:/srv/tube-scout
    tube-scout.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = inputs@{ self, nixpkgs, agenix, tube-scout, ... }: {
    nixosConfigurations.tube-scout-host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        agenix.nixosModules.default
        tube-scout.nixosModules.default
        ./configuration.nix
      ];
    };
  };
}
```

### 3-2. 호스트 configuration

```nix
# /etc/nixos/configuration.nix (발췌)
{ config, pkgs, inputs, ... }:

{
  # tube-scout 패키지는 운영자가 별도 derivation으로 빌드한 결과를 주입.
  # uv2nix / poetry2nix / mkPoetryApplication 등 환경에 맞게 선택.
  services.tube-scout-admin-web = {
    enable = true;
    package = inputs.tube-scout.packages.x86_64-linux.default;  # 예시
    secretsDir = ./secrets;                                      # *.age 위치
    departmentAliases = [ "physiology" "nursing" ];
    # extraEnvironment.TUBE_SCOUT_LOG_LEVEL = "INFO";  # 필요 시
  };

  # nginx 또는 Caddy (§4 참조)
  services.nginx.enable = true;
}
```

### 3-3. 적용

```bash
sudo nixos-rebuild switch --flake /etc/nixos#tube-scout-host
sudo systemctl status tube-scout-admin-web.service
journalctl -u tube-scout-admin-web -f
```

부팅 시 `validate_required_env`가 `TUBE_SCOUT_ADMIN_USERNAME` /
`_PASSWORD_BCRYPT` / `_SESSION_SECRET` 존재 + bcrypt 형식을 검증한다.
실패하면 service가 startup에서 즉시 종료되며 `journalctl`에 누락된
변수명이 기록된다 (값은 노출되지 않음 — Fail-Fast).

---

## 4. Reverse proxy 구성

unit은 `unix:/run/tube-scout/admin-web.sock`에 바인딩한다. nginx/Caddy는
HTTPS를 종단하고 UDS upstream으로 트래픽을 전달한다.

### 4-1. nginx 스니펫

```nginx
upstream tube_scout_admin {
    server unix:/run/tube-scout/admin-web.sock;
}

server {
    listen 80;
    server_name tube-scout.bhug.local;
    return 308 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name tube-scout.bhug.local;

    ssl_certificate     /var/lib/acme/tube-scout.bhug.local/fullchain.pem;
    ssl_certificate_key /var/lib/acme/tube-scout.bhug.local/key.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    charset utf-8;

    # 분석 작업 진행률 폴링용 — 기본 60s는 너무 짧다.
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    client_max_body_size 16m;

    location / {
        proxy_pass         http://tube_scout_admin;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # PDF/Excel 등 결과물 정적 다운로드 — Starlette FileResponse로 직접 송출.
    location /jobs/ {
        proxy_pass         http://tube_scout_admin;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_buffering    off;  # 큰 PDF 스트리밍을 위해 버퍼링 해제
    }
}
```

nginx 사용자(`nginx` 또는 `nobody`)는 `/run/tube-scout` 디렉터리에 접근
가능해야 한다. 모듈은 기본적으로 mode 0750으로 디렉터리를 만들고 그룹은
`tube-scout`로 둔다. nginx를 보조 그룹에 추가:

```nix
users.users.nginx.extraGroups = [ "tube-scout" ];
```

### 4-2. Caddy 스니펫 (대체)

```caddy
tube-scout.bhug.local {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000; includeSubDomains"
    reverse_proxy unix//run/tube-scout/admin-web.sock {
        transport http {
            read_timeout 10m
            write_timeout 10m
        }
        header_up X-Forwarded-Proto {scheme}
    }
}
```

```nix
users.users.caddy.extraGroups = [ "tube-scout" ];
```

### 4-3. HTTP → HTTPS 강제

애플리케이션 층의 `HttpsRedirectMiddleware`도 `X-Forwarded-Proto`를 보고
308을 응답한다(FR-004b). nginx/Caddy 양쪽에서 강제하므로 어느 한쪽이
빠져도 기능은 유지된다.

---

## 5. 운영

### 5-1. 로그

| 출처 | 위치 |
|------|------|
| 부팅/lifespan/uvicorn stdout | `journalctl -u tube-scout-admin-web` |
| 애플리케이션 로거 | `${stateDir}/logs/admin-web.log` (기본 `/var/lib/tube-scout/logs/`) |
| 작업별 진행 로그 | `${stateDir}/projects/{job-id}/job.log` |

journald는 자동 로테이션이 적용되지만, 파일 로그는 별도 설정이 필요하다.

### 5-2. logrotate 권고

```nix
services.logrotate.settings.tube-scout = {
  files = [ "/var/lib/tube-scout/logs/*.log" ];
  frequency = "daily";
  rotate = 30;
  compress = true;
  delaycompress = true;
  missingok = true;
  notifempty = true;
  create = "0640 tube-scout tube-scout";
  postrotate = ''
    systemctl kill -s HUP tube-scout-admin-web.service || true
  '';
};
```

`postrotate`는 application logger가 SIGHUP에서 재오픈하지 않을 경우
생략 가능 (Python `logging.handlers.WatchedFileHandler` 기본 동작에 한해
inode 변경을 자동 감지).

### 5-3. admin.db 백업

SQLite 파일은 WAL 모드로 동작하므로 단순 `cp`는 위험하다. systemd timer로
SQLite online backup API를 사용:

```nix
systemd.services."tube-scout-db-backup" = {
  description = "Snapshot tube-scout admin.db";
  serviceConfig = {
    Type = "oneshot";
    User = "tube-scout";
    Group = "tube-scout";
    ExecStart = ''
      ${pkgs.sqlite}/bin/sqlite3 \
        /var/lib/tube-scout/admin.db \
        ".backup '/var/lib/tube-scout/backups/admin-$(date -Is).db'"
    '';
  };
};

systemd.timers."tube-scout-db-backup" = {
  wantedBy = [ "timers.target" ];
  timerConfig = {
    OnCalendar = "daily";
    Persistent = true;
    RandomizedDelaySec = "30m";
  };
};

systemd.tmpfiles.rules = [
  "d /var/lib/tube-scout/backups 0700 tube-scout tube-scout - 30d"
];
```

`tmpfiles` 규칙의 마지막 필드 `30d`가 30일 경과 백업을 자동 삭제한다.
오프사이트 보관이 필요하면 별도 rsync/restic 스케줄을 추가.

### 5-4. 학과 추가 절차

1. agenix 저장소에 `tube-scout-<alias>.age`와 키 등록 (§2-1)
2. 운영 호스트의 `services.tube-scout-admin-web.departmentAliases`에 alias 추가
3. `sudo nixos-rebuild switch` — service가 재시작되며 새 EnvironmentFile 로드
4. `sudo -u tube-scout tube-scout admin add-department --alias <alias> ...` 로 `departments.json` 갱신
5. `tube-scout admin verify <alias>` 로 6단계 OAuth/토큰/채널 검증

---

## 6. 트러블슈팅

| 증상 | 원인 후보 | 해결 |
|------|----------|------|
| boot 직후 `MissingEnvError` | `*.age` 누락 또는 키 오타 | `journalctl -u tube-scout-admin-web` → 변수명 확인 → agenix 파일 갱신 |
| `bcrypt` 형식 오류 | `_PASSWORD_BCRYPT`에 평문 또는 따옴표 | `agenix -e` 후 `$2b$12$…` 60자만 단일 라인 |
| nginx 502 (Permission denied to socket) | nginx 사용자가 `tube-scout` 그룹 미가입 | `users.users.nginx.extraGroups = [ "tube-scout" ]` |
| 진행률 polling이 60s에서 끊김 | nginx `proxy_read_timeout` 기본값 | §4-1 600s로 상향 |
| `~/.config/tube-scout`에 쓰기 시도 실패 | `ProtectHome=true`가 차단 | 모듈이 주입한 `TUBE_SCOUT_CONFIG_DIR` 환경변수가 web 코드에서 사용되는지 확인 (`src/tube_scout/web/paths.py`) |
| OAuth 콜백 도착 안 함 | redirect URI 불일치 | Google Cloud Console에서 `https://tube-scout.bhug.local/oauth/callback` 등록 |
| WAL 파일 무한 증가 | shutdown 시 `wal_checkpoint(TRUNCATE)` 실패 | `journalctl`에 `lifespan shutdown: PRAGMA wal_checkpoint failed` 검색 → 디스크/권한 점검 |
| logrotate 후 빈 파일에 씀 | application logger가 새 inode 미감지 | §5-2의 `postrotate` SIGHUP 또는 `WatchedFileHandler` 사용 확인 |
| `admin.db is locked` 백업 실패 | 작업이 장기 트랜잭션 보유 | `sqlite3 .backup`은 안전 — 다른 도구가 락 잡았는지 점검 |

---

## 7. 보안 체크리스트 (배포 직후)

- [ ] `curl http://tube-scout.bhug.local/` → 308 → HTTPS
- [ ] DevTools에서 세션 쿠키 `Secure; HttpOnly; SameSite=Lax` 확인
- [ ] 응답 헤더에 `Strict-Transport-Security` 노출
- [ ] `journalctl -u tube-scout-admin-web | grep -i secret` → 평문 시크릿 0건
- [ ] `find /nix/store -name '*.age' -readable` → 0건 (agenix 산출물은 `/run/agenix`에만 존재)
- [ ] 잘못된 비밀번호 5회 → 6번째 시도 시 잠금 안내
- [ ] `psql`/`sqlite3 admin.db` 직접 접근 → root 또는 `tube-scout` 외 차단
- [ ] systemd-analyze security tube-scout-admin-web — exposure level OK 또는 MEDIUM 이하

---

## 8. 참고

- 모듈 소스: [`nix/module.nix`](../nix/module.nix)
- agenix README: <https://github.com/ryantm/agenix>
- Constitution VI (Secrets via agenix): `specs/008-admin-web-ui/spec.md` §Constitution
- quickstart 절차: `specs/008-admin-web-ui/quickstart.md`
