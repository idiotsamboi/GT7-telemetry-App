"""Offline intent grammar and an optional, isolated microphone worker."""
import json, re, queue, multiprocessing as mp, time, math, array, shutil, subprocess, threading, tempfile, wave
from pathlib import Path

ALIASES={
 'radio check':'radio','status':'status','how much fuel':'fuel','fuel status':'fuel','can i finish':'finish','how much do i need to save':'save','when should i pit':'pit',
 'box this lap':'box','last lap':'last','best lap':'best','delta to reference':'delta','where am i losing time':'loss','how are the tyres':'tyres','how are the tires':'tyres',
 'what happened that lap':'lap_summary','compare with my best':'compare','use the last lap as reference':'reference','mark this corner':'corner','mark that incident':'incident',
 'show live':'show_live','show analysis':'show_analysis','show strategy':'show_strategy','repeat':'repeat','speak less':'less','speak more':'more',
 'quiet for two minutes':'quiet','mute':'mute','stop talking':'stop','resume engineer':'resume','end session':'end'}

def intent(text):
    text=re.sub(r'[^a-z0-9 .:]','',text.lower()).strip().rstrip('.?')
    if text in ALIASES:return ALIASES[text],None
    if text.startswith('save a note ') and len(text)>12:return 'note',text[12:500]
    m=re.fullmatch(r'set target lap time (\d{1,2}):(\d{2})(?:\.(\d{1,3}))?',text)
    if m and int(m[2])<60:return 'target',(int(m[1])*60+int(m[2]))*1000+int((m[3] or '').ljust(3,'0'))
    numbers={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'twenty':20,'thirty':30,'forty':40,'fifty':50}
    m=re.fullmatch(r'set target lap time (.+?) minutes? (.+?) seconds?',text)
    if m:
        def num(s):return int(s) if s.isdigit() else sum(numbers[w] for w in s.split())
        try:
            minutes,seconds=num(m[1]),num(m[2])
            if 0<=minutes<60 and 0<=seconds<60:return 'target',(minutes*60+seconds)*1000
        except KeyError:pass
    return 'unknown',None

def mic_worker(commands,results,settings):
    def send(x):
        try:results.put_nowait(x)
        except queue.Full:pass
    try:
        import sounddevice as sd
        from vosk import Model,KaldiRecognizer,SetLogLevel
        SetLogLevel(-1)
        if not Path(settings['vosk_model']).is_dir():raise RuntimeError('Choose an installed small Vosk model directory')
        model=Model(settings['vosk_model']); rate=settings['mic_rate']
        grammar=json.dumps(list(ALIASES)+['[unk]'])
        recognizer=None; listening=False; started=0; chunks=queue.Queue(64)
        def callback(indata,frames,timing,status):
            try:chunks.put_nowait(bytes(indata))
            except queue.Full:send({'error':'Microphone input queue overflow'})
        with sd.RawInputStream(samplerate=rate,blocksize=1600,dtype='int16',channels=1,device=settings['input_device'],callback=callback):
            send({'state':'ready'})
            while True:
                try:
                    cmd=commands.get_nowait()
                    if cmd=='close':break
                    if cmd=='start':
                        recognizer=KaldiRecognizer(model,rate,grammar);recognizer.SetWords(True);listening=True;started=time.monotonic();send({'state':'listening'})
                        while not chunks.empty():chunks.get_nowait()
                    if cmd=='stop' and listening:
                        result=json.loads(recognizer.FinalResult());send({'result':result});listening=False;send({'state':'ready'})
                except queue.Empty:pass
                try:data=chunks.get(timeout=.1)
                except queue.Empty:continue
                values=array.array('h',data);peak=max(map(abs,values),default=0)/32768
                send({'level':peak,'clipping':peak>.98})
                if listening:
                    recognizer.AcceptWaveform(data)
                    if time.monotonic()-started>12:send({'result':json.loads(recognizer.FinalResult())});listening=False;send({'state':'ready'})
    except Exception as e:send({'state':'unavailable','error':str(e)})

class Microphone:
    def __init__(self):self.process=None; self.commands=mp.Queue(8);self.results=mp.Queue(64);self.state='disabled';self.level=0.;self.clipping=False;self.error=None
    def start_worker(self,settings):
        if self.process and self.process.is_alive():return
        if not settings.vosk_model:self.error='Install Vosk, sounddevice, PortAudio and select a small English model in Settings';self.state='unavailable';return
        # Never reuse queues from a stopped/terminated worker (stale close/PTT).
        self.commands=mp.Queue(8);self.results=mp.Queue(64);self.error=None
        self.process=mp.Process(target=mic_worker,args=(self.commands,self.results,settings.model_dump(mode='json')),daemon=True);self.process.start();self.state='loading'
    def control(self,cmd):
        try:self.commands.put_nowait(cmd)
        except queue.Full:self.error='Microphone control queue full'
    def poll(self):
        texts=[]
        for _ in range(64):
            try:r=self.results.get_nowait()
            except queue.Empty:break
            self.state=r.get('state',self.state);self.level=r.get('level',self.level);self.clipping=r.get('clipping',self.clipping);self.error=r.get('error',self.error)
            if 'result' in r:texts.append(r['result'])
        return texts
    def close(self):
        if self.process:
            self.control('close')
            self.process.join(1)
            if self.process.is_alive():self.process.terminate();self.process.join(1)
        self.process=None;self.state='disabled';self.level=0.;self.clipping=False

class Speaker:
    def __init__(self):self.process=None;self.thread=None;self.error=None;self.finished=0;self.cancelled=threading.Event();self.priority=9
    @property
    def busy(self):return bool(self.thread and self.thread.is_alive())
    def stop(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:self.process.terminate()
        try:
            import sounddevice as sd
            sd.stop()
        except ImportError:pass
        self.finished=time.monotonic()
    def speak(self,text,settings,priority=2):
        if self.busy:return False
        self.cancelled.clear();self.priority=priority
        def run():
            try:
                if settings.tts=='piper':
                    import sounddevice as sd
                    with tempfile.TemporaryDirectory() as d:
                        target=str(Path(d)/'speech.wav')
                        args=['piper','--model',settings.piper_model,'--output_file',target]
                        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                        _,err=self.process.communicate(text.encode(),timeout=30)
                        if self.process.returncode:raise RuntimeError(err.decode(errors='replace')[:300])
                        if self.cancelled.is_set():return
                        with wave.open(target) as w:
                            import numpy as np
                            samples=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16);rate=w.getframerate()
                        sd.play(samples,rate,device=settings.output_device,blocking=True)
                else:
                    binary=shutil.which('espeak-ng') or shutil.which('espeak')
                    if not binary:raise RuntimeError('eSpeak NG unavailable; install espeak-ng on Ubuntu')
                    args=[binary,'-v',settings.voice,'-s',str(settings.voice_rate),'-a',str(settings.voice_volume),'--stdin']
                    if settings.output_device is None:
                        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                        _,err=self.process.communicate(text.encode(),timeout=30)
                        if self.process.returncode and not self.cancelled.is_set():raise RuntimeError(err.decode(errors='replace')[:300])
                    else:
                        import sounddevice as sd,numpy as np
                        with tempfile.TemporaryDirectory() as d:
                            path=str(Path(d)/'speech.wav');args[1:1]=['-w',path]
                            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);self.process.communicate(text.encode(),timeout=30)
                            if self.cancelled.is_set():return
                            with wave.open(path) as w:samples=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16);rate=w.getframerate()
                            sd.play(samples,rate,device=settings.output_device,blocking=True)
                self.error=None
            except Exception as e:self.error=str(e)
            finally:self.finished=time.monotonic()
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return True

def audio_devices():
    try:
        import sounddevice as sd
        return {'devices':[dict(x) for x in sd.query_devices()],'default':list(sd.default.device)}
    except Exception as e:return {'devices':[],'error':str(e)}

def audio_probe(settings,playback=False):
    """Two-second in-memory test; caller explicitly requested calibration or playback."""
    try:
        import sounddevice as sd,numpy as np
        audio=sd.rec(int(settings.mic_rate*2),samplerate=settings.mic_rate,channels=1,dtype='float32',device=settings.input_device,blocking=True)
        rms=float(np.sqrt(np.mean(audio**2)));peak=float(np.max(np.abs(audio)))
        if playback:sd.play(audio,settings.mic_rate,device=settings.output_device,blocking=True)
        return {'rms':rms,'peak':peak,'clipping':peak>.98,'suggested_voice_threshold':min(.5,max(.01,rms*3)),'duration_s':2,'stored':False,'playback':playback}
    except Exception as e:return {'error':str(e),'stored':False}
