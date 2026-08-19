#!/usr/bin/env python3
"""
create_admin.py — Seed an initial admin user from environment variables.

Usage:
    JWT_ADMIN_USERNAME=admin JWT_ADMIN_PASSWORD=secure123 python create_admin.py
"""

import os
import sys

from auth import _create_user, _hash_password, _init_users_table


def main() -> None:
    username = os.environ.get("JWT_ADMIN_USERNAME", "admin")
    password = os.environ.get("JWT_ADMIN_PASSWORD")

    if not password:
        print("ERROR: JWT_ADMIN_PASSWORD environment variable not set.")
        sys.exit(1)

    _init_users_table()

    hashed = _hash_password(password)
    ok = _create_user(username, hashed, is_admin=True)

    if ok:
        print(f"Admin user '{username}' created successfully.")
    else:
        print(f"Admin user '{username}' already exists (skipping).")


if __name__ == "__main__":
    main()
