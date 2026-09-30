import json, sqlite3, threading, queue, time
from concurrent.futures import Future
from ..core.defaults import RECORDER_QUEUE, RECORDER_BATCH, RECORDER_BATCH_WINDOW_S
from pathlib import Path
from .schema import migrate

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
    def __init__(self,path,capacity=RECORDER_QUEUE):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.q=queue.Queue(capacity); self.drops=0; self.failed_rows=0; self.error=None; self.written=0; self.failed_other=0; self.last_write=time.monotonic(); self.ready=threading.Event(); self.thread=threading.Thread(target=self._run,daemon=True,name='sqlite-writer'); self.thread.start(); self.ready.wait(10)
        if not self.ready.is_set():raise RuntimeError('Database writer did not start')
        if self.error:raise RuntimeError(self.error)
    def put(self,kind,args):
        try:self.q.put_nowait((kind,args,time.monotonic())); return True
        except queue.Full:self.drops+=1; return False
    def career_transaction(self, operation, timeout=10):
        """Run a bounded domain operation on the sole writer; acknowledge only after commit.

        Operations must not commit, change transaction state, or call back into Store.
        A timed-out caller must retry idempotently: its queued operation may still commit.
        """
        if threading.current_thread() is self.thread:raise RuntimeError('Nested writer transaction')
        if not self.thread.is_alive():raise RuntimeError('Database writer is closed')
        future=Future()
        self.q.put(('career',(operation,future),time.monotonic()),timeout=timeout)
        return future.result(timeout=timeout)
    def _run(self):
        try:
            db=sqlite3.connect(self.path); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=NORMAL'); db.execute('PRAGMA wal_autocheckpoint=1000'); db.executescript(MIGRATION)
            migrate(db)
            db.execute("UPDATE sessions SET status='interrupted', ended=datetime('now') WHERE ended IS NULL")
            db.commit()
        except Exception as e:self.error=str(e); self.ready.set(); return
        self.ready.set(); stopped=False
        while not stopped:
            job=self.q.get(); jobs=[job]
            deadline=time.monotonic()+RECORDER_BATCH_WINDOW_S
            for _ in range(RECORDER_BATCH-1):
                if jobs[-1][0] in ('barrier','stop'):break
                try:jobs.append(self.q.get(timeout=max(.001,deadline-time.monotonic())))
                except queue.Empty:break
                if time.monotonic()>=deadline:break
            acknowledgements=[]; batch_error=None
            try:
                with db:
                    # SAVEPOINT must be inside an outer transaction even when it is
                    # the first job; RELEASE alone would otherwise commit early.
                    db.execute('BEGIN')
                    for kind,args,_ in jobs:
                        if kind=='stop':stopped=True
                        elif kind=='barrier':pass
                        elif kind=='career':
                            operation,future=args
                            db.execute('SAVEPOINT career_job')
                            try:
                                result=operation(db)
                                db.execute('RELEASE SAVEPOINT career_job')
                                acknowledgements.append((future,result,None))
                            except Exception as exc:
                                db.execute('ROLLBACK TO SAVEPOINT career_job')
                                db.execute('RELEASE SAVEPOINT career_job')
                                self.failed_other+=1
                                acknowledgements.append((future,None,exc))
                        elif kind=='sample':db.execute('INSERT INTO samples(session,lap_id,mono,packet_id,payload) VALUES(?,?,?,?,?)',args)
                        elif kind=='session':db.execute('INSERT OR REPLACE INTO sessions(id,started,ended,status,provenance,meta,report,protected) VALUES(?,?,?,?,?,?,?,COALESCE((SELECT protected FROM sessions WHERE id=?),0))',(*args,args[0]))
                        elif kind=='lap':db.execute('INSERT OR REPLACE INTO laps VALUES(?,?,?)',args)
                        elif kind=='event':db.execute('INSERT INTO events(session,utc,payload) VALUES(?,?,?)',args)
                        elif kind in ('audit','annotation'):
                            # isolated: a malformed row is counted, it must not roll back the batch of samples around it
                            try:
                                if kind=='audit':db.execute('INSERT OR IGNORE INTO audit_log(id,utc,actor,capability,command_id,target,payload_hash,result_code,message,session_id) VALUES(?,?,?,?,?,?,?,?,?,?)',args)
                                else:db.execute('INSERT INTO events(session,utc,payload,kind) VALUES(?,?,?,?)',args)
                            except (sqlite3.Error,ValueError,TypeError,OverflowError):self.failed_other+=1
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
            except (sqlite3.Error,OSError) as e:
                batch_error=e; self.error=str(e); self.failed_rows+=sum(j[0]=='sample' for j in jobs)
            finally:
                # A later telemetry failure can roll back a successful career job.
                acknowledged={id(future) for future,_,_ in acknowledgements}
                for future,result,exc in acknowledgements:
                    if batch_error or exc:future.set_exception(batch_error or exc)
                    else:future.set_result(result)
                for kind,args,_ in jobs:
                    if kind=='career' and id(args[1]) not in acknowledged:
                        args[1].set_exception(batch_error or RuntimeError('Career job was not executed'))
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
    def read_snapshot(self,queries):
        """Repository-owned bounded queries sharing one WAL snapshot (e.g. archive exports)."""
        with sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro',uri=True,timeout=2) as db:
            db.row_factory=sqlite3.Row
            db.execute('BEGIN')
            return {name:[dict(r) for r in db.execute(sql,args).fetchall()] for name,(sql,args) in queries.items()}
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
    def audit(self,session=None,since=None,limit=500):
        where=[];args=[]
        if session is not None:where.append('session_id=?');args.append(session)
        if since is not None:where.append('utc>=?');args.append(since)
        return self.query('SELECT * FROM audit_log'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY utc DESC,id LIMIT ?',(*args,max(1,min(int(limit),5000))))
    def annotations(self,session,kinds=None,limit=1000):
        marks=''
        args=[session]
        if kinds:kinds=list(kinds);marks=' AND kind IN (%s)'%','.join('?'*len(kinds));args+=kinds
        rows=self.query('SELECT id,kind,payload FROM events WHERE session=? AND kind IS NOT NULL'+marks+' ORDER BY id LIMIT ?',(*args,max(1,min(int(limit),10000))))
        return [{**json.loads(r['payload']),'event_id':r['id'],'kind':r['kind']} for r in rows]
    def health(self):
        oldest=0
        with self.q.mutex:
            if self.q.queue:oldest=max(0,time.monotonic()-self.q.queue[0][2])
        wal=Path(str(self.path)+'-wal')
        return {'queue':self.q.qsize(),'capacity_samples':self.q.maxsize,'queue_age_s':oldest,'application_drops':self.drops,'failed_rows':self.failed_rows,'failed_other_rows':self.failed_other,'error':self.error,'written':self.written,'db_bytes':self.path.stat().st_size if self.path.exists() else 0,'wal_bytes':wal.stat().st_size if wal.exists() else 0}
