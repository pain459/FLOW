from pathlib import Path
import pytest


def test_all_committed_profiles_validate_and_digest_is_stable():
    from load_generator.controller.schemas import load_profile

    profiles = Path(__file__).parents[1] / "profiles"
    for path in profiles.glob("*.yaml"):
        first, second = load_profile(path.stem), load_profile(path.stem)
        assert first.digest() == second.digest()
        assert first.duration_seconds <= first.safety.max_duration_seconds
    assert load_profile("read_heavy").mix["transfer_write"] < 0.5
    assert load_profile("write_heavy").mix["transfer_write"] > 0.5


def test_duration_overrides_preserve_all_declared_stages():
    from load_generator.controller.schemas import load_profile

    profile = load_profile("burst", {"duration_seconds": 120, "users": 60})
    assert sum(stage.seconds for stage in profile.stages) == 120
    assert [stage.users for stage in profile.stages] == [20, 60, 20]
    with pytest.raises(ValueError):
        load_profile("burst", {"duration_seconds": 2})


def test_profile_path_cannot_escape_committed_catalog():
    from load_generator.controller.schemas import load_profile

    with pytest.raises(ValueError):
        load_profile("../../secret")
