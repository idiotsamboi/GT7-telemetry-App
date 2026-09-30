# Phase 4 - challenges & competition (F031-F050)
4a: F033 session challenge, F036 chains, F041 PB boss, F043 find-one-second, F044 consistency boss, F050 perfect session.
4b: F042 sector recovery (no official sectors: use CALCULATED equal-distance/corner segments, labelled), F046 best-lap composition (theoretical best from own segments, CALCULATED), F047 ghost reference (own best/reference lap only), F048 personal rival (own past self; never other drivers' data unless SHARED_DRIVER explicit), F049 comeback (recover after regression vs own median).
Design: new module gamification/challenge_types.py (registry of types: generator + evaluator + gates) reusing challenges.py offer/accept/skip/expiry/frozen-target/rewards; no new engine. Replay/demo/synthetic never progress or reward. Rejection gates per spec 14.7.
Tests per batch: tests/test_gamification_challenge_types_{a,b}.py. Rollback: flag dynamic_challenges.
