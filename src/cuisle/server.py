"""Loopback HTTP server and JSON API for the dashboard."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cuisle import db
from cuisle.config import Config
from cuisle.util import DAY_MS, parse_since

LOG = logging.getLogger("cuisle.server")
ASSETS = {
    "icon.svg": "image/svg+xml",
    "favicon.ico": "image/x-icon",
    "apple-touch-icon.png": "image/png",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}


def _asset_bytes(name: str) -> bytes:
    return files("cuisle").joinpath("icons", name).read_bytes()


def _dashboard_html() -> bytes:
    return files("cuisle").joinpath("dashboard.html").read_bytes()


def status_payload(conn: Any, now_ms: int) -> dict[str, Any]:
    snapshot = db.status_snapshot(conn, now_ms - 15 * 60 * 1000)
    snapshot["server_time"] = now_ms
    for row in snapshot["interfaces"]:
        row["is_up"] = bool(row.get("is_up"))
        row["is_default"] = bool(row.get("is_default"))
    for row in snapshot["probes"]:
        row["success"] = bool(row.get("success"))
    for row in snapshot["throughputs"]:
        row["success"] = bool(row.get("success"))
    snapshot["stale"] = snapshot["host"] is None or now_ms - snapshot["host"]["ts"] > 60_000
    return snapshot


class Handler(BaseHTTPRequestHandler):
    server_version = "Cuisle"
    db_path: Path
    config: Config

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        path = url.path
        query = parse_qs(url.query)
        if path == "/":
            self._send(_dashboard_html(), "text/html; charset=utf-8")
            return
        if path == "/healthz":
            self._json({"ok": True})
            return
        if path in ("/icon.svg", "/favicon.ico", "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"):
            try:
                data = _asset_bytes(path.lstrip("/"))
            except FileNotFoundError:
                self._json({"error": "icon not found"}, status=404)
                return
            self._send(data, ASSETS[path.lstrip("/")])
            return
        if not path.startswith("/api/"):
            self._json({"error": "not found"}, status=404)
            return

        try:
            conn = db.connect(self.db_path, readonly=True)
        except FileNotFoundError:
            self._json({"error": "no database yet; start the daemon"}, status=503)
            return
        try:
            if path == "/api/status":
                self._json(status_payload(conn, _now_ms()))
            elif path == "/api/series":
                self._json(self._series(conn, query))
            elif path == "/api/processes":
                since = _since(query, "1h")
                sort = _first(query, "sort", "cpu")
                limit = _int(query, "limit", 25, 1, 500)
                self._json({"processes": db.processes_since(conn, since, sort, limit)})
            elif path == "/api/connections":
                since = _since(query, "15m")
                limit = _int(query, "limit", 50, 1, 500)
                self._json(
                    {
                        "connections": db.connections_since(
                            conn,
                            since,
                            state=_first(query, "state", None),
                            process=_first(query, "process", None),
                            limit=limit,
                        )
                    }
                )
            elif path == "/api/events":
                since = _since(query, "24h")
                limit = _int(query, "limit", 50, 1, 500)
                self._json({"events": db.events_since(conn, since, limit)})
            elif path == "/api/config":
                self._json(self.config.as_dict())
            else:
                self._json({"error": "not found"}, status=404)
        except Exception as exc:
            LOG.exception("API request failed: %s", path)
            self._json({"error": str(exc)}, status=500)
        finally:
            conn.close()

    def _series(self, conn: Any, query: dict[str, list[str]]) -> dict[str, Any]:
        metric = _first(query, "metric", "cpu_pct") or "cpu_pct"
        now = _now_ms()
        since = _since(query, "1h")
        scope = _first(query, "scope", None)
        anchor = _first(query, "anchor", None)
        method = _first(query, "method", None)
        resolution = _first(query, "resolution", "auto") or "auto"
        points = _int(query, "points", 300, 50, 2000)
        if metric in ("latency_ms", "loss_pct"):
            method = method or "icmp"
            anchor = anchor or _default_anchor(self.config, method)
        elif metric in ("down_bps", "up_bps"):
            anchor = anchor or "networkquality"
            method = method or "networkquality"
        elif metric == "rssi_dbm" and not anchor:
            interfaces = db.latest_interfaces(conn)
            active = next((row for row in interfaces if row["is_default"]), None)
            if active is None:
                active = next((row for row in interfaces if row["is_up"]), None)
            if active:
                anchor = active["ifname"]
        result = db.series_window(
            conn,
            metric,
            since,
            now,
            scope=scope,
            anchor=anchor,
            method=method,
            max_points=points,
            resolution=resolution,
            raw_cutoff_ms=now - self.config.retention.raw_days * DAY_MS,
            five_cutoff_ms=now - self.config.retention.five_minute_days * DAY_MS,
            hourly_cutoff_ms=now - self.config.retention.hourly_days * DAY_MS,
        )
        return {
            "metric": metric,
            "resolution": result["resolution"],
            "points": result["points"],
            "window": {"since": since, "until": now},
            "series": {"scope": scope, "anchor": anchor, "method": method},
        }

    def _send(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send(data, "application/json; charset=utf-8", status)

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("%s - %s", self.address_string(), fmt % args)


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _default_anchor(config: Config, method: str) -> str | None:
    for anchor in config.enabled_anchors():
        if method in anchor.health:
            return anchor.name
    return None


def _first(query: dict[str, list[str]], key: str, default: Any) -> Any:
    values = query.get(key)
    return values[0] if values else default


def _since(query: dict[str, list[str]], default: str) -> int:
    now = _now_ms()
    value = _first(query, "since", None) or default
    return parse_since(value, now, 0)


def _int(
    query: dict[str, list[str]], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = _first(query, key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def make_server(config: Config) -> ThreadingHTTPServer:
    handler = type(
        "CuisleHandler",
        (Handler,),
        {"db_path": config.db_path, "config": config},
    )
    server = ThreadingHTTPServer(
        (config.general.dashboard_host, config.general.dashboard_port), handler
    )
    server.daemon_threads = True
    return server


def serve_in_thread(config: Config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = make_server(config)
    thread = threading.Thread(target=server.serve_forever, name="cuisle-dashboard", daemon=True)
    thread.start()
    return server, thread


def serve(config: Config) -> None:
    server = make_server(config)
    host, port = server.server_address[:2]
    print(f"Cuisle dashboard: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def is_running(host: str, port: int, timeout: float = 0.5) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
