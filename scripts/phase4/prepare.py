"""Executed inside Docker only. Extends existing local env without exposing secrets."""

import secrets
from pathlib import Path

p = Path("/workspace/.env")
text = p.read_text()
for name in (
    "DECISION_PASSWORD",
    "DECISION_MIGRATOR_PASSWORD",
    "EVALUATOR_PASSWORD",
    "DECISION_API_TOKEN",
):
    if name + "=replace_with_generated_secret" in text:
        text = text.replace(
            name + "=replace_with_generated_secret", name + "=" + secrets.token_hex(24)
        )
    elif not any(line.startswith(name + "=") for line in text.splitlines()):
        text += f"\n{name}={secrets.token_hex(24)}"
p.write_text(text.rstrip() + "\n")
p.chmod(0o600)
print("Generated/retained decision credentials; no secrets printed")
