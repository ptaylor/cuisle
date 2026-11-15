# AGENTS.md

Instructions for any human or AI agent working in this repository.

## Summary

**Cuisle** (Irish for pulse or vein) is a macOS-only, always-on monitor for
processes, network connections, link health and throughput. A launchd user agent
samples the machine, writes to a local SQLite database, and serves a
loopback-only dashboard; a CLI queries the same data. It is observability only:
it never changes network settings, kills processes, or sends data anywhere
except the probe anchors the user configures.

## Status

**Design stage — no runtime code yet.** This file and `README.md` define the
intended architecture, command surface and invariants. The first implementation
milestone is a package scaffold with config, SQLite schema and tests; the
samplers, probes, dashboard and launchd integration follow. Do not describe the
tool as working until `pytest` passes and `cuisle doctor` runs on a real Mac.

Milestones, in order:

1. Scaffold: package, config, SQLite schema/migrations, `doctor`, tests,
   `install.sh`, `.gitignore`, `pyproject.toml`.
2. Samplers: processes, sockets, interfaces (with optional Wi-Fi detail).
3. Health probes: DNS/TCP/TLS/HTTP/ICMP per anchor and scope.
4. Throughput: `networkQuality`, bounded regional HTTP transfers, and optional
   Ookla Speedtest and iperf3 backends, with battery and data-cost guards.
5. Storage: event log, rollups, retention and pruning.
6. Interfaces: CLI, loopback dashboard and self-contained HTML report.
7. Service: launchd install/uninstall/status, log paths and restart behaviour.

Known gaps to settle during implementation:

- **Regional throughput needs anchors the user trusts.** No hard-coded
  third-party URL is guaranteed to stay in its region. Health probes work with
  any host; throughput needs a URL that supports a bounded or range read, or an
  Ookla/iperf3 anchor. Upload needs a writable endpoint, an Ookla server or an
  iperf3 server. An anchor that cannot be verified is reported as unavailable,
  never silently trusted.
- **Wi-Fi names are gated.** SSID/BSSID/signal need the optional PyObjC
  CoreWLAN/CoreLocation extra, and names also need Location Services
  authorisation for the host terminal app. Without them, Cuisle reports the
  interface type and traffic but not Wi-Fi names.
- **Full per-process visibility is unavailable without root.** Cuisle never
  asks for `sudo`; metrics that need it are reported as unavailable, not
  guessed or returned as zero.

## Commands

Planned entry points. The first commit that adds the scaffold must make these
exact commands work.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # core + pytest/ruff
.venv/bin/pip install -e ".[corewlan]"     # optional Wi-Fi details
./install.sh ~/bin                         # idempotent symlink

.venv/bin/python -m pytest                 # no live network required
.venv/bin/python -m ruff check .
./tools/make-icons.sh                      # rebuild PNGs/favicon (ImageMagick)
.venv/bin/cuisle doctor                    # tools, permissions, anchors, paths
.venv/bin/cuisle daemon run                # foreground; the only daemon mode
.venv/bin/cuisle service install           # launchd LaunchAgent
.venv/bin/cuisle dashboard                 # http://127.0.0.1:8787
.venv/bin/cuisle status
```

Rules for commands:

- No command, install step or test may require `sudo`.
- `pytest` must pass with no network access; live probes are exercised through
  fixtures and a fake clock/runner.
- `ruff check .` must pass with the default rule set (import sorting included),
  matching `../wifi` and `../bu`.
- `./tools/make-icons.sh` is deterministic: it renders from the SVG, strips
  metadata and writes PNG32. Re-running it with an unchanged SVG must leave
  every generated file byte-identical.
- `daemon run` stays in the foreground and logs to stderr; launchd is the only
  supported way to keep it running.
- Every query and report command supports `--json`, with units in the key name
  (`latency_ms`, `down_bps`, `rssi_dbm`). Operational commands (`daemon`,
  `service`) print plain status and do not need JSON.

## Layout

The implementation does not exist yet; this is the intended layout.

| Path | What it is |
| --- | --- |
| `src/cuisle/cli.py` | Command definitions: `status`, `watch`, `processes`, `connections`, `health`, `speed`, `history`, `report`, `dashboard`, `service`, `doctor`, `config`, `paths`. |
| `src/cuisle/config.py` | TOML loading, defaults, path resolution and environment overrides. |
| `src/cuisle/daemon.py` | Scheduler, signal handling, sleep/wake gap detection, sampler isolation. |
| `src/cuisle/samplers/processes.py` | Host and per-process CPU, memory, threads and network deltas. |
| `src/cuisle/samplers/connections.py` | TCP/UDP sockets from `netstat`, PID-to-name mapping, per-socket deltas. |
| `src/cuisle/samplers/interfaces.py` | Active route, addresses, Wi-Fi/Ethernet classification, link counters. |
| `src/cuisle/samplers/health.py` | DNS/TCP/TLS/HTTP/ICMP probes per anchor and scope. |
| `src/cuisle/samplers/throughput.py` | Throughput scheduling and result normalisation. |
| `src/cuisle/backends.py` | HTTP, optional Ookla Speedtest and optional iperf3 throughput backends. |
| `src/cuisle/probes.py` | Individual probe implementations and result types (no scheduling). |
| `src/cuisle/networkquality.py` | `networkQuality -c` invocation and JSON parsing. |
| `src/cuisle/db.py` | SQLite schema, migrations (`PRAGMA user_version`), queries, retention. |
| `src/cuisle/rollup.py` | Raw to 5-minute/hourly aggregates and scheduled pruning. |
| `src/cuisle/server.py` | Loopback HTTP server, JSON API, and `/icon.svg` / `/favicon.ico` / `/apple-touch-icon.png` routes. |
| `src/cuisle/dashboard.html` | Single-file dashboard (inline CSS/JS/SVG); links the icon as favicon and header logo. |
| `src/cuisle/icons/icon.svg` | Single source of the Cuisle mark: a heartbeat pulse on a network ring. |
| `src/cuisle/icons/*.png`, `favicon.ico` | Rasterised README/favicon/app sizes; generated by `tools/make-icons.sh` and committed. |
| `src/cuisle/report.py` | Self-contained HTML report generated from the database. |
| `src/cuisle/model.py` | Dataclasses shared by samplers, storage and renderers. |
| `tests/` | pytest suite; `tests/fixtures/` holds real command output with regeneration commands. |
| `install.sh` | Symlinks the `cuisle` command into the target directory; warns when it is not on `PATH`. |
| `tools/make-icons.sh` | Rasterises the icon SVG with ImageMagick; flat filled shapes only. |
| `pyproject.toml` | Package metadata, dependencies, package data (`icons/*`), pytest and ruff config. |

## Technology Stack

### Python

- **Role**: the whole tool: daemon, samplers, CLI, HTTP server and tests.
- **Version**: `>=3.11` (`requires-python`), because `tomllib` and modern typing
  are used; developed on 3.13.2.
- **Best Practices**:
  - `from __future__ import annotations` in every module; type hints on public
    functions.
  - Use the standard library for SQLite, HTTP, TLS, JSON, time and subprocess
    before adding a package.
  - Keep samplers independent: one failure must not stop the daemon or the
    other samplers.
  - Never parse a human table when a JSON/CSV mode exists; when only text
    exists, commit a fixture and test the parser.
  - Use `time.monotonic()` for scheduling and `time.time()` for recorded
    timestamps; store UTC.
- **Docs**: https://docs.python.org/3/

### psutil

- **Role**: host CPU/memory, per-process CPU/RSS/threads/status/username, and
  interface addresses/statistics.
- **Version**: `>=5.9` (7.1.3 observed); core dependency.
- **Best Practices**:
  - `Process.cpu_percent()` needs repeated calls to be meaningful; keep one
    `Process` cache and compute deltas rather than a fresh blocking call per
    process.
  - `Process.io_counters()` does **not** exist on macOS and
    `net_connections()` raises `AccessDenied` for other users' PIDs. Do not
    build network byte counts on psutil; use `netstat -anv`.
  - `net_if_addrs()` and `net_if_stats()` work without root and are the
    reliable way to map addresses to interfaces (Python 3.13 here has no
    `socket.getifaddrs()`).
  - Handle `NoSuchProcess`, `AccessDenied` and `ZombieProcess` per process;
    never let one PID abort a sample.
- **Docs**: https://psutil.readthedocs.io/

### macOS network tools

- **Role**: the data sources macOS exposes without root: `netstat`, `nettop`,
  `ping`, `route`, `scutil`, `ifconfig`, `networksetup`, `pmset`,
  `networkQuality` and `dig`.
- **Version**: shipped by macOS; developed against macOS 15.7.9 (Darwin 24.6.0).
  `networkQuality` requires macOS 12+; target macOS 13+ and verify at `doctor`
  time.
- **Best Practices**:
  - Invoke with explicit arguments and kill handling; never rely on locale,
    aliases or the user's shell profile.
  - Parse from a JSON or CSV mode where one exists (`networkQuality -c`);
    otherwise parse a committed fixture.
  - Record the tool, method and interface with every sample; never compare
    samples from different methods.
  - Treat a missing tool as "unavailable" and name the metric that is lost; do
    not crash the daemon.
- **Docs**: `man netstat`, `man nettop`, `man ping`, `man scutil`,
  `man networkQuality`, `man pmset`.

### Ookla Speedtest CLI (optional)

- **Role**: optional regional throughput backend. It measures download, upload
  and latency against a server chosen by ID, which is the practical way to get
  an upload figure for a specific country.
- **Version**: the current Ookla binary from the `teamookla/speedtest` tap; not
  a Python dependency. `cuisle doctor` must run `speedtest --version` and
  reject the old Python `speedtest-cli` shim.
- **Best Practices**:
  - Install with `brew tap teamookla/speedtest && brew update && brew install
    speedtest --force`; accept the licence explicitly with `--accept-license`
    (the first run prompts).
  - Use `speedtest -f json -s <server_id>` and parse the JSON. Find IDs with
    `speedtest -L`; record the server ID, name and URL with the sample. The
    JSON's `download.bandwidth` and `upload.bandwidth` are bytes per second;
    convert to bits per second before storing `down_bps`/`up_bps`.
  - Never scrape the human-readable output; never auto-install the tool; never
    run it without an anchor that names a server.
  - It sends data to Ookla's servers. Apply the same battery, expensive-link and
    interval guards as any throughput test, and say so in the privacy section.
- **Docs**: https://www.speedtest.net/apps/cli

### iperf3 (optional)

- **Role**: optional regional throughput backend against a server the user
  controls; the most private way to measure upload and download to a region.
- **Version**: `iperf3` 3.x (3.22 current when this was written); not a Python
  dependency and not installed on this machine by default.
- **Best Practices**:
  - Client: `iperf3 -c <host> -p <port> -t <seconds> -J`. The default direction
    is upload to the server, `-R` is download, and `--bidir` is both.
  - Server: `iperf3 -s -p <port>` on a host you control. Never use a public
    iperf3 server without permission, and never assume one exists.
  - Parse the JSON; record host, port, direction, duration and backend. The
    endpoint's `bits_per_second` is already in bits; map the direction to
    `down_bps` or `up_bps` explicitly. Apply the same battery, expensive-link
    and data guards.
- **Docs**: https://software.es.net/iperf/ · https://iperf.fr/

### PyObjC + CoreWLAN/CoreLocation (optional `corewlan` extra)

- **Role**: SSID, BSSID, RSSI, noise, channel, band and transmit rate for the
  active Wi-Fi link, plus the Location Services state that explains redaction.
- **Version**: `pyobjc-framework-CoreWLAN>=10.0` and
  `pyobjc-framework-CoreLocation>=10.0`; optional so the core tool installs
  and runs without them.
- **Best Practices**:
  - Import lazily inside the Wi-Fi sampler; absence degrades to interface type
    only.
  - Never unwrap a CoreWLAN value; every property can be `nil` (redaction,
    unsupported hardware).
  - Use only the documented API. Do not read `scanRecord` SPI or undocumented
    properties; `../wifi` documents the traps.
  - Redaction is not hidden: report `<redacted>` separately from a genuinely
    non-broadcasting network.
  - Never call `requestWhenInUseAuthorization()` unless the user explicitly
    asks; the permission belongs to the host terminal app.
- **Docs**: https://pyobjc.readthedocs.io/ ·
  https://developer.apple.com/documentation/corewlan

### SQLite (standard library `sqlite3`)

- **Role**: local time-series store for samples, events and rollups.
- **Version**: whatever ships with Python; WAL mode, foreign keys on,
  `busy_timeout` set.
- **Best Practices**:
  - One writer (the daemon); readers use their own connections. Batch inserts
    in one transaction per flush.
  - Schema changes go through `_migrate`, gated by `PRAGMA user_version`; never
    rewrite the database on startup.
  - Bound growth: store top-N process rows and non-zero socket deltas, not
    every PID every 5 seconds; roll up and prune on a schedule.
  - Store timestamps as integer epoch milliseconds (UTC); convert only for
    display.
  - Index `(ts)` on every sample table and `(anchor, ts)` / `(pid, ts)` where
    queried.
- **Docs**: https://docs.python.org/3/library/sqlite3.html ·
  https://sqlite.org/wal.html

### click

- **Role**: CLI command and option parsing, matching `../wifi` and `../bu`.
- **Version**: `click>=8.1`.
- **Best Practices**:
  - Commands return structured data to a renderer; keep formatting out of
    command bodies.
  - Every query command has `--json`; errors go to stderr with a non-zero exit.
  - Do not use click for the daemon's scheduling or HTTP server.
- **Docs**: https://click.palletsprojects.com/

### Vanilla JavaScript dashboard

- **Role**: the loopback-only web UI served by `server.py`.
- **Version**: browser-native ES2020+; no build step, no framework, no CDN.
- **Best Practices**:
  - One `dashboard.html` with inline CSS/JS/SVG, per the house rule on embedded
    assets.
  - Escape every server-supplied string before inserting it into markup; use
    `textContent` where possible.
  - Fetch the JSON API; never embed a snapshot of live data in the HTML.
  - Keep charts as inline SVG built from the returned series; no chart library
    unless it earns its place.
  - The dashboard is read-only. Destructive actions, if ever added, go through
    the CLI or an explicit confirmed endpoint.
- **Docs**: https://developer.mozilla.org/docs/Web/JavaScript

### ImageMagick (build-time, icons)

- **Role**: rasterises `src/cuisle/icons/icon.svg` into the PNG sizes, the
  Apple touch icon and `favicon.ico`.
- **Version**: ImageMagick 7 (`magick`); developed against the installed
  `/usr/local/bin/magick`.
- **Best Practices**:
  - The SVG uses filled rectangles, circles and polygons only. This build has
    no librsvg delegate, and its MSVG renderer silently drops gradients,
    transforms, dashes, filters and stroked paths.
  - Render once at high density, resize with `-strip`, and force `PNG32:` so
    transparency and deterministic output survive.
  - ImageMagick is build-time only; it is not a runtime dependency and `doctor`
    does not require it.
  - Run `./tools/make-icons.sh` after editing the SVG and commit the SVG and
    every generated file together.
- **Docs**: https://imagemagick.org/

### launchd

- **Role**: keeps the daemon running as a per-user LaunchAgent across login,
  crashes and reboots.
- **Version**: macOS built-in; `launchctl bootstrap/bootout` on modern macOS.
- **Best Practices**:
  - Write `~/Library/LaunchAgents/com.ptaylor.cuisle.plist`; never install a
    root daemon.
  - `RunAtLoad` plus `KeepAlive` with a `ThrottleInterval`;
    `cuisle service stop` uses `launchctl bootout` so KeepAlive does not fight
    it.
  - Set `ProcessType=Background`, `Nice=5`, `LowPriorityIO=true`; log to
    `~/Library/Logs/cuisle/`.
  - Use absolute interpreter/program paths in the plist; a symlink into the
    repo is not guaranteed to survive.
  - `service status` reports `launchctl print gui/$UID/com.ptaylor.cuisle`;
    `doctor` checks the plist and log paths.
- **Docs**: https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html

### pytest and ruff (`dev` extra)

- **Role**: tests and linting.
- **Version**: `pytest>=8.0`, `ruff>=0.6`; configured in `pyproject.toml`.
- **Best Practices**:
  - Tests are offline and deterministic: fake the clock and the command
    runner; use committed fixtures for parsers.
  - Never assert on live network counts, timings or interface names; they vary
    legitimately.
  - Add a test for every parser and every rule that protects the database from
    unbounded growth.
  - `ruff check .` must pass; match the sibling repos' default rule set (no
    custom ignore list).
- **Docs**: https://docs.pytest.org/ · https://docs.astral.sh/ruff/

## macOS facts — do not relearn these the hard way

1. **`netstat -anv -p tcp|udp` is the primary socket source.** It exposes
   per-socket `rxbytes`/`txbytes`, the owning `pid`, state and both addresses
   without root. `psutil.Process.io_counters()` does not exist on macOS, and
   `psutil.net_connections()` raises `AccessDenied` for other users' PIDs. Do
   not build per-process byte counts on psutil.
2. **netstat addresses use `.` before the port**, e.g.
   `192.168.192.58.49677` and `fe80::...%en0.49662`; parse from the right,
   handle `*.*` and `*.port`, and do not assume `:`. IPv6 zone IDs (`%en0`)
   appear in the local address.
3. **`nettop -J` accepts only a fixed column set.** `pid` and `state` are not
   valid names, and an invalid name prints the help text instead of failing —
   which looks like a parse bug. Use nettop only as a cross-check or for its
   `-t wifi|wired|expensive` filter; use netstat for the data.
4. **`nettop -L` process rows are `name.pid` and the name is truncated** (15
   characters). Map the PID through psutil/`ps` rather than displaying the
   label.
5. **`ping` flags are macOS-specific.** `-W` is milliseconds (unlike Linux's
   seconds), `-c` is the count, and fractional `-i` below one second requires
   root. A 3-packet probe therefore takes about 3 seconds; do not run one per
   anchor per second. `ping` as a normal user works for ICMP echo here.
6. **`networkQuality` is a capacity test, not a ping.** `-c` writes JSON; `-M`
   caps runtime; `-s` runs sequentially; `-I` binds an interface. One run
   transferred about 75 MB down and 17 MB up in 15 seconds, so never schedule
   it like a health probe. It measures to Apple's edge (`test_endpoint`, e.g.
   `iedub1-edge-bx-002.aaplimg.com`), not an arbitrary region.
7. **`networkQuality` timestamps have no timezone** (`2026-11-15
   20:21:07.400`). Parse as local time and convert to UTC explicitly; do not
   treat them as UTC.
8. **`scutil --nwi` and `route -n get default` disagree in useful ways.**
   `scutil` reports reachability per interface; `route` reports the interface
   that actually carries the default route. Record both: a VPN/tunnel
   (`utun*`) may be the default route while the physical uplink is `en0`. Do
   not attribute all traffic to the tunnel and call it the link.
9. **Do not assume `en0` is Wi-Fi.** `networksetup -listallhardwareports` maps
   devices to ports; docks add `en5`/`en6`/`en7` (USB LAN) and `bridge0`
   (Thunderbolt). Refresh the mapping periodically and classify by port name,
   not device number.
10. **CoreWLAN redacts SSID/BSSID without Location Services authorisation.**
    This is a permission of the **host terminal app**, not of Python or
    Cuisle. `nil` means withheld, not absent. Never prompt automatically;
    `doctor` explains the state and the path to grant it. A genuinely hidden
    AP exposes its BSSID; a redacted one may not.
11. **Python 3.13 on this Mac has no `socket.getifaddrs()`.** Use
    `psutil.net_if_addrs()` or parse `ifconfig`; do not copy code that assumes
    the stdlib helper exists.
12. **Counters are cumulative and reset.** Per-socket counters vanish when a
    socket closes; host and interface counters reset on interface reset. Delta
    only within the same key and session; clamp negatives to zero and record a
    reset event instead of a huge spike.
13. **Sleep/wake is not an outage.** A gap larger than twice the sampling
    interval is a `sleep_gap` event; skip delta-based metrics for that
    interval. Clock changes (NTP, manual) must not create negative or enormous
    rates.
14. **Probe methods are not interchangeable.** DNS timing includes resolver
    caching; ICMP can be blocked; TCP connect proves reachability but not the
    application; TLS adds handshake time; HTTP may follow redirects or be
    blocked. Store the method with every sample and never compare a DNS
    latency with an HTTP total.
15. **Regional anchors must be verified, not assumed.** A CDN or Anycast host
    answers from the nearest PoP: `www.gov.ie` resolves to CloudFront and
    `ftp.heanet.ie` to CloudFront, even though HEAnet is in Ireland.
    `www.heanet.ie` resolves to HEAnet's own `193.1.193.205` and is a usable
    Irish health anchor. Third-party throughput URLs change;
    `doctor --anchors` must resolve, connect and read a bounded number of
    bytes before an anchor is trusted.
16. **Battery and data cost are part of correctness.** `pmset -g batt` gives
    the power source. Default to pausing throughput and `networkQuality` on
    battery and on interfaces macOS marks expensive. A monitor that drains
    the battery or burns a data allowance is broken even if its numbers are
    right.
17. **The dashboard is loopback-only.** Bind `127.0.0.1` by default; a
    non-loopback bind requires an explicit flag, a warning and a token. There
    is no authentication on loopback, so never expose it to the LAN "just for
    a moment".
18. **SQLite is a single-writer system.** One daemon writer; dashboard readers
    get their own connection and `busy_timeout`. Never hold a write
    transaction while a probe or HTTP request runs.
19. **The `speedtest` on this Mac is a broken Python shim, not Ookla's CLI.**
    `~/Library/Python/3.8/bin/speedtest` imports a missing `speedtest` module.
    The official binary is `speedtest` from the `teamookla/speedtest` tap; the
    Homebrew `speedtest-cli` formula is a different, older Python tool.
    `doctor` must distinguish them by `speedtest --version` and must not treat
    the shim as available.
20. **Ookla, iperf3 and HTTP are different measurements.** Ookla measures
    against its own server, iperf3 against a server you run, and the HTTP
    backend against configured URLs. Their numbers are not interchangeable;
    store the backend and server with every sample and keep them in separate
    series.
21. **iperf3 direction is easy to get backwards.** The default client sends to
    the server (upload from the Mac); `-R` makes the server send (download);
    `--bidir` does both and reports two directions in one JSON document. Map
    the result to the correct label before storing it.

## Project rules

- **Read-only, always.** Cuisle never changes network settings, kills or
  throttles processes, edits other apps' data or clears caches. The only writes
  are to its own config, database, logs and report files.
- **No `sudo`.** If a metric needs root, record it as unavailable and name the
  gap in `doctor` and the dashboard. Do not silently return zero.
- **Do not guess.** Distinguish `unknown`, `unavailable`, `zero` and `down`. A
  missing SSID is not a hidden network; a failed probe is not a dead link; a
  sleeping Mac is not an outage.
- **Every sample carries its method, backend and interface.** Never mix Wi-Fi
  and Ethernet, ICMP and TCP, HTTP, Ookla and iperf3, download-only and
  upload+download, or a full test and a partial one in the same series.
- **Optional backends are optional.** `speedtest` and `iperf3` are external
  tools, never Python dependencies. `doctor` detects them; Cuisle never
  auto-installs them, never runs one without an anchor that names a server, and
  records the backend and server with every sample. A missing tool is
  "unavailable", not a failure.
- **Bound the database by construction.** Top-N process rows per interval,
  process rows only when CPU/memory/network is non-trivial, socket rows only
  for deltas or interesting states, hourly rollups, scheduled pruning. "We
  will add retention later" is not acceptable.
- **Sampler isolation.** A failing tool, permission error or malformed line
  logs once per failure class, backs off, and never stops the daemon or the
  other samplers.
- **Conservative defaults.** 5 s processes, 10 s connections and interfaces,
  30 s health, 6 h regional throughput, 12 h `networkQuality`; pause the heavy
  tests on battery and expensive links. Every interval is configurable.
  `speedtest` and `iperf3` transfer real data and get the same guards.
- **Privacy by default.** No telemetry, no cloud account, no reverse DNS
  unless configured, no packet capture, no content. Only configured probe
  traffic leaves the machine. The database, logs and dashboard stay local.
- **Time is explicit.** Store UTC epoch milliseconds; display in the system
  timezone; use monotonic time for schedules; record clock jumps and sleep gaps
  as events.
- **Tests never touch the network.** Live probes are adapted through a runner
  interface and tested with fixtures. A test that needs `ping`,
  `networkQuality`, `speedtest`, `iperf3` or a real interface is an integration
  test, excluded from the default run.
- **Keep the docs and the schema in step.** A new metric means a model, a
  column, a migration, a parser test, an API field, a dashboard label and an
  entry here in the same commit.

## Icon

`src/cuisle/icons/icon.svg` is the single source of the mark: a heartbeat pulse
on a network ring.

- The dashboard serves `/icon.svg`, `/favicon.ico` and `/apple-touch-icon.png`
  from the package and links them in `dashboard.html`:

  ```html
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <img src="/icon.svg" alt="" width="28" height="28">
  ```

- The SVG is flat on purpose. This ImageMagick build has no librsvg delegate;
  its MSVG renderer silently drops gradients, transforms, dashes, filters and
  even stroked paths. Use filled rectangles, circles and polygons only. A
  stroked design rasterises as a blank tile, which is how the first draft of
  this icon failed.
- Regenerate with `./tools/make-icons.sh`. It writes 16/32/48/64/128/192/256/
  512/1024 PNGs, a full-bleed `apple-touch-icon.png` (180) and a multi-size
  `favicon.ico`. ImageMagick is build-time only; `doctor` does not require it.
- Commit the SVG and every generated file in the same commit. These are app
  assets, not build output: do not add `src/cuisle/icons/` to `.gitignore`, and
  include `icons/*` in package data when the scaffold lands.
- Generated artefacts carry their attribution: the SVG header and
  `tools/make-icons.sh` name the assistant and tooling.

## Keeping `.gitignore` current — required

`.gitignore` is part of a change, never a follow-up to it. When a change creates
files that should not be committed, the patterns go in **the same commit** — a
cached thumbnail committed by accident is much harder to remove than a line is
to add.

Keep current, at minimum:

- **Tool and dependency output**: build directories, package caches, virtual
  environments, downloaded models and sample media, generated index files.
- **Local state**: config and env files (`*.env`, `.env.local`), log files, and
  anything naming this machine or a user's home directory.
- **Editor and OS metadata**: `.DS_Store`, `.vscode/`, `.idea/`, `*.swp`.

Rules:

- Prefer the official patterns published for the technology over invented ones;
  check the tool's own documentation rather than guessing.
- Group patterns by reason, each under a comment saying which tool or platform it
  belongs to, so the next reader can tell what a pattern is for.
- **Never** ignore editor tooling by reflex where the team may want it shared: an
  ignore rule is a commitment, and adding an un-ignore afterwards (`!.vscode/…`)
  is confusing. Ignore the specific local artefacts, not the whole directory, when
  that distinction matters.
- **Never commit secrets** — ignore the file that holds them. If one is committed
  by accident, say so in the commit that removes it rather than deleting it
  quietly, because the history still has it.
- The failure to watch for is the opposite of the usual one: ignoring a file the
  tool needs at run time. If it is needed to run or to build, it is source and it
  belongs in git.

For this project, the scaffold commit must add at least:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# cuisle runtime data (never commit a database or its WAL/SHM files)
*.db
*.db-wal
*.db-shm
*.log
reports/

# Local configuration
*.env
.env.*
*.local.toml

# macOS
.DS_Store
.AppleDouble
.LSOverride

# Editors
.idea/
*.swp
```

`tests/fixtures/` stays tracked: the tests read it at run time. Do not add a
broad `fixtures/` ignore.

`src/cuisle/icons/` is also tracked: the SVG and the generated PNGs/favicon are
app assets, not build output. Do not add an `icons/` ignore.

## Commit conventions

- Imperative sentences, no conventional-commit prefix: "Extract keyframes with a
  scene-change threshold".
- The subject says what changed; the body says **why**, and records the trap that
  was avoided or the measurement that justified the choice.
- One logical change per commit.

## AI attribution — required

Any commit produced with an AI coding assistant — for the code, the docs, the
artwork, or the commit message itself — must end with a trailer naming the
assistant **and** the exact model, its version, and the effort level it ran at:

```
Assisted-by: <assistant> (<model> <version>, effort: <level>)
```

```
Assisted-by: GitHub Copilot (DeepSeek V4 Flash, effort: high)
```

```
Assisted-by: Claude Code (Sonnet 5.5, effort: high)
```

Rules:

- Name the model you were actually running, and its version when it has one.
  "AI", "Copilot", "an LLM" or a bare tool name is not attribution.
- State the effort (reasoning) level the model was set to, as the tool names it
  (`low`, `medium`, `high`, …), because it changes how much to trust the work.
  If the tool has no such setting, leave the `effort:` part out; never guess.
- One trailer per assistant: two assistants on one commit means two
  `Assisted-by:` trailers.
- Use `git commit --trailer "Assisted-by=GitHub Copilot (DeepSeek V4 Flash, effort: high)"`
  rather than hand-placing the line, so it lands in the trailer block.
- No trailer means the work was written by hand. Never add one for a change you
  did not make.

### Elsewhere, not only in commits

Git history is not the only place this is read, so the same attribution applies
wherever the work is visible without it:

- **Documents and prose** substantially written by an assistant — this file,
  `README.md`, design notes — carry the assistant, model, version and effort level, either as a
  note in the document or in a short "AI contributions" list.
- **Release notes, changelogs, tags and pull-request descriptions** written with
  an assistant end with the same `Assisted-by:` trailer.
- **Generated artefacts** that are committed (thumbnails, classification output,
  fixtures) record in their header or in the command that regenerates them which
  tooling and which assistant produced them, so the result can be reproduced.

When in doubt, attribute. An unnecessary trailer costs a line; a missing one
misrepresents who wrote the work.

## General house rules

- **License**: every repository ships a `LICENSE`. Default to MIT. Use
  AGPL-3.0-or-later when the project links or invokes GPL-licensed tooling (for
  example a `--enable-gpl` FFmpeg build), or when the work should stay reusable by
  AGPL projects.
- **README**: every repository has a README that says what the project is, how to
  install it, and how to use it.
- **Install**: command-line tools install via an idempotent `install.sh` that
  symlinks into `$HOME/bin`, and warn when `$HOME/bin` is not on `PATH` (zsh).
- **Prefer self-contained, low-dependency tooling**: plain stdlib/Python or vanilla
  web tech over frameworks unless a dependency earns its place, and single-file
  scripts with embedded frontend assets over separate `static/` folders.
- **Verify before claiming done**: run the build, tests, linters, or a dry run and
  record the outcome in the commit body.
- **Keep this file current**: when a change introduces a language, library, or
  dependency, update `AGENTS.md` in the same commit — with rationale, a Best
  Practices block, and docs links — and add the matching `.gitignore` patterns in
  that same commit.

## AI contributions

`AGENTS.md` and `README.md` were written by Claude Code (DeepSeek Flash,
effort: high) on 2026-11-15. The session reported `CLAUDE_EFFORT=high`. The
Cuisle icon (`src/cuisle/icons/icon.svg`), `tools/make-icons.sh` and the
rasterised derivatives were generated by the same assistant in the same
session. Commits produced in this session use the trailer:

```
Assisted-by: Claude Code (DeepSeek Flash, effort: high)
```

Any later change written with an assistant must add its own record under the
rules above.
