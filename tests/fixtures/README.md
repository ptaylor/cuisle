# Fixtures

Sanitised command output captured on macOS 15.7.9 on 2026-11-15 for the parser
tests. Local IPs, MAC addresses, hostnames and the DNS server were replaced;
remote addresses were replaced with documentation-style placeholders of the
same width. PIDs remain as observed.

Regeneration commands:

```sh
netstat -anv -p tcp | head -25 > netstat_tcp.txt
netstat -anv -p udp | head -20 > netstat_udp.txt
route -n get default > route_default.txt
networksetup -listallhardwareports > hardware_ports.txt
netstat -ib | head -25 > netstat_ib.txt
scutil --nwi > scutil_nwi.txt
ping -n -c 3 1.1.1.1 > ping.txt
dig +time=2 +tries=1 www.heanet.ie > dig.txt
pmset -g batt > pmset_batt.txt
networkQuality -c -M 15 -s | jq '{base_rtt, dl_bytes_transferred,
  dl_responsiveness, dl_throughput, end_date, interface_name, other,
  start_date, test_endpoint, ul_bytes_transferred, ul_responsiveness,
  ul_throughput}' > networkquality.json
```

`networkquality.json` is real output, trimmed to the keys Cuisle reads.

`speedtest.json` and `iperf3.json` are schema-only fixtures: neither tool is
installed on the capture machine (the `speedtest` on PATH is a broken Python
shim). They test the JSON parsers, not a live measurement.

Assisted-by: Claude Code (DeepSeek Flash, effort: high)
