from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from types import SimpleNamespace

from conftest import FakeRunner, fixture_text

from cuisle import probes
from cuisle.config import Anchor


class Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeTls(Ctx):
    def getpeercert(self):
        return {"notAfter": "Dec 31 23:59:59 2030 GMT"}


class FakeResponse(Ctx):
    status = 200

    def read(self, size=None):
        return b"x" * 100

    def geturl(self):
        return "https://example.test/"


def test_icmp_probe() -> None:
    result = probes.icmp_probe("1.1.1.1", FakeRunner({"ping": fixture_text("ping.txt")}))
    assert result.success
    assert result.loss_pct == 0.0
    assert result.latency_ms is not None


def test_dns_probe() -> None:
    result = probes.dns_probe("www.heanet.ie", FakeRunner({"dig": fixture_text("dig.txt")}))
    assert result.success
    assert result.status == "NOERROR"
    assert result.latency_ms == 32.0


def test_dns_fallback(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    result = probes.dns_probe("example.test", FakeRunner())
    assert result.success
    assert result.status == "system-resolver"


def test_tcp_probe(monkeypatch) -> None:
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Ctx())
    result = probes.tcp_probe("example.test", 443)
    assert result.success
    assert result.latency_ms is not None


def test_tls_probe(monkeypatch) -> None:
    context = SimpleNamespace(wrap_socket=lambda raw, server_hostname: FakeTls())
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Ctx())
    result = probes.tls_probe("example.test", 443)
    assert result.success
    assert "expires" in (result.detail or "")


def test_http_probe(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    result = probes.http_probe("https://example.test/")
    assert result.success
    assert result.status == "200"


def test_http_error(monkeypatch) -> None:
    def fail(request, timeout):
        raise urllib.error.HTTPError("https://example.test/", 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    result = probes.http_probe("https://example.test/")
    assert not result.success
    assert result.status == "404"


def test_run_anchor_health(monkeypatch) -> None:
    context = SimpleNamespace(wrap_socket=lambda raw, server_hostname: FakeTls())
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Ctx())
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    anchor = Anchor(
        name="all",
        scope="country",
        host="example.test",
        port=443,
        url="https://example.test/",
        health=("icmp", "dns", "tcp", "tls", "http"),
    )
    samples = probes.run_anchor_health(
        anchor,
        gateway="192.168.100.1",
        interface="en0",
        ts=1000,
        runner=FakeRunner({"ping": fixture_text("ping.txt"), "dig": fixture_text("dig.txt")}),
    )
    assert {s.method for s in samples} == {"icmp", "dns", "tcp", "tls", "http"}
    assert all(s.success for s in samples)
    assert all(s.interface == "en0" for s in samples)
