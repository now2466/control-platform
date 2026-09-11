#!/usr/bin/env python3
"""Validate deployment invariants before starting the control center."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse


REQUIRED = (
    "CONTROL_PLATFORM_MODE",
    "CONTROL_PLATFORM_HOST",
    "CONTROL_PLATFORM_PORT",
    "CONTROL_PLATFORM_ALLOWED_ORIGIN",
    "CONTROL_PLATFORM_WORKERS",
    "ROS_DOMAIN_ID_ROBOT_1",
    "ROS_DOMAIN_ID_ROBOT_2",
    "ROSBRIDGE_URL_ROBOT_1",
    "ROSBRIDGE_URL_ROBOT_2",
)


def load_env(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    if not path.exists():
        raise ValueError(f"env file does not exist: {path}")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def validate(values: dict[str, str]) -> list[str]:
    errors = [f"missing {key}" for key in REQUIRED if not values.get(key)]
    if errors:
        return errors
    if values["CONTROL_PLATFORM_MODE"] not in {"mock", "ros"}:
        errors.append("CONTROL_PLATFORM_MODE must be mock or ros")
    if values["CONTROL_PLATFORM_WORKERS"] != "1":
        errors.append("CONTROL_PLATFORM_WORKERS must be 1")
    if values["ROS_DOMAIN_ID_ROBOT_1"] != "12":
        errors.append("ROS_DOMAIN_ID_ROBOT_1 must be 12")
    if values["ROS_DOMAIN_ID_ROBOT_2"] != "13":
        errors.append("ROS_DOMAIN_ID_ROBOT_2 must be 13")
    if values["ROSBRIDGE_URL_ROBOT_1"] == values["ROSBRIDGE_URL_ROBOT_2"]:
        errors.append("robot_1 and robot_2 rosbridge URLs must be different")
    for robot_id in ("ROBOT_1", "ROBOT_2"):
        parsed = urlparse(values[f"ROSBRIDGE_URL_{robot_id}"])
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            errors.append(f"ROSBRIDGE_URL_{robot_id} must be a ws:// or wss:// URL")
    origin = urlparse(values["CONTROL_PLATFORM_ALLOWED_ORIGIN"])
    if origin.scheme not in {"http", "https"} or not origin.netloc:
        errors.append("CONTROL_PLATFORM_ALLOWED_ORIGIN must be an absolute HTTP(S) origin")
    secure = values.get("CONTROL_PLATFORM_SECURE_COOKIES", "0")
    if secure not in {"0", "1"}:
        errors.append("CONTROL_PLATFORM_SECURE_COOKIES must be 0 or 1")
    if secure == "1" and origin.scheme != "https":
        errors.append("Secure cookies require an HTTPS allowed origin")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_env(args.env_file))
    except ValueError as error:
        print(f"INVALID: {error}")
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 2
    print(f"OK: {args.env_file} (worker=1, robot_1 domain=12, robot_2 domain=13)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
