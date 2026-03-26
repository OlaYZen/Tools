# Zabbix Templates

Custom Zabbix templates for network infrastructure monitoring.

---

## `template_app_opnsense_snmp.yaml` — OPNsense by SNMP

**Zabbix version:** 7.4  
**Group:** Templates/Applications

A modified version of the [official Zabbix OPNsense template](https://www.zabbix.com/integrations/opnsense) (originally targeting Zabbix 7.0). Monitors an OPNsense firewall via SNMPv2 using the `bsnmpd` daemon on FreeBSD.

### Changes from the official template

- **Added:** firewall rules count, pf state table (current/limit/% used), source tracking table (current/limit/% used), SNMP agent availability item
- **Added:** built-in dashboard with packet filter reason codes and per-interface traffic graphs
- **Modified:** CPU utilization item reworked to use a JS preprocessor that walks all cores and averages them, rather than the official single-OID approach
- **Changed:** DNS service monitor now looks for `dnsmasq` instead of `unbound`; DHCP service monitor now looks for `dnsmasq` instead of `dhcpd` — reflects a setup where dnsmasq handles both

### What it monitors

- **Packet filter (pf):** running status, per-interface IPv4/IPv6 traffic (bytes/packets, passed/blocked), pf reason code counters (match, bad-offset, fragment, short, normalize, memory-drop)
- **Firewall tables:** state table and source tracking table utilization (current entries, limits, % used)
- **Firewall rules:** total labeled rule count
- **Services:** DHCP server, DNS server, web UI (lighttpd)
- **Network interfaces:** LLD-discovered interfaces via IF-MIB with traffic, errors, discards, and operational status
- **SNMP availability:** internal Zabbix SNMP reachability item

### Triggers

| Trigger | Severity |
|---|---|
| Packet filter not running | High |
| DHCP / DNS / web server not running | Average |
| State table usage > 90% | Warning |
| Source tracking table usage > 90% | Warning |
| No SNMP data collection | Warning |
| Interface link down | Average |
| Interface high in/out error rate | Warning |
| Interface high in/out bandwidth usage | Warning |

**MIBs used:** `BEGEMOT-PF-MIB`, `HOST-RESOURCES-MIB`, `IF-MIB`, `SNMPv2-MIB`

---

## `template_net_zyxel_gs1900_48_snmp.yaml` — ZyXEL GS1900-48 SNMP

**Zabbix version:** 7.4  
**Group:** Templates/Network devices

A fully custom template built from scratch for the ZyXEL GS1900-48 (48x GbE RJ45 + 2x SFP, fanless smart managed switch). Uses SNMPv2c with a mix of standard MIBs and the ZyXEL enterprise MIB (`1.3.6.1.4.1.890.1.15`).

> **Note:** Some items are marked `[MAY NOT RESPOND]` — these depend on firmware version. Verify with `snmpget` before relying on them.

### What it monitors

- **Availability:** ICMP ping, packet loss, response time
- **System:** hostname, description, location, uptime, firmware version
- **Performance:** CPU utilization (instantaneous + 1m/5m averages), memory used/available
- **Interfaces (LLD):** per-port traffic (bps), bandwidth utilization (%), errors, discards, unicast/multicast packet rates, admin/oper status, link-down detection
- **Spanning Tree (STP):** root bridge ID, topology change counter, per-port STP state
- **LLDP:** neighbor discovery (chassis ID, port, system name/description) via LLD

### Triggers

| Trigger | Severity |
|---|---|
| Switch unreachable (5 consecutive ICMP failures) | Disaster |
| STP root bridge changed | Warning |
| STP topology change detected | Warning |
| Switch rebooted (uptime < 10 min) | Warning |
| High ICMP packet loss | Warning |
| High CPU utilization | Warning |
| Low available memory | Warning |
| Port link down (admin up) | Warning |
| Port high error rate | Warning |
| Port high bandwidth utilization | Warning |
| Port STP blocking | Info |
| Firmware version changed | Info |

### Macros

| Macro | Default | Description |
|---|---|---|
| `{$SNMP_COMMUNITY}` | `public` | SNMPv2c community string |
| `{$IF_UTIL_MAX}` | `90` | Bandwidth utilization warning threshold (%) |
| `{$IF_ERRORS_WARN}` | `2` | Interface errors/s warning threshold |
| `{$PING_LOSS_WARN}` | `20` | ICMP packet loss warning threshold (%) |
| `{$CPU_UTIL_MAX}` | `90` | CPU utilization warning threshold (%) |
| `{$MEM_AVAIL_MIN}` | `10` | Minimum available memory threshold (%) |
| `{$IF_LINK_DOWN_DISABLE}` | *(empty)* | Set to suppress link-down triggers on specific interfaces |

**MIBs used:** `IF-MIB`, `BRIDGE-MIB`, `LLDP-MIB`, ZyXEL enterprise MIB (`1.3.6.1.4.1.890.1.15`), `SNMPv2-MIB`
