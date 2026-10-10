from load_generator.controller.schemas import Profile


def stage_at(profile: Profile, elapsed: float) -> tuple[str, int]:
    if elapsed < profile.warmup_seconds:
        return "warmup", min(5, profile.users)
    elapsed -= profile.warmup_seconds
    if elapsed >= profile.duration_seconds:
        return "cooldown", 0
    if not profile.stages:
        return "running", profile.users
    for stage in profile.stages:
        if elapsed < stage.seconds:
            return "running", stage.users
        elapsed -= stage.seconds
    return "cooldown", 0
