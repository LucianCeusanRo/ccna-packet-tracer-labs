#!/usr/bin/env python3
"""Parse and validate Cisco IOS-style .cfg files used in these Packet Tracer labs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path

IFACE_NAME = (
    r"(?:FastEthernet|GigabitEthernet|Ethernet|Serial|Loopback|Vlan|Port-channel)"
    r"\d+(?:/\d+)*(?:\.\d+)?"
)

COMMAND_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"hostname\s+\S+",
        r"no\s+ip\s+domain-lookup",
        r"no\s+ip\s+address",
        r"no\s+shutdown",
        r"end",
        r"vlan\s+\d+",
        r"name\s+.+",
        rf"interface\s+{IFACE_NAME}",
        r"description\s+.+",
        r"switchport\s+mode\s+(?:access|trunk)",
        r"switchport\s+nonegotiate",
        r"switchport\s+access\s+vlan\s+\d+",
        r"switchport\s+trunk\s+allowed\s+vlan\s+[\d,\-]+",
        r"switchport\s+trunk\s+encapsulation\s+dot1q",
        r"spanning-tree\s+portfast(?:\s+trunk)?",
        r"encapsulation\s+dot1[qQ]\s+\d+",
        r"ip\s+address\s+\d+\.\d+\.\d+\.\d+\s+\d+\.\d+\.\d+\.\d+",
        r"ip\s+access-group\s+\S+\s+(?:in|out)",
        r"access-list\s+\d+\s+(?:permit|deny)\s+.+",
        r"ip\s+access-list\s+extended\s+\S+",
        r"(?:permit|deny)\s+(?:ip|tcp|udp|icmp)\s+.+",
        r"router\s+ospf\s+\d+",
        r"router-id\s+\d+\.\d+\.\d+\.\d+",
        r"network\s+\d+\.\d+\.\d+\.\d+\s+\d+\.\d+\.\d+\.\d+\s+area\s+\d+",
    )
]

BLOCK_OPEN = re.compile(
    rf"^(?:interface\s+{IFACE_NAME}|vlan\s+\d+|router\s+ospf\s+\d+|ip\s+access-list\s+extended\s+\S+)$",
    re.I,
)
HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)$", re.I)
VLAN_RE = re.compile(r"^vlan\s+(\d+)$", re.I)
NAME_RE = re.compile(r"^name\s+(.+)$", re.I)
IFACE_RE = re.compile(rf"^interface\s+({IFACE_NAME})$", re.I)
DESC_RE = re.compile(r"^description\s+(.+)$", re.I)
MODE_RE = re.compile(r"^switchport\s+mode\s+(access|trunk)$", re.I)
ACCESS_VLAN_RE = re.compile(r"^switchport\s+access\s+vlan\s+(\d+)$", re.I)
ALLOWED_VLAN_RE = re.compile(r"^switchport\s+trunk\s+allowed\s+vlan\s+([\d,\-]+)$", re.I)
ENCAP_RE = re.compile(r"^encapsulation\s+dot1[qQ]\s+(\d+)$", re.I)
IP_ADDR_RE = re.compile(
    r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)$", re.I
)
ACL_GROUP_RE = re.compile(r"^ip\s+access-group\s+(\S+)\s+(in|out)$", re.I)
STD_ACL_RE = re.compile(r"^access-list\s+(\d+)\s+(permit|deny)\s+(.+)$", re.I)
EXT_ACL_RE = re.compile(r"^ip\s+access-list\s+extended\s+(\S+)$", re.I)
ACE_RE = re.compile(r"^(permit|deny)\s+(?:ip|tcp|udp|icmp)\s+(.+)$", re.I)
OSPF_RE = re.compile(r"^router\s+ospf\s+(\d+)$", re.I)
RID_RE = re.compile(r"^router-id\s+(\d+\.\d+\.\d+\.\d+)$", re.I)
NET_RE = re.compile(
    r"^network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+area\s+(\d+)$", re.I
)
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _expand_vlan_list(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if start > end:
                raise ValueError(f"VLAN range {part} is inverted")
            out.extend(range(start, end + 1))
        else:
            out.append(int(part))
    return out


def _check_vlan(vid: int) -> str | None:
    if not 1 <= vid <= 4094:
        return f"VLAN id {vid} is outside 1–4094"
    return None


def _check_ipv4_tokens(text: str) -> list[str]:
    errors = []
    for token in IPV4_RE.findall(text):
        if token in {"0.0.0.0", "255.255.255.255"}:
            continue
        try:
            IPv4Address(token)
        except Exception:
            errors.append(f"invalid IPv4 address {token}")
    return errors


@dataclass
class Iface:
    name: str
    description: str | None = None
    commands: list[str] = field(default_factory=list)
    mode: str | None = None
    access_vlan: int | None = None
    allowed_vlans: list[int] | None = None
    ip: str | None = None
    no_ip: bool = False
    no_shutdown: bool = False
    encapsulation: int | None = None
    nonegotiate: bool = False
    portfast: bool = False
    access_group: tuple[str, str] | None = None


@dataclass
class ParsedConfig:
    path: Path
    hostname: str | None = None
    vlans: dict[int, str] = field(default_factory=dict)
    interfaces: dict[str, Iface] = field(default_factory=dict)
    ospf: dict | None = None
    standard_acls: dict[int, list[str]] = field(default_factory=dict)
    extended_acls: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_text(text: str, path: Path | None = None) -> ParsedConfig:
    cfg = ParsedConfig(path=path or Path("<memory>"))
    if not text.strip():
        cfg.errors.append("file is empty")
        return cfg

    current_vlan: int | None = None
    current_iface: Iface | None = None
    current_ospf: dict | None = None
    current_ext: str | None = None
    last_code: str | None = None
    hostname_count = 0

    def close_blocks() -> None:
        nonlocal current_vlan, current_iface, current_ospf, current_ext
        current_vlan = None
        current_iface = None
        current_ospf = None
        current_ext = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        # IOS does not use tabs in these labs; flag them so a paste error is visible.
        if "\t" in raw:
            cfg.errors.append(f"line {lineno}: tab character (use spaces)")
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("!"):
            continue
        if line != line.rstrip():
            pass  # already stripped
        cmd = line.strip()
        if not any(p.fullmatch(cmd) for p in COMMAND_PATTERNS):
            cfg.errors.append(f"line {lineno}: unrecognized IOS command: {cmd}")
            continue

        if BLOCK_OPEN.fullmatch(cmd) or HOSTNAME_RE.fullmatch(cmd) or STD_ACL_RE.fullmatch(cmd) or cmd.lower() == "end":
            # Standard ACLs and hostname are top-level; close the previous block first
            # unless we are opening a new block of the same kind after close.
            if not ACE_RE.fullmatch(cmd):
                close_blocks()

        if m := HOSTNAME_RE.fullmatch(cmd):
            hostname_count += 1
            cfg.hostname = m.group(1)
            last_code = cmd
            continue

        if cmd.lower() == "end":
            last_code = cmd
            continue

        if m := VLAN_RE.fullmatch(cmd):
            vid = int(m.group(1))
            if err := _check_vlan(vid):
                cfg.errors.append(f"line {lineno}: {err}")
            cfg.vlans.setdefault(vid, "")
            current_vlan = vid
            last_code = cmd
            continue

        if m := NAME_RE.fullmatch(cmd):
            if current_vlan is None:
                cfg.errors.append(f"line {lineno}: 'name' outside a VLAN block")
            else:
                cfg.vlans[current_vlan] = m.group(1).strip()
            last_code = cmd
            continue

        if m := IFACE_RE.fullmatch(cmd):
            iface = Iface(name=m.group(1))
            if iface.name in cfg.interfaces:
                cfg.errors.append(f"line {lineno}: duplicate interface {iface.name}")
            cfg.interfaces[iface.name] = iface
            current_iface = iface
            last_code = cmd
            continue

        if m := OSPF_RE.fullmatch(cmd):
            current_ospf = {"process": int(m.group(1)), "router_id": None, "networks": []}
            if cfg.ospf is not None:
                cfg.errors.append(f"line {lineno}: more than one OSPF process (labs use a single process)")
            cfg.ospf = current_ospf
            last_code = cmd
            continue

        if m := EXT_ACL_RE.fullmatch(cmd):
            current_ext = m.group(1)
            cfg.extended_acls.setdefault(current_ext, [])
            last_code = cmd
            continue

        if m := STD_ACL_RE.fullmatch(cmd):
            num = int(m.group(1))
            if not 1 <= num <= 99:
                cfg.errors.append(f"line {lineno}: standard ACL {num} is outside 1–99")
            cfg.standard_acls.setdefault(num, []).append(f"{m.group(2).lower()} {m.group(3).strip()}")
            cfg.errors.extend(f"line {lineno}: {e}" for e in _check_ipv4_tokens(m.group(3)))
            last_code = cmd
            continue

        # Subcommands
        if m := DESC_RE.fullmatch(cmd):
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: 'description' outside an interface")
            else:
                current_iface.description = m.group(1)
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := MODE_RE.fullmatch(cmd):
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: switchport mode outside an interface")
            else:
                current_iface.mode = m.group(1).lower()
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() == "switchport nonegotiate":
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: switchport nonegotiate outside an interface")
            else:
                current_iface.nonegotiate = True
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := ACCESS_VLAN_RE.fullmatch(cmd):
            vid = int(m.group(1))
            if err := _check_vlan(vid):
                cfg.errors.append(f"line {lineno}: {err}")
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: access vlan outside an interface")
            else:
                current_iface.access_vlan = vid
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := ALLOWED_VLAN_RE.fullmatch(cmd):
            try:
                vlans = _expand_vlan_list(m.group(1))
            except ValueError as e:
                cfg.errors.append(f"line {lineno}: {e}")
                vlans = []
            for vid in vlans:
                if err := _check_vlan(vid):
                    cfg.errors.append(f"line {lineno}: {err}")
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: trunk allowed vlan outside an interface")
            else:
                current_iface.allowed_vlans = vlans
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() == "switchport trunk encapsulation dot1q":
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: trunk encapsulation outside an interface")
            else:
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() in {"spanning-tree portfast", "spanning-tree portfast trunk"}:
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: portfast outside an interface")
            else:
                current_iface.portfast = True
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := ENCAP_RE.fullmatch(cmd):
            vid = int(m.group(1))
            if err := _check_vlan(vid):
                cfg.errors.append(f"line {lineno}: {err}")
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: encapsulation outside an interface")
            else:
                current_iface.encapsulation = vid
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := IP_ADDR_RE.fullmatch(cmd):
            ip, mask = m.group(1), m.group(2)
            try:
                iface = IPv4Interface(f"{ip}/{mask}")
                cidr = str(iface)
            except Exception as e:
                cfg.errors.append(f"line {lineno}: invalid ip address {ip} {mask}: {e}")
                cidr = f"{ip}/{mask}"
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: ip address outside an interface")
            else:
                current_iface.ip = cidr
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() == "no ip address":
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: 'no ip address' outside an interface")
            else:
                current_iface.no_ip = True
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() == "no shutdown":
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: 'no shutdown' outside an interface")
            else:
                current_iface.no_shutdown = True
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if cmd.lower() == "no ip domain-lookup":
            last_code = cmd
            continue

        if m := ACL_GROUP_RE.fullmatch(cmd):
            if current_iface is None:
                cfg.errors.append(f"line {lineno}: ip access-group outside an interface")
            else:
                current_iface.access_group = (m.group(1), m.group(2).lower())
                current_iface.commands.append(cmd)
            last_code = cmd
            continue

        if m := RID_RE.fullmatch(cmd):
            try:
                IPv4Address(m.group(1))
            except Exception:
                cfg.errors.append(f"line {lineno}: invalid router-id {m.group(1)}")
            if current_ospf is None:
                cfg.errors.append(f"line {lineno}: router-id outside 'router ospf'")
            else:
                current_ospf["router_id"] = m.group(1)
            last_code = cmd
            continue

        if m := NET_RE.fullmatch(cmd):
            net, wild, area = m.group(1), m.group(2), int(m.group(3))
            try:
                IPv4Address(net)
                IPv4Address(wild)
            except Exception:
                cfg.errors.append(f"line {lineno}: invalid OSPF network {net} {wild}")
            if current_ospf is None:
                cfg.errors.append(f"line {lineno}: network statement outside 'router ospf'")
            else:
                current_ospf["networks"].append({"network": net, "wildcard": wild, "area": area})
            last_code = cmd
            continue

        if m := ACE_RE.fullmatch(cmd):
            if current_ext is None:
                cfg.errors.append(f"line {lineno}: ACE outside an extended ACL")
            else:
                cfg.extended_acls[current_ext].append(cmd)
            cfg.errors.extend(f"line {lineno}: {e}" for e in _check_ipv4_tokens(cmd))
            last_code = cmd
            continue

        # Recognized by the pattern list but not handled above — still counts as parsed.
        last_code = cmd

    if hostname_count > 1:
        cfg.errors.append("more than one hostname command")
    if last_code is None:
        cfg.errors.append("no IOS commands found")
    elif last_code.lower() != "end":
        cfg.errors.append("config does not end with 'end'")

    return cfg


def parse_file(path: Path) -> ParsedConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        cfg = ParsedConfig(path=path)
        cfg.errors.append(f"not valid UTF-8: {e}")
        return cfg
    return parse_text(text, path)


def iter_lab_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and re.match(r"^\d{2}-", p.name))


def iter_cfg_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for lab in iter_lab_dirs(root):
        files.extend(sorted(lab.glob("*.cfg")))
    return files
