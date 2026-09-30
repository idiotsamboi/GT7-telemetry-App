"""Bounded notification center storage (F097). Levels: CRITICAL, IMPORTANT, NORMAL, SILENT."""
from __future__ import annotations

LEVELS = ('CRITICAL', 'IMPORTANT', 'NORMAL', 'SILENT')
MAX_PER_DRIVER = 200
_COLUMNS = ('id', 'driver_id', 'level', 'title', 'body', 'read_at', 'created_at')


def add_notification(db, notification_id: str, driver_id: str, level: str, title: str, body: str, stamp: str) -> bool:
    if level not in LEVELS:
        raise ValueError('Unknown notification level')
    cur = db.execute('INSERT OR IGNORE INTO career_notifications(id,driver_id,level,title,body,read_at,created_at) VALUES(?,?,?,?,?,NULL,?)',
                     (notification_id, driver_id, level, title[:120], body[:400], stamp))
    db.execute('DELETE FROM career_notifications WHERE driver_id=? AND id NOT IN '
               '(SELECT id FROM career_notifications WHERE driver_id=? ORDER BY created_at DESC,id DESC LIMIT ?)',
               (driver_id, driver_id, MAX_PER_DRIVER))
    return bool(cur.rowcount)


def list_notifications(store, driver_id: str, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    return store.query('SELECT ' + ','.join(_COLUMNS) + ' FROM career_notifications WHERE driver_id=? '
                       'ORDER BY created_at DESC,id DESC LIMIT ?', (driver_id, limit))


def mark_read(store, driver_id: str, notification_id: str, stamp: str) -> dict:
    def operation(db):
        cur = db.execute('UPDATE career_notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND driver_id=?', (stamp, notification_id, driver_id))
        if not cur.rowcount:
            raise ValueError('Unknown notification')
        row = db.execute('SELECT ' + ','.join(_COLUMNS) + ' FROM career_notifications WHERE id=?', (notification_id,)).fetchone()
        return dict(zip(_COLUMNS, row))
    return store.career_transaction(operation)
