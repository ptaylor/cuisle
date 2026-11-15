<p align="center"><img src="src/cuisle/icons/icon.svg" alt="Cuisle icon: a heartbeat pulse across a network" width="96" height="96"></p>

# Cuisle

*Cuisle* — Irish for pulse or vein; a heartbeat for the network.

**A permanent, local-only monitor for macOS processes, connections, link health
and throughput.**

> **Status: working MVP.** The daemon, samplers, probes, SQLite store, CLI,
> dashboard, report, icon pipeline and tests work. The optional CoreWLAN,
> Ookla Speedtest and iperf3 paths are implemented but not all exercised on
> this machine; the launchd plist is generated and tested, but the agent was
> not installed here. See [Status](#status).
>
> The repository is `ptaylor/cuisle`; the installed command is `cuisle`.

## Status

Working and exercised on macOS 15.7.9:

- Process, socket, interface and host sampling without `sudo`.
- DNS/TCP/TLS/HTTP/ICMP probes to the default anchors.
- The HTTP throughput backend, tested against a local server, and
  `networkQuality` JSON parsing.
- The daemon loop, loopback dashboard, HTML report, rollups, retention and
  `install.sh`.
- 63 tests and a clean `ruff check .`.

Not yet exercised on this machine:

- CoreWLAN (optional extra not installed): Wi-Fi names and signal are
  unavailable; the interface and its traffic are still sampled.
- Live Ookla Speedtest and iperf3 runs: the installed `speedtest` is a broken
  Python shim and `iperf3` is not installed. Their backends and parsers are
  covered by tests with schema fixtures.
- `cuisle service install` beyond plist generation: installing a launchd agent
  on this Mac was deliberately left to the user.
- A long-running soak test. A 15-second daemon-loop smoke test produced host,
  process, socket, interface and probe samples and a live dashboard.


## What it does

Cuisle runs as a launchd user agent and keeps a local record of what the
machine's processes and network are doing. It answers questions that macOS only
answers one snapshot at a time:

- What is using my network right now, and what used it overnight?
- Are my connections healthy — on the LAN, in my country, in Europe, and
  worldwide?
- Is the Wi-Fi or Ethernet link itself degrading (signal, errors, retransmits)?
- How fast is the link, and how does that vary by destination and time of day?
- Did something change — a roam, an interface switch, a VPN, a new IP, a
  sleep/wake gap?

It observes. It does not change network settings, kill processes, block
connections or send your data anywhere. Everything is stored in a local SQLite
database and shown through a CLI and a dashboard that listens only on loopback.

## What it records

| Area | What is sampled |
| --- | --- |
| **Processes** | PID, name, user, CPU %, resident memory, thread count, state and start time. Network-active processes are ranked by bytes in and out. |
| **Connections** | TCP and UDP sockets: local and remote address, state, owning PID and per-socket bytes in/out. Listening and established sockets are both visible. |
| **Interfaces** | The interface carrying the default route, the physical port behind it (Wi-Fi, Ethernet, USB LAN, Thunderbolt, VPN), addresses, gateway, link speed and interface error counters. |
| **Wi-Fi (optional)** | SSID, BSSID, RSSI, noise, SNR, channel, band, width and transmit rate, when CoreWLAN and Location Services allow it. |
| **Health** | Per probe anchor: DNS resolution, TCP connect, TLS handshake and certificate expiry, HTTP status and time, and ICMP loss/jitter/latency. |
| **Throughput** | Per anchor: download and upload bits per second via HTTP, Ookla Speedtest or iperf3. Plus Apple `networkQuality` capacity, base RTT and responsiveness for the active interface. |
| **Events** | Link up/down, interface switch, IP change, Wi-Fi roam (when Wi-Fi detail is available), VPN change, sleep/wake gap and counter reset. |

Every sample records the interface and the probe method that produced it. A
missing value is stored as unknown or unavailable, never as zero.

## Why not an existing tool?

| Tool | What it gives | What it misses |
| --- | --- | --- |
| Activity Monitor | Live per-process CPU, memory and energy | No history, no per-connection bytes, no regional health |
| `nettop` | Live per-process and per-socket bytes | Cryptic, no history, no health checks, no dashboard |
| `networkQuality` | Capacity and responsiveness on demand | One-shot, Apple's endpoints only, no history |
| `ping` / `traceroute` | Path health on demand | Manual, one destination at a time, no record |
| Wi-Fi menu / `wifi` | Current link details | No process, connection or throughput history |
| Little Snitch and similar | Per-app rules and blocking | A firewall, not a passive historian |

Cuisle is the historian and the health check. It is not a firewall and does not
replace one.

## Measurement scopes

Measurements are grouped by how far away the destination is. The scopes are
configurable, because "local" and "international" mean different things on
different connections.

| Scope | What it answers | Default example |
| --- | --- | --- |
| `lan` | Is the router and local network healthy? | The default gateway, auto-detected |
| `country` | Is the path to my own country healthy? | A national host you trust |
| `europe` | Is the wider European path healthy? | A European host you trust |
| `international` | Is the global path healthy? | A host outside Europe you trust |

Anchors are ordinary configuration, not hard-coded addresses. Each one names a
scope, a host and port, the health methods to run, and optionally a throughput
backend with a download or upload URL. `cuisle doctor --anchors` runs the
configured health probes and reports what it can verify; a throughput run
(`cuisle speed --now`) is what verifies a download URL or server ID. An anchor
that fails is reported, not silently used.

### Anchors must be verified

A CDN or Anycast address answers from the nearest point of presence, so a
famous national domain can measure a local CDN edge rather than a national
path. Cases observed on this machine:

- `www.gov.ie` resolves through CloudFront, not to a host in Ireland.
- `ftp.heanet.ie` resolves through CloudFront, despite HEAnet being Irish.
- `www.heanet.ie` resolves to HEAnet's own `193.1.193.205` and is a usable
  Irish health anchor.

For throughput, a public file mirror in the target region is more honest than a
CDN URL, but third-party paths change. `doctor --anchors` checks health;
`cuisle speed --now` checks the throughput URL or server. The configuration is
meant to be edited. The default set assumes Ireland and is only an example. The
same applies to an Ookla server ID and an iperf3 host: a throughput run records
what it can verify and says when it cannot.

Upload throughput needs a writable endpoint, or an anchor that uses the
`speedtest` or `iperf3` backend. If neither is available, Cuisle records
download only and reports upload as unavailable for that anchor — it does not
report zero.

## How it works

```text
launchd (per-user LaunchAgent)
  └─ cuisle daemon run
       ├─ processes     5 s    psutil: CPU, memory, threads, process list
       ├─ connections  10 s    netstat -anv: sockets, bytes, PIDs
       ├─ interfaces   10 s    route / scutil / networksetup (+ CoreWLAN)
       ├─ health       30 s    DNS, TCP, TLS, HTTP, ICMP per anchor
       ├─ throughput    6 h    HTTP / speedtest / iperf3 per anchor
       └─ capacity     12 h    networkQuality -c (paused on battery)
             │
             ▼
       SQLite (WAL): raw samples + 5-minute/hourly rollups + events
             │
       loopback HTTP API ── dashboard (127.0.0.1:8787)
             │
       CLI ── status / watch / history / report
```

### Processes

`psutil` supplies host and per-process CPU, memory, thread counts and process
identity. It is also used for interface addresses. It is **not** used for
network byte counts: on macOS `Process.io_counters()` does not exist, and
`net_connections()` is denied for other users' processes.

### Connections and per-process network bytes

`netstat -anv -p tcp` and `-p udp` expose, without root, each socket's local and
remote address, state, owning PID, and cumulative receive/transmit bytes.
Cuisle deltas those counters per socket, maps the PID to a process name, and
aggregates per process. Per-process byte counts are therefore measured, not
inferred from interface totals.

### Interfaces and Wi-Fi

`route -n get default` gives the interface carrying the default route;
`scutil --nwi` gives reachability; `networksetup -listallhardwareports` maps
device names to physical ports, so a dock's USB Ethernet is not mistaken for
Wi-Fi. The active interface is labelled Wi-Fi or Ethernet on every sample.

If the optional CoreWLAN/CoreLocation extra is installed and the host terminal
has Location Services authorisation, the Wi-Fi SSID, BSSID, signal, noise,
channel, band and rate are added. Otherwise the interface is still monitored,
with the Wi-Fi-specific fields reported as unavailable.

### Health

Health is measured with the lightest method that answers the question:

- **DNS** — resolution time against the system resolver or a configured server.
- **TCP** — connect time to a host and port.
- **TLS** — handshake time and certificate expiry.
- **HTTP** — status, time to first byte and total time, with a bounded body
  read and a redirect limit.
- **ICMP** — loss, minimum/mean/maximum latency and jitter from a short
  `ping` run.

The method is stored with every result. A DNS timing is never compared with an
HTTP total, and a TCP connect is never presented as proof that an application
is healthy.

### Throughput

Three regional backends, plus Apple's capacity test. Each anchor names its
backend, and the backend is stored with every result:

- **`http` (default)** — fetch a bounded amount from `download_url` and
  optionally POST to `upload_url`. It works with any anchor, needs no extra
  tool, and can measure upload only where the anchor has a writable endpoint.
- **`speedtest` (optional)** — the Ookla CLI, pointed at a server ID chosen in
  the anchor. It reports download, upload, latency and jitter in one JSON
  document. Install it from the `teamookla/speedtest` tap; it is not the older
  Python `speedtest-cli`. The `speedtest` currently on this Mac is a broken
  shim, not Ookla's binary. Data goes to Ookla.
- **`iperf3` (optional)** — a client against a server you control. The default
  direction is upload, `-R` is download, and `--bidir` measures both. It is the
  most private regional option but needs a host you run and maintain.

**`networkQuality -c`** is separate: it measures the active interface against
Apple's edge (download, upload, base RTT, responsiveness), not a chosen region.
One run here transferred about 75 MB down and 17 MB up in 15 seconds, so it is
scheduled every 12 hours by default.

All throughput tests are skipped on battery and on interfaces macOS marks as
expensive unless the configuration allows it. They transfer real data; a
monitor that drains the battery or burns a data allowance is broken even when
its numbers are right. HTTP, Ookla and iperf3 results are different
measurements, so they are kept in separate series and never averaged together.

### Storage

SQLite in WAL mode, with one daemon writer and independent readers. Raw samples
are kept for 7 days, 5-minute rollups for 90 days, and hourly rollups for a
year. Growth is bounded by construction: only top-N process rows, only socket
deltas or state changes, and scheduled pruning. The database lives under
`~/.local/share/cuisle/`.

The dashboard and `cuisle history` read raw data for windows up to 7 days,
5-minute rollups up to 90 days, and hourly rollups up to a year. Long windows
are downsampled to about 300 chart buckets, each carrying an average, minimum,
maximum and sample count. Rollups are written by the hourly maintenance pass; a
fresh daemon therefore falls back to raw data until its first rollup run.

## Install

Install from the repository:

```sh
git clone https://github.com/ptaylor/cuisle.git
cd cuisle

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -e ".[corewlan]"   # optional Wi-Fi details

./install.sh ~/bin                       # symlink `cuisle` into ~/bin
cuisle doctor                            # check tools, paths and permissions
cuisle service install                   # launchd, starts at login
```

Requirements:

- macOS 13 or later (developed on macOS 15.7.9). `networkQuality` needs macOS
  12 or later.
- Python 3.11 or later.
- No `sudo`, at any point.
- Optional: the `corewlan` extra for Wi-Fi names and signal detail. Without it,
  the interface and its traffic are still monitored.
- Optional: the Ookla Speedtest CLI or `iperf3` for the `speedtest` and
  `iperf3` throughput backends. Install Ookla with
  `brew tap teamookla/speedtest && brew update && brew install speedtest --force`,
  or iperf3 with `brew install iperf3`. The older Python `speedtest-cli` is a
  different tool; `cuisle doctor` detects both and says which is available.

`install.sh` is idempotent, refuses to overwrite an unrelated file, and warns
when the target directory is not on `PATH`. The launchd agent is optional;
`cuisle daemon run` works without it.

To remove it:

```sh
cuisle service uninstall
rm ~/bin/cuisle
```

The database and logs are left in place; remove
`~/.local/share/cuisle` and `~/Library/Logs/cuisle` yourself if
you want them gone.

## Usage

Every query command prints a human table by default and JSON with `--json`.
Units are in the JSON key names (`latency_ms`, `down_bps`, `rssi_dbm`).

| Command | What it does |
| --- | --- |
| `cuisle status` | One-screen snapshot: link, health per scope, throughput and top processes. |
| `cuisle watch` | Refresh the snapshot in place; `--interval` sets the cadence. |
| `cuisle daemon run` | Run the sampler loop in the foreground; `--once` takes one light sample. |
| `cuisle processes` | Top processes by CPU, memory, received bytes or sent bytes. |
| `cuisle connections` | Sockets, filtered by state, process or address. |
| `cuisle health` | Latest latency, loss and jitter per anchor; `--now` runs the probes. |
| `cuisle speed` | Run a throughput test now with `--now` (`--backend` is `http`, `speedtest` or `iperf3`; `--no-networkquality` skips the ~90 MB Apple test), or show the last result. |
| `cuisle history` | Query a series over time (`--metric`, `--scope`, `--anchor`, `--method`, `--since`, `--resolution auto|raw|5m|1h`, `--points`). |
| `cuisle report` | Self-contained HTML report for a time range; writes to `./reports/` by default, `--output` overrides. |
| `cuisle dashboard` | Open the daemon's dashboard in the default browser; `--no-open` prints the URL, `--standalone` serves the database read-only. |
| `cuisle service` | `install`, `uninstall`, `start`, `stop`, `restart`, `status`. |
| `cuisle doctor` | Check tools, SQLite, launchd, permissions, anchors (`--anchors`) and optional backends. |
| `cuisle config` | Open the configuration file in `$EDITOR` (`--show` prints it). |
| `cuisle paths` | Show config, data, log and plist locations. |

### Illustrative output

Representative output; numbers vary:

```text
ACTIVE LINK
  Interface   en0 (Wi-Fi)
  SSID        example-net
  Address     192.168.192.58/24
  Gateway     192.168.192.1
  Signal      -57 dBm  SNR 39 dB  5 GHz  ch 44  80 MHz  866 Mbps
  Counters    1.2 G rx · 340 M tx · 0 errors · 0 drops

NETWORK HEALTH                          now     p50     p95    loss
  lan           gateway                   1 ms    1 ms    2 ms    0%
  country       www.heanet.ie            18 ms   19 ms   24 ms    0%
  europe        ftp.funet.fi             38 ms   39 ms   52 ms    0%
  international debian.osuosl.org         82 ms   84 ms  110 ms    1%

THROUGHPUT  (last capacity test 12 min ago, en0)
  networkQuality  down 620 Mbps · up 48 Mbps · base RTT 38 ms
  europe          down 180 Mbps · up unavailable (no upload endpoint)

TOP PROCESSES (network, last 60 s)
  Dropbox              4.2 MB rx   1.1 MB tx
  Google Chrome        2.8 MB rx   0.4 MB tx
  mDNSResponder      120.0 kB rx  90.0 kB tx

TOP PROCESSES (CPU, now)
  WindowServer          8.4%
  Google Chrome         6.1%
  kernel_task           4.2%
```

## Dashboard

The daemon serves a single-file dashboard at `http://127.0.0.1:8787`. It is
read-only and shows:

- **History and events** — the first cards on the page. A range selector in the
  header covers 1 hour, 24 hours, 7 days, 30 days, 90 days and 1 year. The
  History card has a series selector for latency per anchor/method, download
  and upload throughput per anchor/backend, and host CPU/memory. The chart
  draws an average line with a min/max band and axes; its source is chosen
  automatically from raw (up to 7 days), 5-minute rollups (up to 90 days) and
  hourly rollups (up to a year). The Events card uses the same range and shows
  the most recent 200 events. The chosen range is remembered on the device and
  can be deep-linked with `?range=1y` (or `1h`, `24h`, `7d`, `30d`, `90d`).
- **Active link** — interface, address, gateway, Wi-Fi signal, counters and
  errors.
- **Host** — CPU, memory, load and process count.
- **Network health** — the latest probe per anchor and method.
- **Throughput** — the latest result per anchor, including `networkQuality`.
- **Processes and connections** — top CPU/memory consumers, network talkers and
  recent active sockets.

The page is plain HTML with inline CSS, JavaScript and SVG. There is no build
step, no framework and no CDN. It binds to loopback only; remote access is not
implemented — use an SSH tunnel if you need it from another machine.

The Cuisle mark is the dashboard's favicon and header logo: the server serves
`/icon.svg`, `/favicon.ico` and `/apple-touch-icon.png` from
`src/cuisle/icons/`. The same files are used in this README and are available
for app packaging.

## Permissions, privacy and data

- **No `sudo`.** Cuisle uses only the interfaces macOS exposes to a normal user.
  Where that leaves a gap, it says so instead of guessing.
- **No telemetry and no cloud account.** The database, logs and dashboard are
  local. No data is sent to the project or a third party beyond the probe
  traffic described below.
- **Outbound traffic is only the probes you configure**: DNS, TCP, TLS, HTTP
  and ICMP to the anchors, plus `networkQuality` to Apple's edge when it is
  due. If an anchor uses the `speedtest` backend, that traffic goes to Ookla; if
  it uses `iperf3`, it goes to the server you name. Neither runs unless
  configured. ICMP and HTTP probes are small; capacity tests are not.
- **Wi-Fi names need Location Services.** macOS withholds SSID and BSSID from
  a process unless the *host terminal app* has authorisation. Cuisle reports
  the redaction and explains what to grant; it never prompts for location
  itself.
- **No content, no packet capture.** Cuisle records metadata: process names,
  addresses, ports, byte counts, timings and status codes. It does not capture
  packets, read payloads, decrypt TLS or record browsing history.
- **Retention is bounded.** Raw samples 7 days, 5-minute rollups 90 days,
  hourly rollups 1 year, all configurable. The retention job prunes in
  batches; the database does not grow without limit.

## Configuration

The file is TOML, at `~/.config/cuisle/config.toml`. Scalar settings have
defaults, so the file can start small; the anchors below are examples to
replace with hosts you trust.

```toml
[general]
data_dir = "~/.local/share/cuisle"
log_dir = "~/Library/Logs/cuisle"
dashboard_host = "127.0.0.1"
dashboard_port = 8787

[retention]
raw_days = 7
five_minute_days = 90
hourly_days = 365

[sampling]
process_seconds = 5
connection_seconds = 10
interface_seconds = 10
health_seconds = 30
throughput_seconds = 21600       # 6 hours
networkquality_seconds = 43200   # 12 hours

[battery]
pause_throughput = true
pause_networkquality = true
slow_health_seconds = 60

[throughput]
backend = "http"          # default; an anchor may override
download_bytes = 1_000_000
upload_bytes = 256_000
timeout_seconds = 30
allow_expensive = false

[[anchor]]
name = "gateway"
scope = "lan"
health = ["icmp"]
# host is taken from the default route

[[anchor]]
name = "ie-health"
scope = "country"
host = "www.heanet.ie"
port = 443
url = "https://www.heanet.ie/"
health = ["dns", "tcp", "tls", "http"]
# Example only: verify with `cuisle doctor --anchors`, then use an anchor
# you trust for your own country.

[[anchor]]
name = "eu-throughput"
scope = "europe"
host = "ftp.funet.fi"
port = 443
url = "https://ftp.funet.fi/"
health = ["dns", "tcp", "tls", "http"]
download_url = "https://ftp.funet.fi/pub/linux/mirrors/debian/dists/stable/main/Contents-amd64.gz"
# upload_url is omitted: upload throughput is reported as unavailable.

[[anchor]]
name = "world-throughput"
scope = "international"
host = "debian.osuosl.org"
port = 443
url = "https://debian.osuosl.org/debian/"
health = ["dns", "tcp", "tls", "http"]
download_url = "https://debian.osuosl.org/debian/dists/stable/main/Contents-amd64.gz"
```

### Optional speed-test backends

An anchor can override the default backend:

```toml
[[anchor]]
name = "eu-ookla"
scope = "europe"
backend = "speedtest"
server_id = 12345          # list servers with `speedtest -L`
health = ["dns", "tcp", "tls"]

[[anchor]]
name = "world-iperf"
scope = "international"
backend = "iperf3"
host = "iperf.example.net"
port = 5201
duration_seconds = 10
direction = "both"         # up (default), down (-R), both (--bidir)
health = ["tcp"]
```

Both tools are optional. `cuisle doctor` reports whether they are installed and
whether the configured server answers. An unavailable backend is reported as
unavailable, not as zero, and the backend name is stored with every result.

Environment overrides: `CUISLE_CONFIG_DIR`, `CUISLE_DATA_DIR`,
`CUISLE_LOG_DIR`. `cuisle paths` prints the effective values; `cuisle config`
opens the file.

The configuration contains no secrets. If an upload endpoint needs a token,
reference an environment variable rather than writing the token into the file.

## Limitations

- **macOS only.** The data sources are `netstat`, `route`, `scutil`,
  `networksetup`, `pmset`, `networkQuality` and CoreWLAN.
- **No root means no full visibility.** Sockets and process metrics that the
  operating system withholds are reported as unavailable. Cuisle does not ask
  for elevated privileges.
- **Wi-Fi names may be redacted.** Location Services authorisation belongs to
  the terminal app, and BSSIDs may remain withheld even when SSIDs are visible.
- **`networkQuality` measures Apple's edge, not an arbitrary region.** It is a
  capacity and responsiveness test, not a regional speed test. One run costs
  about 90 MB of transfer; the default interval reflects that.
- **Regional throughput depends on the anchors.** A CDN or Anycast URL answers
  from the nearest edge and defeats the geographic measurement. Upload needs a
  writable endpoint. Third-party anchors change; `doctor --anchors` checks
  health and a throughput run checks the URL.
- **Optional backends are external.** The Ookla CLI is third-party and sends
  test traffic to Ookla; its servers change. iperf3 needs a server you control.
  Neither is installed automatically. Their code paths and parsers are tested,
  but neither tool was available on the capture machine for a live run.
- **Backends are not comparable.** An HTTP transfer, an Ookla test and an
  iperf3 run measure different paths and methods. They are stored as separate
  series and never averaged together.
- **Per-process bytes are sampled.** Sockets that open and close entirely
  between two samples can be missed. UDP has no connection state, so a "UDP
  connection" means a bound or associated socket. The first sample of a
  one-shot run records sockets at 0 bps; the second produces rates.
- **VPNs and tunnels complicate attribution.** A `utun*` interface may carry
  the default route while the physical uplink is `en0`. Cuisle records both and
  labels the tunnel; it cannot see inside it.
- **Sleep is recorded, not interpolated.** A gap is an event, not an outage
  and not a zero.
- **No packet capture or content inspection.** This is deliberate.
- **The dashboard has no authentication.** It is loopback-only by design.
- **Charts show average, minimum and maximum; not p50/p95.** There is no zoom,
  pan or tooltip yet, and each chart is a fixed ~300-bucket view.
- **Rollups arrive hourly.** A freshly started daemon has raw data only until
  its first maintenance pass, so 30/90-day and 1-year views can look sparse at
  first.
- **The CLI shows raw series, not percentile summaries.** `history` and the
  dashboard chart the samples or rollups that exist; p50/p95 aggregation is not
  implemented yet.
- **Launchd installation was not exercised here.** Plist generation is tested;
  installing the agent on this Mac was left to the user.
- **No PyPI release.** Install is editable from the repository.

## Development

Run the tests and lint:

```sh
.venv/bin/python -m pytest        # 63 tests, offline
.venv/bin/python -m ruff check .
.venv/bin/cuisle doctor
```

The suite uses sanitised command fixtures and a fake runner; the dashboard and
HTTP-backend tests use loopback only. A test that needs a live interface,
`ping`, `networkQuality`, `speedtest` or `iperf3` is an integration test and is
not part of the default run.

### Icon

`src/cuisle/icons/icon.svg` is the single source of the mark: a heartbeat pulse
on a network ring. The dashboard serves `/icon.svg`, `/favicon.ico` and
`/apple-touch-icon.png` from that directory.

After editing the SVG, regenerate the PNG sizes and favicon:

```sh
./tools/make-icons.sh
```

ImageMagick is a build-time tool, not a runtime dependency. The SVG is
deliberately flat — filled rectangles, circles and polygons only. This
ImageMagick build has no librsvg delegate, and its MSVG renderer drops
gradients, transforms, dashes, filters and even stroked paths, so a stroked
design would rasterise as a blank tile. Commit the SVG, the generated PNGs and
`favicon.ico` together.

The layout and the rules for adding a metric are in
[`AGENTS.md`](./AGENTS.md).

## Roadmap

- [x] Design documents
- [x] Icon, PNG sizes and favicon
- [x] Package scaffold, configuration, SQLite schema and migrations
- [x] Process, connection and interface samplers
- [x] Health probes and anchor verification
- [x] Throughput tests with battery and data-cost guards
- [x] Rollups, retention and events
- [x] CLI, dashboard and HTML report
- [x] launchd service and `install.sh`
- [x] Optional Ookla Speedtest and iperf3 backends for regional throughput
- [x] Long-range, rollup-backed dashboard history and events
- [ ] Live soak test and real regional anchor tuning
- [ ] CoreWLAN/Location Services verification on a granted terminal
- [ ] Percentile summaries for `health` and `history`
- [ ] Publish to PyPI

## License

MIT — see [`LICENSE`](./LICENSE).

## AI contributions

This README, `AGENTS.md`, the implementation in `src/cuisle/`, the tests and
fixtures, `pyproject.toml`, `install.sh` and `.gitignore` were written by
Claude Code (DeepSeek Flash, effort: high) on 2026-11-15. The session reported
`CLAUDE_EFFORT=high`. The Cuisle icon (`src/cuisle/icons/icon.svg`),
`tools/make-icons.sh` and its rasterised derivatives were generated by the same
assistant in the same session.
