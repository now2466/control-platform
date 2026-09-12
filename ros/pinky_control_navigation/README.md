# Pinky static-map navigation

`map_260905.pgm` is the occupancy raster generated from the collision boxes in
`backend/pinky_control_center/resources/worlds/map_260905.world`. The dashboard
and Nav2 use the same map frame (`map`), resolution (`0.005 m/cell`), and origin.

Run this package only after the hardware bringup and the control watchdog are
running:

```bash
ros2 launch pinky_control_navigation robot_nav2.launch.py use_sim_time:=false
```

The controller and recovery behavior output is remapped to
`/control/nav_velocity`; the watchdog remains the only publisher of `/cmd_vel`.
The launch intentionally does not start SLAM. Clicking `위치 재설정(AMCL)` sends
`/initialpose` after the robot has been manually lifted and placed elsewhere;
the static map is retained. Navigation lifecycle activation waits for AMCL to
publish `map -> base_footprint` and retries after a late initial pose; it is not
activated by a fixed startup timer.
