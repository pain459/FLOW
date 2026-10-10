"""Bounded manual Locust controls; qualified profiles remain headless."""

import math
import os
from flask import request
from load_generator.controller.schemas import validate_target


def quit_ui(environment):
    if os.getenv("LOAD_STACK_UI") == "true":
        environment.runner.stop()
        return
    environment.runner.quit()
    environment.web_ui.stop()


def supervise_safely(environment, supervise):
    try:
        supervise()
    except Exception:
        quit_ui(environment)


def install_guard(environment, profile):
    environment.web_ui.app.config["MAX_CONTENT_LENGTH"] = 16384

    @environment.web_ui.app.before_request
    def safe_swarm():
        if request.path == "/user" and request.method == "POST":
            return {
                "success": False,
                "message": "User definitions are fixed by PulsePay",
            }, 403
        if request.path != "/swarm" or request.method != "POST":
            return None
        values = request.form
        try:
            if set(values) - {
                "host",
                "user_count",
                "spawn_rate",
                "run_time",
                "shape_class",
                "user_classes",
                "profile",
            }:
                raise ValueError("Unsupported PulsePay load option")
            validate_target(values.get("host") or "http://api:8080")
            users = int(values.get("user_count", "0"))
            rate = float(values.get("spawn_rate", "0"))
            if not 1 <= users <= profile.safety.max_concurrent_users:
                raise ValueError("User count exceeds the selected profile safety limit")
            if not math.isfinite(rate) or not 0 < rate <= 50:
                raise ValueError("Spawn rate must be positive and at most 50 users/sec")
            if values.get("run_time") or values.get("shape_class") not in {
                None,
                "",
                "Default",
            }:
                raise ValueError(
                    "Session duration and workload mix come from the selected profile"
                )
            if any(name != "PulsePayUser" for name in values.getlist("user_classes")):
                raise ValueError("Only the PulsePay user class is permitted")
        except (TypeError, ValueError) as exc:
            return {"success": False, "message": str(exc)}, 400
        return None
