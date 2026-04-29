{ config, lib, pkgs, ... }:

# NixOS module — tube-scout admin web UI (008-admin-web-ui T100).
#
# Wires the Starlette + uvicorn admin web UI as a hardened systemd service
# behind a UDS socket. Secrets are injected as KEY=VALUE EnvironmentFile=
# entries produced by agenix; no plaintext credentials live in the Nix
# store (Constitution VI).
#
# The package itself is provided by the consumer (uv2nix/poetry2nix-built
# derivation). This module is responsible only for runtime wiring.
#
# Required agenix secret files (consumer-managed, never committed):
#   * tube-scout-shared.age
#       TUBE_SCOUT_ADMIN_USERNAME=<operator>
#       TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT=$2b$12$...
#       TUBE_SCOUT_SESSION_SECRET=<openssl rand -hex 32>
#   * tube-scout-{alias}.age (one per department in `departmentAliases`)
#       TUBE_SCOUT_CHANNEL_ID_<ALIAS_UPPER>=UC...
#       TUBE_SCOUT_CLIENT_SECRET_<ALIAS_UPPER>={"web":{...}}
#       TUBE_SCOUT_API_KEY_<ALIAS_UPPER>=AIzaSy...

with lib;

let
  cfg = config.services.tube-scout-admin-web;

  # Secret name set: shared + one per department alias.
  secretNames =
    [ "tube-scout-shared" ]
    ++ map (alias: "tube-scout-${alias}") cfg.departmentAliases;

  # /run/agenix/<name> is the canonical mount path produced by agenix.
  envFiles = map (n: "/run/agenix/${n}") secretNames;

  # Map of agenix secret declarations (one per name above).
  ageSecretsAttrs = listToAttrs (map (name: {
    name = name;
    value = {
      file = "${cfg.secretsDir}/${name}.age";
      owner = cfg.user;
      group = cfg.group;
      mode = "0400";
    };
  }) secretNames);
in
{
  options.services.tube-scout-admin-web = {
    enable = mkEnableOption "tube-scout admin web UI (Starlette + uvicorn)";

    package = mkOption {
      type = types.package;
      description = ''
        The tube-scout Python distribution. Must expose a `uvicorn` console
        script on `bin/` whose runtime PYTHONPATH includes `tube_scout` and
        all dependencies declared in pyproject.toml (starlette, uvicorn,
        bcrypt, itsdangerous, pydantic v2, jinja2, ...).
      '';
    };

    user = mkOption {
      type = types.str;
      default = "tube-scout";
      description = "System user that owns runtime dirs and runs the service.";
    };

    group = mkOption {
      type = types.str;
      default = "tube-scout";
    };

    socketPath = mkOption {
      type = types.path;
      default = "/run/tube-scout/admin-web.sock";
      description = ''
        UDS path uvicorn binds to. Reverse proxy (nginx/Caddy) must point
        its upstream at this socket and must run as a user/group that has
        read+write access to the parent directory `/run/tube-scout`.
      '';
    };

    stateDir = mkOption {
      type = types.path;
      default = "/var/lib/tube-scout";
      description = ''
        Persistent state directory bound into the unit via
        TUBE_SCOUT_CONFIG_DIR/STATE_DIR. Holds admin.db, projects/{job}/,
        logs/, locks/, and operator-managed departments.json.
      '';
    };

    secretsDir = mkOption {
      type = types.path;
      example = literalExpression ''./secrets'';
      description = ''
        Directory containing the *.age files referenced by `departmentAliases`
        and the shared file. The directory itself is consumer-managed and
        is *not* added to the Nix store unencrypted — agenix decrypts each
        file at activation time into /run/agenix/<name>.
      '';
    };

    departmentAliases = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "physiology" "nursing" ];
      description = ''
        Department aliases for which a `tube-scout-<alias>.age` secret file
        must exist in `secretsDir`. The bare name (no extension, no path) is
        also the systemd EnvironmentFile basename mounted at
        /run/agenix/tube-scout-<alias>.
      '';
    };

    socketDirMode = mkOption {
      type = types.str;
      default = "0750";
      description = ''
        Permission bits for the `/run/tube-scout` parent directory. Default
        0750 lets the reverse-proxy group reach the UDS while denying world
        access. Set to 0770 if nginx/Caddy run under a different group than
        `cfg.group` and rely on supplementary group membership.
      '';
    };

    extraEnvironment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      description = ''
        Additional non-secret environment variables to inject (e.g.
        `TUBE_SCOUT_LOG_LEVEL`). Secrets must come from the agenix files;
        anything placed here lands in the Nix store world-readable.
      '';
    };
  };

  config = mkIf cfg.enable {
    users.users.${cfg.user} = {
      isSystemUser = true;
      group = cfg.group;
      home = cfg.stateDir;
      createHome = false;  # systemd.tmpfiles owns this — see below.
      description = "tube-scout admin web UI service user";
    };
    users.groups.${cfg.group} = { };

    age.secrets = ageSecretsAttrs;

    systemd.tmpfiles.rules = [
      "d /run/tube-scout            ${cfg.socketDirMode} ${cfg.user} ${cfg.group} - -"
      "d ${cfg.stateDir}            0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.stateDir}/logs       0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.stateDir}/locks      0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.stateDir}/projects   0750 ${cfg.user} ${cfg.group} - -"
      "d ${cfg.stateDir}/tokens     0700 ${cfg.user} ${cfg.group} - -"
    ];

    systemd.services.tube-scout-admin-web = {
      description = "tube-scout admin web UI (Starlette + uvicorn)";
      after = [ "network.target" "agenix.service" ];
      wants = [ "agenix.service" ];
      wantedBy = [ "multi-user.target" ];

      environment = {
        PYTHONUNBUFFERED = "1";
        # paths.py three-tier resolver: direct env wins, no `/tube-scout`
        # suffix appended.
        TUBE_SCOUT_CONFIG_DIR = "${cfg.stateDir}";
        TUBE_SCOUT_STATE_DIR = "${cfg.stateDir}";
        TUBE_SCOUT_LOG_DIR = "${cfg.stateDir}/logs";
        TUBE_SCOUT_LOCK_DIR = "${cfg.stateDir}/locks";
      } // cfg.extraEnvironment;

      serviceConfig = {
        Type = "exec";
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.stateDir;

        # agenix mounts each *.age decrypted as KEY=VALUE at /run/agenix/<name>.
        # systemd merges the files in declaration order; later files win on
        # collision, so do not declare duplicate keys across departments.
        EnvironmentFile = envFiles;

        ExecStart = ''
          ${cfg.package}/bin/uvicorn tube_scout.web.app:create_app \
            --factory \
            --uds ${cfg.socketPath} \
            --no-access-log
        '';

        # Hardening — see `man systemd.exec`.
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        ProtectClock = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectProc = "invisible";
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        RestrictNamespaces = true;
        LockPersonality = true;
        # Keep MDWX off: huggingface/torch JIT and CFFI shims need writable
        # executable pages.
        MemoryDenyWriteExecute = false;
        RestrictRealtime = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" "~@privileged" "~@resources" ];
        ReadWritePaths = [ cfg.stateDir "/run/tube-scout" ];

        Restart = "on-failure";
        RestartSec = "5s";

        # File descriptor budget for many concurrent in-flight job tasks.
        LimitNOFILE = 65536;

        StandardOutput = "journal";
        StandardError = "journal";

        SyslogIdentifier = "tube-scout-admin-web";
      };
    };
  };
}
