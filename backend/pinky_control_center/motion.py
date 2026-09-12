from __future__ import annotations


# Pinky Pro encoder odometry quantizes a physically stopped robot to roughly
# +/-0.0013 m/s and +/-0.026 rad/s. These limits reject actual motion while
# allowing that measured zero-speed noise.
STILL_LINEAR_MPS = 0.01
STILL_ANGULAR_RPS = 0.03


def within_still_tolerance(linear_mps: float | None, angular_rps: float | None) -> bool:
    return (
        linear_mps is not None
        and abs(linear_mps) <= STILL_LINEAR_MPS
        and angular_rps is not None
        and abs(angular_rps) <= STILL_ANGULAR_RPS
    )
