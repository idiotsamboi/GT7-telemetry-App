import json, sqlite3, threading, queue, time
from pathlib import Path

MIGRATION='''
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,started TEXT NOT NULL,ended TEXT,status TEXT NOT NULL,provenance TEXT NOT NULL,meta TEXT NOT NULL,report TEXT,protected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY,session TEXT NOT NULL,lap_id TEXT,mono REAL NOT NULL,packet_id INTEGER NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sample_session_time ON samples(session,mono);
CREATE TABLE IF NOT EXISTS laps(id TEXT PRIMARY KEY,session TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS lap_session ON laps(session);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,session TEXT,utc TEXT,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_session ON events(session,id);
CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY,payload TEXT NOT NULL);
PRAGMA user_version=1;
'''

class Store:
    """One writer thread; 8192 jobs, drop-new with explicit accounting. 240-row batches."""
    def __init__(self,path,capacity=8192):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.q=queue.Queue(capacity); self.drops=0; self.failed_rows=0; self.error=None; self.written=0; self.last_write=time.monotonic(); self.ready=threading.Event(); self.thread=threading.Thread(target=self._run,daemon=True,name='sqlite-writer'); self.thread.start(); self.ready.wait(10)
        if not self.ready.is_set():raise RuntimeError('Database writer did not start')
        if self.error:raise RuntimeError(self.error)
    def put(self,kind,args):
        try:self.q.put_nowait((kind,args,time.monotonic())); return True
        except queue.Full:self.drops+=1; return False
    def _run(self):
        try:
            db=sqlite3.connect(self.path); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=NORMAL'); db.execute('PRAGMA wal_autocheckpoint=1000'); db.executescript(MIGRATION)
            columns={r[1] for r in db.execute('PRAGMA table_info(sessions)')}
            if 'archived_at' not in columns:db.execute('ALTER TABLE sessions ADD COLUMN archived_at TEXT')
            db.execute('PRAGMA user_version=2')
            db.execute("UPDATE sessions SET status='interrupted', ended=datetime('now') WHERE ended IS NULL")
            db.commit()
        except Exception as e:self.error=str(e); self.ready.set(); return
        self.ready.set(); stopped=False
        while not stopped:
            job=self.q.get(); jobs=[job]
            deadline=time.monotonic()+.20
            for _ in range(239):
                if jobs[-1][0] in ('barrier','stop'):break
                try:jobs.append(self.q.get(timeout=max(.001,deadline-time.monotonic())))
                except queue.Empty:break
                if time.monotonic()>=deadline:break
            try:
                with db:
                    for kind,args,_ in jobs:
                        if kind=='stop':stopped=True
                        elif kind=='barrier':pass
                        elif kind=='sample':db.execute('INSERT INTO samples(session,lap_id,mono,packet_id,payload) VALUES(?,?,?,?,?)',args)
                        elif kind=='session':db.execute('INSERT OR REPLACE INTO sessions(id,started,ended,status,provenance,meta,report,protected) VALUES(?,?,?,?,?,?,?,COALESCE((SELECT protected FROM sessions WHERE id=?),0))',(*args,args[0]))
                        elif kind=='lap':db.execute('INSERT OR REPLACE INTO laps VALUES(?,?,?)',args)
                        elif kind=='event':db.execute('INSERT INTO events(session,utc,payload) VALUES(?,?,?)',args)
                        elif kind=='metadata':db.execute('UPDATE sessions SET meta=?,protected=? WHERE id=?',args)
                        elif kind=='archive':
                            stamp,sid=args
                            db.execute('UPDATE sessions SET archived_at=? WHERE id=? AND ended IS NOT NULL AND (protected=0 OR ? IS NULL)',(stamp,sid,stamp))
                        elif kind=='correct':db.execute('UPDATE sessions SET status=?,report=? WHERE id=? AND ended IS NOT NULL',args)
                        elif kind=='purge':
                            eligible=db.execute('SELECT id FROM sessions WHERE id=? AND ended IS NOT NULL AND protected=0 AND archived_at IS NOT NULL',(args,)).fetchone()
                            if eligible:
                                for table in ('samples','laps','events'):db.execute(f'DELETE FROM {table} WHERE session=?',(args,))
                                db.execute('DELETE FROM sessions WHERE id=?',(args,))
                        elif kind=='profile':db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?)',args)
                self.written+=sum(j[0]=='sample' for j in jobs); self.last_write=time.monotonic(); self.error=None
            except (sqlite3.Error,OSError) as e:self.error=str(e); self.failed_rows+=sum(j[0]=='sample' for j in jobs)
            finally:
                for kind,args,_ in jobs:
                    if kind=='barrier':args.set()
                    self.q.task_done()
        try:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:db.close()
    def flush(self,timeout=10):
        event=threading.Event(); self.q.put(('barrier',event,time.monotonic()),timeout=timeout)
        if not event.wait(timeout):raise TimeoutError('Storage flush timed out')
    def close(self):
        self.q.put(('stop',None,time.monotonic()),timeout=10); self.thread.join(15)
    def query(self,sql,args=()):
        with sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro',uri=True,timeout=2) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute(sql,args).fetchall()]
    def sessions(self,include_archived=False):
        rows=self.query('SELECT * FROM sessions WHERE (? OR archived_at IS NULL) ORDER BY started DESC LIMIT 200',(int(include_archived),))
        for r in rows:r['meta']=json.loads(r['meta']); r['report']=json.loads(r['report']) if r['report'] else None
        return rows
    def detail(self,sid):
        rows=self.query('SELECT * FROM sessions WHERE id=?',(sid,))
        if not rows:return None
        r=rows[0]; r['meta']=json.loads(r['meta']); r['report']=json.loads(r['report']) if r['report'] else None
        r['laps']=[json.loads(x['payload']) for x in self.query('SELECT payload FROM laps WHERE session=? ORDER BY rowid LIMIT 10000',(sid,))]
        r['events']=[json.loads(x['payload']) for x in self.query('SELECT payload FROM events WHERE session=? ORDER BY id DESC LIMIT 500',(sid,))]
        return r
    def samples(self,sid,after=-1e30,limit=10000,after_id=None):
        if after_id is None:
            result=self.query('SELECT id,payload FROM samples WHERE session=? AND mono>? ORDER BY mono,id LIMIT ?',(sid,after,min(limit,10000)))
        else:
            result=self.query('SELECT id,payload FROM samples WHERE session=? AND mono>=? AND id>? ORDER BY id LIMIT ?',(sid,after,after_id,min(limit,10000)))
        return [{**json.loads(r['payload']),'record_id':r['id']} for r in result]
    def health(self):
        oldest=0
        with self.q.mutex:
            if self.q.queue:oldest=max(0,time.monotonic()-self.q.queue[0][2])
        wal=Path(str(self.path)+'-wal')
        return {'queue':self.q.qsize(),'capacity_samples':self.q.maxsize,'queue_age_s':oldest,'application_drops':self.drops,'failed_rows':self.failed_rows,'error':self.error,'written':self.written,'db_bytes':self.path.stat().st_size if self.path.exists() else 0,'wal_bytes':wal.stat().st_size if wal.exists() else 0}
