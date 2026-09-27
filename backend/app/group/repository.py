"""Durable group records in the existing SQLite database; independent of receiver queue."""
import sqlite3,json,threading,time,hashlib,secrets,uuid
from pathlib import Path
from contextlib import contextmanager

def uid():return uuid.uuid4().hex
def digest(token):return hashlib.sha256(token.encode()).hexdigest()
def encode(value):return json.dumps(value,separators=(',',':'),allow_nan=False)

class GroupRepository:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock()
  with self.connect() as db:
   db.executescript('''CREATE TABLE IF NOT EXISTS group_schema(version INTEGER NOT NULL);
INSERT INTO group_schema SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM group_schema);
CREATE TABLE IF NOT EXISTS group_documents(kind TEXT NOT NULL,id TEXT PRIMARY KEY,parent TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS group_document_parent ON group_documents(kind,parent);
CREATE TABLE IF NOT EXISTS group_credentials(hash TEXT PRIMARY KEY,kind TEXT NOT NULL,subject TEXT NOT NULL,group_id TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS group_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,group_id TEXT NOT NULL,session_id TEXT NOT NULL,utc REAL NOT NULL,actor TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS group_event_session ON group_events(session_id,seq);
CREATE TABLE IF NOT EXISTS group_frames(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,utc REAL NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS group_frame_session ON group_frames(session_id,utc);
''')
 @contextmanager
 def connect(self):
  db=sqlite3.connect(self.path,timeout=2);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
  try:
   with db:yield db
  finally:db.close()
 def docs(self,kind,parent=None):
  with self.connect() as db:
   rows=db.execute('SELECT payload FROM group_documents WHERE kind=?'+(' AND parent=?' if parent is not None else '')+' ORDER BY rowid LIMIT 10000',(kind,parent) if parent is not None else (kind,)).fetchall()
  return [json.loads(r[0]) for r in rows]
 def get(self,kind,id):
  with self.connect() as db:r=db.execute('SELECT payload FROM group_documents WHERE kind=? AND id=?',(kind,id)).fetchone()
  return json.loads(r[0]) if r else None
 def commit(self,documents=(),event=None):
  with self.lock,self.connect() as db:
   for kind,id,parent,data in documents:db.execute('INSERT INTO group_documents VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,parent=excluded.parent',(kind,id,parent,encode(data)))
   seq=None
   if event:
    group,session,actor,kind,data=event
    seq=db.execute('INSERT INTO group_events(group_id,session_id,utc,actor,kind,payload) VALUES(?,?,?,?,?,?)',(group,session,time.time(),actor,kind,encode(data))).lastrowid
   return seq
 def token(self,kind,subject,group,ttl=86400):
  token=secrets.token_urlsafe(32)
  with self.lock,self.connect() as db:db.execute('INSERT INTO group_credentials VALUES(?,?,?,?,?,0)',(digest(token),kind,subject,group,time.time()+ttl))
  return token
 def auth(self,token,kinds=None):
  if not token or len(token)>256:return None
  with self.connect() as db:r=db.execute('SELECT kind,subject,group_id,expires FROM group_credentials WHERE hash=? AND revoked=0 AND expires>?',(digest(token),time.time())).fetchone()
  if not r or kinds is not None and r['kind'] not in kinds:return None
  return dict(r)
 def revoke(self,subject,kind=None):
  with self.lock,self.connect() as db:db.execute('UPDATE group_credentials SET revoked=1 WHERE subject=?'+(' AND kind=?' if kind else ''),(subject,kind) if kind else (subject,))
 def events(self,group,after=0,session=None):
  with self.connect() as db:
   rows=db.execute('SELECT * FROM group_events WHERE group_id=? AND seq>?'+(' AND session_id=?' if session else '')+' ORDER BY seq LIMIT 1000',(group,after,session) if session else (group,after)).fetchall()
  return [{**dict(r),'payload':json.loads(r['payload'])} for r in rows]
 def frame(self,session,utc,data):
  with self.lock,self.connect() as db:db.execute('INSERT INTO group_frames(session_id,utc,payload) VALUES(?,?,?)',(session,utc,encode(data)))
 def frame_at(self,session,utc):
  with self.connect() as db:r=db.execute('SELECT payload FROM group_frames WHERE session_id=? AND utc<=? ORDER BY utc DESC LIMIT 1',(session,utc)).fetchone()
  return json.loads(r[0]) if r else None
