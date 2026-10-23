"""Loads the fake company data from ../data."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str, data_dir: Path):
    return json.loads((data_dir / name).read_text())


@dataclass
class CompanyData:
    members: dict  # member_id -> member record (contains PRIVATE fields)
    vendors: dict  # vendor_id -> vendor record
    groups: dict   # group_id -> group record (member_id, title, recent history)
    house: dict    # the house booking identity + venue list + sharing rule

    def member_for_group(self, group_id: str) -> dict:
        return self.members[self.groups[group_id]["member_id"]]


def load_data(data_dir: Path = DATA_DIR) -> CompanyData:
    members = {m["member_id"]: m for m in _load("members.json", data_dir)}
    vendors = {v["vendor_id"]: v for v in _load("vendors.json", data_dir)}
    groups = {g["group_id"]: g for g in _load("groups.json", data_dir)}
    house = _load("house.json", data_dir)
    return CompanyData(members=members, vendors=vendors, groups=groups, house=house)
