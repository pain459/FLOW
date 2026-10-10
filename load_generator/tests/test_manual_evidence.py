from types import SimpleNamespace
from load_generator.controller.lifecycle import atomic_json, read_json


def test_manual_session_publishes_real_productive_window_and_warmup(tmp_path):
    from load_generator.stack_ui import observe_session

    atomic_json(tmp_path / "clock.json", {"started_epoch": 100, "warmup_seconds": 10})
    stats = SimpleNamespace(
        phases={"measured": {"http": 120, "confirmed_commits": 30, "outcomes": {"success": 120}}}
    )
    first = observe_session(tmp_path, stats, users=5, epoch=105)
    assert first["phase"] == "warmup"
    assert read_json(tmp_path / "state.json")["status"] == "WARMUP"
    observe_session(tmp_path, stats, users=5, epoch=112)
    stats.phases["measured"]["http"] = 300
    stats.phases["measured"]["confirmed_commits"] = 90
    final = observe_session(tmp_path, stats, users=5, epoch=130)
    assert final["load"]["measured"]["http"] == 300
    assert final["active_users"] == 5
    assert read_json(tmp_path / "state.json")["status"] == "RUNNING"
    samples = read_json(tmp_path / "recent-observations.json")["samples"]
    assert samples[1]["load"]["measured"]["http"] == 120
    assert samples[-1]["load"]["measured"]["confirmed_commits"] == 90
