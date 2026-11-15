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

**Working MVP.** The package, daemon, samplers, probes, SQLite store, rollups,
CLI, dashboard, report, icon pipeline and tests are implemented and run on
macOS 15.7.9. `pytest` passes 63 tests and `ruff check .` is clean.

Working and exercised on this Mac:

- Process, socket, interface and host sampling without `sudo`.
- DNS/TCP/TLS/HTTP/ICMP probes to the four default anchors.
- The HTTP throughput backend (tested against a local server) and
  `networkQuality` JSON parsing.
- The daemon loop, the loopback dashboard, the HTML report and `install.sh`.
- SQLite WAL storage, rollups, retention and the icon pipeline.
- The dashboard range/series selector and `cuisle history` read raw, 5-minute
  and hourly rollups for windows from 1 hour to 1 year; both were exercised
  against live rollups.

Known gaps, stated so they are not mistaken for working features:

- CoreWLAN is optional and not installed here, so Wi-Fi names and signal are
  unavailable until the `corewlan` extra and Location Services are enabled.
- The Ookla Speedtest and iperf3 backends are implemented and parser-tested but
  have not been run against the real tools on this machine: `speedtest` is the
  broken Python shim and `iperf3` is not installed.
- `cuisle service install` has been exercised up to plist generation; the
  launchd bootstrap path has not been installed on this Mac.
- The dashboard is a functional read-only single-page view, not a polished
  charting application. It shows average plus min/max; p50/p95 and zoom/pan are
  not implemented.
- Rollups are written by the hourly maintenance pass, so a freshly started
  daemon falls back to raw data for long windows until its first pass.
- There is no PyPI release; installation is editable from the repository.

## Commands

These work from the repository today.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # core + pytest/ruff
.venv/bin/pip install -e ".[corewlan]"     # optional Wi-Fi details
./install.sh ~/bin                         # idempotent symlink

.venv/bin/python -m pytest                 # 63 tests, no live network
.venv/bin/python -m ruff check .
./tools/make-icons.sh                      # rebuild PNGs/favicon (ImageMagick)

.venv/bin/cuisle doctor                    # tools, permissions, anchors, paths
.venv/bin/cuisle daemon run                # foreground; the only daemon mode
.venv/bin/cuisle daemon run --once         # one light sample, no throughput
.venv/bin/cuisle dashboard                 # opens http://127.0.0.1:8787
.venv/bin/cuisle dashboard --no-open       # print the URL only (headless)
.venv/bin/cuisle report --since 24h        # writes ./reports/*.html
.venv/bin/cuisle history --metric cpu_pct --since 30d --resolution auto
.venv/bin/cuisle status
.venv/bin/cuisle health --now              # run probes without the daemon
.venv/bin/cuisle speed --now               # runs networkQuality: ~90 MB
.venv/bin/cuisle speed --now --no-networkquality  # regional HTTP/backend only
.venv/bin/cuisle service install           # launchd LaunchAgent
```

Rules for commands:

- No command, install step or test may require `sudo`.
- `pytest` must pass with no external network access. Live probes are exercised
  through fixtures and a fake runner; the loopback dashboard and local HTTP
  backend tests are local-only.
- `ruff check .` must pass with the default rule set (import sorting included),
  matching `../wifi` and `../bu`.
- `./tools/make-icons.sh` is deterministic: it renders from the SVG, strips
  metadata and writes PNG32. Re-running it with an unchanged SVG must leave
  every generated file byte-identical.
- `daemon run` stays in the foreground and logs to stderr; launchd is the only
  supported way to keep it running.
- `daemon run --once` is deliberately light: it never starts a throughput test.
- Every query and report command supports `--json`, with units in the key name
  (`latency_ms`, `down_bps`, `rssi_dbm`). Operational commands (`daemon`,
  `service`) print plain status and do not need JSON.
- The dashboard and `history` must not mix probe methods in one series. Latency
  and loss default to ICMP; pass `--method` to choose another.

## Layout

The implementation is in place; this is the current layout.

| Path | What it is |
| --- | --- |
| `src/cuisle/cli.py` | Command definitions: `status`, `watch`, `processes`, `connections`, `health`, `speed`, `history`, `report`, `dashboard`, `daemon`, `service`, `doctor`, `config`, `paths`. |
| `src/cuisle/config.py` | TOML loading, defaults, validation, path resolution and environment overrides. |
| `src/cuisle/daemon.py` | Scheduler, signal handling, sleep/wake gap detection, sampler isolation. |
| `src/cuisle/samplers/processes.py` | Host and per-process CPU, memory, thread and network sampling. |
| `src/cuisle/samplers/connections.py` | TCP/UDP sockets from `netstat`, PID-to-name mapping, per-socket deltas. |
| `src/cuisle/samplers/interfaces.py` | Active route, addresses, Wi-Fi/Ethernet classification, link counters. |
| `src/cuisle/samplers/health.py` | DNS/TCP/TLS/HTTP/ICMP probes per anchor and scope. |
| `src/cuisle/samplers/throughput.py` | Throughput scheduling and result normalisation. |
| `src/cuisle/backends.py` | HTTP, optional Ookla Speedtest and optional iperf3 throughput backends. |
| `src/cuisle/probes.py` | Individual probe implementations and result types (no scheduling). |
| `src/cuisle/networkquality.py` | `networkQuality -c` invocation and JSON parsing. |
| `src/cuisle/db.py` | SQLite schema, writes, queries, the dashboard snapshot and rollup-aware `series_window`. |
| `src/cuisle/rollup.py` | Raw to 5-minute/hourly aggregates and scheduled pruning. |
| `src/cuisle/server.py` | Loopback HTTP server, JSON API (including rollup-aware `/api/series`), and `/icon.svg` / `/favicon.ico` / `/apple-touch-icon.png` routes. |
| `src/cuisle/dashboard.html` | Single-file dashboard (inline CSS/JS/SVG) with range/series selectors, a chart and the event list; links the icon as favicon and header logo. |
| `src/cuisle/service.py` | launchd plist generation, install/uninstall/start/stop/status. |
| `src/cuisle/util.py` | Duration parsing and human-readable byte/rate/time formatting. |
| `src/cuisle/icons/icon.svg` | Single source of the Cuisle mark: a heartbeat pulse on a network ring. |
| `src/cuisle/icons/*.png`, `favicon.ico` | Rasterised README/favicon/app sizes; generated by `tools/make-icons.sh` and committed. |
| `src/cuisle/report.py` | Self-contained HTML report generated from the database. |
| `src/cuisle/model.py` | Dataclasses shared by samplers, storage and renderers. |
| `tests/` | pytest suite (63 tests). |
| `tests/fixtures/` | Sanitised command output and schema-only JSON fixtures, with regeneration commands. |
| `.gitignore` | Python/runtime ignore rules; icons and fixtures stay tracked. |
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
- **Version**: `>=5.9` (7.2.2 in the dev venv); core dependency.
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
  - Tests use no external network: fake the clock and the command runner; use
    committed fixtures for parsers. The dashboard and HTTP-backend tests use
    loopback only.
  - Never assert on live network counts, timings or interface names; they vary
    legitimately.
  - Add a test for every parser and every rule that protects the database from
    unbounded growth.
  - `ruff check .` must pass. This ruff build's default select also includes
    BLE, PYI, SIM and S; a deliberate broad catch carries a targeted
    `# noqa: BLE001` with a reason, not a project-wide ignore.
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
    Irish health anchor. Third-party throughput URLs change; `doctor --anchors`
    runs the health probes, and a throughput run (`cuisle speed --now`) is what
    verifies the download URL or server ID before it is trusted.
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
22. **`netstat -ib` gives bytes and errors; `-i` gives packets.** Cuisle parses
    `-ib` for `Ibytes`/`Obytes` and `Ierrs`/`Oerrs`. Do not store packet counts
    in the byte columns.
23. **`psutil.cpu_percent(interval=None)` returns 0 on its first call.** The
    daemon primes host and per-process CPU before its first sample; without
    priming, `daemon run --once` shows a screen of 0% CPU.
24. **The first connection sample has no rates.** Socket counters are
    cumulative, so the first sample records sockets at 0 bps; the second sample
    produces the deltas. A one-shot `daemon run --once` correctly shows 0 bps
    and is not a bug.
25. **Read-only SQLite URIs need percent-encoding.** The default data directory
    is `~/.local/share/cuisle` (no space), but a user can choose one that
    contains spaces. Use `Path.resolve().as_uri() + "?mode=ro"`, not string
    concatenation.
26. **Never mix probe methods in one series.** The dashboard latency chart
    filters to ICMP; `history --metric latency_ms` defaults to ICMP and
    `--method` selects another. A DNS timing is not an HTTP time.
27. **The dashboard's first `/api/status` may have no probes.** Health probes
    run for several seconds at startup. The browser refreshes; do not treat the
    empty first snapshot as a failure or cache it.
28. **Long windows are read from rollups, never by limiting raw rows.** Raw is
    kept 7 days, 5-minute rollups 90 days and hourly rollups 365 days.
    `series_window` picks the source automatically, downsamples to the requested
    bucket count and keeps each bucket's average, minimum, maximum and count.
    A `LIMIT` on raw data for a long window silently shows only the newest
    slice; never do that.
29. **The dashboard range selector is global; the series selector is explicit.**
    One range (`1h` … `1y`) drives both History and Events. The series choice
    names the metric, scope, anchor and method/backend, so latency methods and
    throughput backends are never mixed. Durations accept `s/m/h/d/w/y`; `1y`
    is 365 days. The range is remembered in `localStorage` and can be
    deep-linked as `?range=1y`.

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
- **Prime CPU before the first sample.** `psutil.cpu_percent(interval=None)` is
  0 on its first call. `ProcessSampler.prime()` seeds host and per-process
  counters; without it `daemon run --once` reports a screen of zeros.
- **The first socket sample has no rates.** Socket counters are cumulative.
  Record first-seen sockets at 0 bps and let the second sample produce deltas;
  never invent a first rate.
- **Probe series are per method.** `history` and the dashboard filter latency
  and loss to one method; ICMP is the default. Do not average a DNS timing with
  an HTTP time.
- **Long-range series use rollups and downsampling.** Query `series_window` or
  `/api/series`, never raw `LIMIT` for a long window. Preserve the min/max band
  and sample count alongside the average. A missing rollup is a reason to fall
  back to a coarser source, not to invent points.
- **`daemon run --once` is light.** It takes one host/process/socket/interface
  sample and one health pass. It never runs a throughput test.
- **Read-only SQLite connections use `Path.as_uri()`.** The data directory
  contains a space; string-built `file:` URIs fail or escape the path.
- **Fixtures are sanitised.** Committed command output replaces local IPs, MAC
  addresses, hostnames and resolver addresses, and records the regeneration
  command. Never commit a real database, log or unsanitised capture.
- **Tests never touch the external network.** Live probes are adapted through a
  runner interface and tested with fixtures. The dashboard and HTTP-backend
  tests use loopback only. A test that needs `ping`, `networkQuality`,
  `speedtest`, `iperf3` or a real interface is an integration test, excluded
  from the default run.
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

For this project, the repository's `.gitignore` contains at least:

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
implementation in `src/cuisle/`, the tests and fixtures in `tests/`,
`pyproject.toml`, `install.sh` and `.gitignore` were written by the same
assistant in the same session. The Cuisle icon (`src/cuisle/icons/icon.svg`),
`tools/make-icons.sh` and the rasterised derivatives were also generated by it.
Commits produced in this session use the trailer:

```
Assisted-by: Claude Code (DeepSeek Flash, effort: high)
```

Any later change written with an assistant must add its own record under the
rules above.
