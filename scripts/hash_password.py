#!/usr/bin/env python3
"""Usage: python scripts/hash_password.py 'your-password'
Prints the bcrypt hash to put into ADMIN_PASSWORD_HASH in .env.

Also prints a Compose-escaped version: Docker Compose interpolates $ inside
.env values too, so a bcrypt hash like $2b$12$... gets corrupted unless
every $ is doubled to $$ in the .env file. Use the second line below."""

import sys

import bcrypt

if len(sys.argv) != 2:
    print("Usage: python hash_password.py 'your-password'")
    sys.exit(1)

hashed = bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode()
escaped = hashed.replace("$", "$$")

print(f"Hash (for direct use, e.g. outside Docker Compose): {hashed}")
print(f"Paste into .env (escaped for Docker Compose):        ADMIN_PASSWORD_HASH={escaped}")
