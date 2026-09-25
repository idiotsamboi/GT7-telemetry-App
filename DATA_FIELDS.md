# Data field reference

All offsets are bytes, little endian, and variant denotes first availability. Source is the pinned upstream header. Values are telemetry unless explicitly derived. Layout confidence is source-verified; behavior/units are not hardware-verified here. Floats must be finite; implausible speed/RPM/fuel normalize to null with a quality flag and preserved invalid wire bytes. Negative timing/pre-race sentinels normalize to null. Arrays preserve FL, FR, RL, RR order where applicable.

| Field | Offset | Type | Units / caution | Variant |
|---|---:|---|---|---|
| position | 0x004 | `3f` | m | A |
| velocity | 0x010 | `3f` | m/s | A |
| rotation | 0x01C | `3f` | raw | A |
| north | 0x028 | `f` | raw | A |
| angular_velocity | 0x02C | `3f` | rad/s | A |
| body_height | 0x038 | `f` | m | A |
| rpm | 0x03C | `f` | rpm | A |
| fuel | 0x044 | `f` | L | A |
| fuel_capacity | 0x048 | `f` | L | A |
| speed | 0x04C | `f` | m/s | A |
| boost | 0x050 | `f` | raw +1 | A |
| oil_pressure | 0x054 | `f` | bar | A |
| water_temp | 0x058 | `f` | C constant | A |
| oil_temp | 0x05C | `f` | C constant | A |
| tyres | 0x060 | `4f` | C surface | A |
| packet_id | 0x070 | `I` | counter | A |
| lap | 0x074 | `h` | lap | A |
| total_laps | 0x076 | `h` | laps | A |
| best_ms | 0x078 | `i` | ms | A |
| last_ms | 0x07C | `i` | ms | A |
| day_ms | 0x080 | `i` | time of day ms | A |
| start_position | 0x084 | `h` | pre-race only | A |
| start_cars | 0x086 | `h` | pre-race only | A |
| rpm_min | 0x088 | `h` | rpm | A |
| rpm_max | 0x08A | `h` | rpm | A |
| transmission_max | 0x08C | `h` | km/h | A |
| flags | 0x08E | `H` | bits | A |
| gears | 0x090 | `B` | nibbles | A |
| throttle_raw | 0x091 | `B` | 0-255 | A |
| brake_raw | 0x092 | `B` | 0-255 | A |
| road_plane | 0x094 | `3f` | raw | A |
| road_distance | 0x0A0 | `f` | m | A |
| wheel_angular | 0x0A4 | `4f` | rad/s | A |
| tyre_radius | 0x0B4 | `4f` | m | A |
| suspension | 0x0C4 | `4f` | m | A |
| unknown_a | 0x0D4 | `8f` | unknown | A |
| clutch | 0x0F4 | `f` | ratio | A |
| clutch_engagement | 0x0F8 | `f` | ratio | A |
| gearbox_rpm | 0x0FC | `f` | rpm | A |
| transmission_ratio | 0x100 | `f` | ratio | A |
| gear_ratios | 0x104 | `8f` | ratio | A |
| car_id | 0x124 | `i` | ID | A |
| steering_rotation | 0x128 | `f` | rad upstream; unverified behavior | B |
| steering_velocity | 0x12C | `f` | rad/s | B |
| acceleration_raw | 0x130 | `3f` | frame unverified | B |
| throttle_filtered | 0x13C | `B` | 0-255 | ~ |
| brake_filtered | 0x13D | `B` | 0-255 | ~ |
| unknown_t_bytes | 0x13E | `2B` | unknown | ~ |
| torque_vectors | 0x140 | `4f` | upstream interpretation unverified | ~ |
| energy_recovery | 0x150 | `f` | unknown | ~ |
| unknown_t | 0x154 | `f` | unknown | ~ |
| surface | 0x158 | `4s` | upstream surface codes | C |
| current_ms | 0x15C | `i` | ms upstream; opt-in | C |
| wheel_steering | 0x160 | `2f` | rad upstream; opt-in | C |
| wheelbase | 0x168 | `f` | m | C |
| category | 0x16C | `4s` | text | C |

## Calculated channels

- speed_kmh = speed_m_s × 3.6.
- gear = low gear nibble; suggested_gear = high nibble, 15 means unavailable.
- throttle/brake = raw byte / 255.
- wheel_speed_kmh = abs(angular_rad_s × radius_m) × 3.6.
- wheel_speed_ratio = wheel linear / car speed; null below 10 m/s, during significant yaw, or an unsuitable road-plane distance. This is an indicator, not confirmed slip.
- Lap pace, fuel use, reserve margin and coasting/overlap/limiter durations are labeled calculations.
- Track/layout, setup notes, race distance/duration, reserve and pit region/limit are user assumptions.

## Unavailable or deliberately gated

Opponent positions/radar, live standings, race gaps, flags/penalties, tyre wear/pressure/compound, exact damage, weather, track name, fuel map and official finish/validity are not supplied as established capabilities. Pre-race position/car count are not live standings. Oil/water temperatures are upstream-described constants. Steering wheel rotation is distinct from front road-wheel angles. C surface/current timing require trust_c_fields before user-facing interpretation. There is no understeer/oversteer diagnosis.