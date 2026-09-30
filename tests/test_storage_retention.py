from datetime import datetime, timedelta, timezone

from backend.app.storage.retention import GB, RetentionPolicy, select_for_archive

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def session(sid, days_old, **extra):
    started = NOW - timedelta(days=days_old)
    base = {'id': sid, 'started': started.isoformat(), 'ended': (started + timedelta(hours=1)).isoformat(),
            'protected': 0, 'archived_at': None, 'meta': {}}
    return {**base, **extra}


def test_age_selection_oldest_first():
    sessions = [session('new', 5), session('old', 200), session('older', 400), session('mid', 91)]
    assert select_for_archive(sessions, RetentionPolicy(days=90), NOW, 0) == ['older', 'old', 'mid']
    assert select_for_archive(sessions, RetentionPolicy(days=90), NOW.timestamp(), 0) == ['older', 'old', 'mid']


def test_protected_active_archived_favourites_never_selected():
    sessions = [session('prot', 999, protected=1), session('active', 999, ended=None), session('gone', 999, archived_at='x'),
                session('fav', 999, meta={'favourite': True}), session('ok', 999)]
    assert select_for_archive(sessions, RetentionPolicy(days=1), NOW, 0) == ['ok']
    assert 'fav' in select_for_archive(sessions, RetentionPolicy(days=1, protect_favourites=False), NOW, 0)
    # size pressure cannot override protection either
    assert select_for_archive(sessions, RetentionPolicy(days=10_000, max_bytes=1), NOW, 10 * GB) == ['ok']


def test_size_cap_archives_oldest_until_under_cap():
    sessions = [session('a', 60, bytes=GB), session('b', 40, bytes=GB), session('c', 20, bytes=GB), session('d', 1, bytes=GB)]
    policy = RetentionPolicy(days=90, max_bytes=2 * GB + GB // 2)
    assert select_for_archive(sessions, policy, NOW, 4 * GB) == ['a', 'b']
    assert select_for_archive(sessions, policy, NOW, 2 * GB) == []
    even = [session('x', 30), session('y', 10)]
    assert select_for_archive(even, RetentionPolicy(days=90, max_bytes=GB), NOW, 2 * GB) == ['x']
    assert RetentionPolicy.from_settings(30, 1.5).max_bytes == int(1.5 * GB)


def test_bad_dates_are_skipped_not_fatal():
    bad = session('bad', 500, started='garbage')
    assert select_for_archive([session('ok', 500), bad], RetentionPolicy(days=1), NOW, 0) == ['ok']
