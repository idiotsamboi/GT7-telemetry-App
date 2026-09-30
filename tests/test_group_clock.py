"""Clock offset sign: the client reports (client - host); the host subtracts it from client timestamps."""
from backend.app.group.client import clock_offset_ms
from backend.app.group.history import common_timeline


def test_client_clock_ahead_gives_positive_offset_and_maps_onto_host_time():
    host_now = 1000.0
    skew = 2.0                                   # client clock is 2 s ahead of the host
    sent, received = host_now + skew - .05, host_now + skew + .05      # 100 ms round trip, host replies mid-flight
    offset = clock_offset_ms(sent, received, host_time=host_now)
    assert abs(offset - 2000) < 1e-6
    sample_client_time = host_now + skew + 10.0  # a packet stamped 10 s later on the client's clock
    T, extra = common_timeline(sample_client_time, received=None, offset_ms=offset)
    assert abs(T - (host_now + 10.0)) < 1e-6 and extra == 0.0        # lands on the host timeline


def test_client_clock_behind_gives_negative_offset():
    assert clock_offset_ms(99.95, 100.05, host_time=101.0) == -1000.0
    T, _ = common_timeline(110.0, None, -1000.0)
    assert T == 111.0


def test_synchronised_clocks_give_near_zero_offset():
    assert abs(clock_offset_ms(50.0, 50.1, host_time=50.05)) < 1e-6
