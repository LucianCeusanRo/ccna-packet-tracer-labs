"""Each lab folder has a complete set of files, and every .cfg parses as IOS."""
from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from ios_parse import ParsedConfig, iter_cfg_files, iter_lab_dirs, parse_file, parse_text  # noqa: E402

LABS = ("01-vlan-trunk", "02-inter-vlan", "03-ospf", "04-acl")


class TestRepoLayout(unittest.TestCase):
    def test_four_labs_present(self):
        names = [p.name for p in iter_lab_dirs(ROOT)]
        self.assertEqual(names, list(LABS))

    def test_each_lab_has_readme_topology_and_config(self):
        for lab in iter_lab_dirs(ROOT):
            with self.subTest(lab=lab.name):
                self.assertTrue((lab / "README.md").is_file(), "missing README.md")
                self.assertGreater((lab / "README.md").stat().st_size, 200)
                svg = lab / "topology.svg"
                self.assertTrue(svg.is_file(), "missing topology.svg")
                self.assertGreater(svg.stat().st_size, 100)
                cfgs = list(lab.glob("*.cfg"))
                self.assertTrue(cfgs, "no .cfg files")

    def test_topology_svg_is_xml(self):
        for lab in iter_lab_dirs(ROOT):
            with self.subTest(lab=lab.name):
                tree = ET.parse(lab / "topology.svg")
                tag = tree.getroot().tag.lower()
                self.assertTrue(tag.endswith("svg"), f"root tag is {tree.getroot().tag}")

    def test_screenshots_exist(self):
        for name in LABS:
            path = ROOT / "docs" / "screenshots" / f"{name}.png"
            with self.subTest(screenshot=name):
                self.assertTrue(path.is_file(), path)
                self.assertGreater(path.stat().st_size, 1000)


class TestParserRejectsBadConfigs(unittest.TestCase):
    def test_empty_file(self):
        cfg = parse_text("\n\n")
        self.assertFalse(cfg.ok)
        self.assertTrue(any("empty" in e for e in cfg.errors))

    def test_typo_is_rejected(self):
        cfg = parse_text("hostname SW1\nhostnam SW2\nend\n")
        self.assertFalse(cfg.ok)
        self.assertTrue(any("unrecognized" in e for e in cfg.errors))

    def test_bad_ip_is_rejected(self):
        text = (
            "hostname R1\n"
            "interface Loopback0\n"
            " ip address 999.1.1.1 255.255.255.255\n"
            "end\n"
        )
        cfg = parse_text(text)
        self.assertFalse(cfg.ok)
        self.assertTrue(any("invalid" in e.lower() or "999" in e for e in cfg.errors))

    def test_missing_end_is_rejected(self):
        cfg = parse_text("hostname SW1\nvlan 10\n name Staff\n")
        self.assertFalse(cfg.ok)
        self.assertTrue(any("end" in e for e in cfg.errors))

    def test_vlan_out_of_range(self):
        cfg = parse_text("hostname SW1\nvlan 5000\n name X\nend\n")
        self.assertFalse(cfg.ok)

    def test_parser_accepts_a_minimal_switch(self):
        text = (
            "! comment\n"
            "hostname SW1\n"
            "no ip domain-lookup\n"
            "vlan 10\n"
            " name Staff\n"
            "interface FastEthernet0/1\n"
            " switchport mode access\n"
            " switchport access vlan 10\n"
            " no shutdown\n"
            "end\n"
        )
        cfg = parse_text(text)
        self.assertEqual(cfg.errors, [])
        self.assertEqual(cfg.hostname, "SW1")
        self.assertEqual(cfg.vlans[10], "Staff")
        self.assertEqual(cfg.interfaces["FastEthernet0/1"].access_vlan, 10)


class TestAllCheckedInConfigsParse(unittest.TestCase):
    def test_every_cfg_parses_cleanly(self):
        files = iter_cfg_files(ROOT)
        self.assertGreaterEqual(len(files), 11)
        for path in files:
            with self.subTest(cfg=str(path.relative_to(ROOT))):
                parsed = parse_file(path)
                self.assertEqual(parsed.errors, [], f"{path.name}: {parsed.errors}")


class TestLab01VlanTrunk(unittest.TestCase):
    def setUp(self):
        self.sw1 = parse_file(ROOT / "01-vlan-trunk" / "SW1.cfg")
        self.sw2 = parse_file(ROOT / "01-vlan-trunk" / "SW2.cfg")

    def test_hostnames(self):
        self.assertEqual(self.sw1.hostname, "SW1")
        self.assertEqual(self.sw2.hostname, "SW2")

    def test_shared_vlans(self):
        for cfg in (self.sw1, self.sw2):
            self.assertEqual(cfg.vlans.get(10), "Staff")
            self.assertEqual(cfg.vlans.get(20), "Guests")

    def test_access_ports_and_trunk(self):
        for cfg in (self.sw1, self.sw2):
            fa1 = cfg.interfaces["FastEthernet0/1"]
            fa2 = cfg.interfaces["FastEthernet0/2"]
            gi = cfg.interfaces["GigabitEthernet0/1"]
            self.assertEqual(fa1.mode, "access")
            self.assertEqual(fa1.access_vlan, 10)
            self.assertTrue(fa1.portfast)
            self.assertTrue(fa1.nonegotiate)
            self.assertEqual(fa2.mode, "access")
            self.assertEqual(fa2.access_vlan, 20)
            self.assertEqual(gi.mode, "trunk")
            self.assertEqual(gi.allowed_vlans, [10, 20])
            self.assertTrue(gi.nonegotiate)
            self.assertTrue(gi.no_shutdown)


class TestLab02InterVlan(unittest.TestCase):
    def setUp(self):
        self.r1 = parse_file(ROOT / "02-inter-vlan" / "R1.cfg")
        self.sw1 = parse_file(ROOT / "02-inter-vlan" / "SW1.cfg")

    def test_router_on_a_stick(self):
        phys = self.r1.interfaces["GigabitEthernet0/0"]
        s10 = self.r1.interfaces["GigabitEthernet0/0.10"]
        s20 = self.r1.interfaces["GigabitEthernet0/0.20"]
        self.assertTrue(phys.no_ip)
        self.assertTrue(phys.no_shutdown)
        self.assertIsNone(phys.ip)
        self.assertEqual(s10.encapsulation, 10)
        self.assertEqual(s10.ip, "192.168.10.1/24")
        self.assertEqual(s20.encapsulation, 20)
        self.assertEqual(s20.ip, "192.168.20.1/24")

    def test_switch_trunk(self):
        self.assertEqual(self.sw1.hostname, "SW1")
        gi = self.sw1.interfaces["GigabitEthernet0/1"]
        self.assertEqual(gi.mode, "trunk")
        self.assertEqual(gi.allowed_vlans, [10, 20])


class TestLab03Ospf(unittest.TestCase):
    def setUp(self):
        self.routers = {
            name: parse_file(ROOT / "03-ospf" / f"{name}.cfg")
            for name in ("R1", "R2", "R3")
        }

    def test_loopbacks_and_router_ids(self):
        expected = {"R1": "1.1.1.1", "R2": "2.2.2.2", "R3": "3.3.3.3"}
        for name, rid in expected.items():
            cfg = self.routers[name]
            self.assertEqual(cfg.hostname, name)
            self.assertEqual(cfg.interfaces["Loopback0"].ip, f"{rid}/32")
            self.assertEqual(cfg.ospf["process"], 1)
            self.assertEqual(cfg.ospf["router_id"], rid)
            areas = {n["area"] for n in cfg.ospf["networks"]}
            self.assertEqual(areas, {0})
            self.assertEqual(len(cfg.ospf["networks"]), 3)

    def test_point_to_point_links_are_consistent(self):
        # Same /30 on both ends, .1 and .2 as documented in the lab README.
        r1, r2, r3 = self.routers["R1"], self.routers["R2"], self.routers["R3"]
        self.assertEqual(r1.interfaces["GigabitEthernet0/0"].ip, "10.0.12.1/30")
        self.assertEqual(r2.interfaces["GigabitEthernet0/0"].ip, "10.0.12.2/30")
        self.assertEqual(r1.interfaces["GigabitEthernet0/1"].ip, "10.0.13.1/30")
        self.assertEqual(r3.interfaces["GigabitEthernet0/0"].ip, "10.0.13.2/30")
        self.assertEqual(r2.interfaces["GigabitEthernet0/1"].ip, "10.0.23.1/30")
        self.assertEqual(r3.interfaces["GigabitEthernet0/1"].ip, "10.0.23.2/30")


class TestLab04Acl(unittest.TestCase):
    def setUp(self):
        self.base = parse_file(ROOT / "04-acl" / "R1.cfg")
        self.std = parse_file(ROOT / "04-acl" / "R1-standard-acl.cfg")
        self.ext = parse_file(ROOT / "04-acl" / "R1-extended-acl.cfg")
        self.sw1 = parse_file(ROOT / "04-acl" / "SW1.cfg")

    def test_base_router_is_router_on_a_stick(self):
        self.assertEqual(self.base.hostname, "R1")
        self.assertTrue(self.base.interfaces["GigabitEthernet0/0"].no_ip)
        self.assertEqual(self.base.interfaces["GigabitEthernet0/0.10"].ip, "192.168.10.1/24")
        self.assertEqual(self.base.interfaces["GigabitEthernet0/0.20"].ip, "192.168.20.1/24")

    def test_standard_acl_close_to_destination(self):
        # Snippet files have no hostname — that is expected.
        self.assertIsNone(self.std.hostname)
        self.assertIn(10, self.std.standard_acls)
        entries = self.std.standard_acls[10]
        self.assertTrue(entries[0].startswith("deny "))
        self.assertIn("192.168.20.0", entries[0])
        self.assertEqual(entries[-1], "permit any")
        iface = self.std.interfaces["GigabitEthernet0/0.10"]
        self.assertEqual(iface.access_group, ("10", "out"))

    def test_extended_acl_close_to_source(self):
        self.assertIn("GUEST_TO_STAFF", self.ext.extended_acls)
        aces = "\n".join(self.ext.extended_acls["GUEST_TO_STAFF"])
        self.assertIn("permit tcp", aces)
        self.assertIn("192.168.10.10", aces)
        self.assertIn("eq 80", aces)
        self.assertIn("permit ip any any", aces)
        iface = self.ext.interfaces["GigabitEthernet0/0.20"]
        self.assertEqual(iface.access_group, ("GUEST_TO_STAFF", "in"))

    def test_switch_has_staff_server_and_guest(self):
        self.assertEqual(self.sw1.interfaces["FastEthernet0/1"].access_vlan, 10)
        self.assertEqual(self.sw1.interfaces["FastEthernet0/2"].access_vlan, 20)
        self.assertEqual(self.sw1.interfaces["FastEthernet0/3"].access_vlan, 10)


if __name__ == "__main__":
    unittest.main()
