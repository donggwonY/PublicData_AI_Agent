#!/usr/bin/env python3
"""Supply a token to Git only during commit-push network operations."""

import os
import sys

if os.environ.get("MENTEE_GIT_AUTH") != "1" or not os.environ.get("GH_TOKEN"):
    raise SystemExit(2)

prompt = " ".join(sys.argv[1:]).lower()
print("x-access-token" if "username" in prompt else os.environ["GH_TOKEN"])
