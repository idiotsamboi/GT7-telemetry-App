# 0010. Performance profiles never alter recording fidelity

Status: accepted

## Context
The Orange Pi 4 GB hard target was dropped, but ARM64 packaging still ships and a laptop next to a PS5 may
be CPU-starved. We want a lever that helps without corrupting data.

## Decision
`Settings.performance_profile` is `AUTO | DESKTOP | LOW_POWER`. `AUTO` resolves to `LOW_POWER` when the CPU
count is ≤ 4 or RAM ≤ 4 GB (`core/platform.resolve_performance_profile`). `LOW_POWER` may lower **what is
shown or sent**: UI Hz (12 → 8), group publish Hz (10 → 5), history length, ambient motion, and it may defer
heavy analysis to lap/session end. It **never** changes the recording rate, sample content or accuracy of
laps, fuel or timing. If a future setting would, the UI must say so explicitly.

## Consequences
The recorder queue, loss accounting and derived-channel maths are profile-independent, so recordings from
any machine are comparable. There is no 4 GB design ceiling.
