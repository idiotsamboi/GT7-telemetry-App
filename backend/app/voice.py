"""Offline intent grammar and an optional, isolated microphone worker."""
import json, re, queue, multiprocessing as mp, time, math, array, shutil, subprocess, threading, tempfile, wave, os
from pathlib import Path
from .requests import CATALOG

ALIASES={
 'radio check':'radio','status':'status','how much fuel':'fuel','fuel status':'fuel','can i finish':'finish','how much do i need to save':'save','when should i pit':'pit',
 'box this lap':'box','last lap':'last','best lap':'best','delta to reference':'delta','where am i losing time':'loss','how are the tyres':'tyres','how are the tires':'tyres',
 'what happened that lap':'lap_summary','compare with my best':'compare','use the last lap as reference':'reference','mark this corner':'corner','mark that incident':'incident',
 'show live':'show_live','show analysis':'show_analysis','show strategy':'show_strategy','repeat':'repeat','speak less':'less','speak more':'more',
 'quiet for two minutes':'quiet','mute':'mute','stop talking':'stop','resume engineer':'resume','end session':'end'}
ALIASES.update({spec['request']:key for key,spec in CATALOG.items()})
ALIASES.update({phrase:'unbox' for phrase in ('unmark pit intent','cancel pit intent','cancel pit stop','stay out')})
ALIASES.update({phrase.replace('tyre','tire'):key for phrase,key in list(ALIASES.items()) if 'tyre' in phrase})

def intent(text):
    text=' '.join(re.sub(r'[^a-z0-9 .:]','',text.lower()).split()).strip().rstrip('.?')
    text=text.removeprefix('please ').removeprefix('engineer ').replace('tires','tyres').replace('tire','tyre')
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

def mic_worker(commands,results,settings,suppressed):
    def send(x):
        try:results.put_nowait(x)
        except queue.Full:pass
    try:
        import sounddevice as sd
        from vosk import Model,KaldiRecognizer,SetLogLevel
        SetLogLevel(-1)
        if not Path(settings['vosk_model']).is_dir():raise RuntimeError('Choose an installed small Vosk model directory')
        model=Model(settings['vosk_model']); rate=settings['mic_rate']
        device=sd.query_devices(settings['input_device'],'input')
        try:sd.check_input_settings(device=settings['input_device'],channels=1,dtype='int16',samplerate=rate)
        except sd.PortAudioError:rate=int(device['default_samplerate'])
        grammar=json.dumps(list(ALIASES)+['engineer '+phrase for phrase in ALIASES]+['[unk]'])
        recognizer=KaldiRecognizer(model,rate,grammar);recognizer.SetWords(True)
        continuous=settings.get('hands_free',False);listening=continuous;started=time.monotonic();blocked=False;chunks=queue.Queue(16)
        def callback(indata,frames,timing,status):
            if suppressed.is_set():return
            if status:send({'error':str(status)})
            try:chunks.put_nowait(bytes(indata))
            except queue.Full:send({'error':'Microphone input queue overflow'})
        with sd.RawInputStream(samplerate=rate,blocksize=max(800,rate//10),dtype='int16',channels=1,device=settings['input_device'],callback=callback):
            send({'state':'listening' if continuous else 'ready','input_device':device['name'],'sample_rate':rate})
            while True:
                try:
                    cmd=commands.get_nowait()
                    if cmd=='close':break
                    if cmd=='start':
                        recognizer.Reset();listening=True;started=time.monotonic();send({'state':'listening'})
                        while not chunks.empty():chunks.get_nowait()
                    if cmd=='stop' and listening:
                        result=json.loads(recognizer.FinalResult());send({'result':result,'captured_at':time.monotonic()});recognizer.Reset();listening=continuous;started=time.monotonic();send({'state':'listening' if continuous else 'ready'})
                except queue.Empty:pass
                if suppressed.is_set():
                    if not blocked:recognizer.Reset();send({'state':'suppressed','level':0})
                    blocked=True
                    while not chunks.empty():chunks.get_nowait()
                    time.sleep(.05);continue
                if blocked:
                    while not chunks.empty():chunks.get_nowait()
                    recognizer.Reset();blocked=False;started=time.monotonic();send({'state':'listening' if listening else 'ready'})
                try:data=chunks.get(timeout=.1)
                except queue.Empty:continue
                values=array.array('h',data);peak=max(map(abs,values),default=0)/32768
                send({'level':peak,'clipping':peak>.98})
                if listening:
                    if recognizer.AcceptWaveform(data):
                        send({'result':json.loads(recognizer.Result()),'captured_at':time.monotonic()});started=time.monotonic()
                    if time.monotonic()-started>12:
                        send({'result':json.loads(recognizer.FinalResult()),'captured_at':time.monotonic()});recognizer.Reset();listening=continuous;started=time.monotonic();send({'state':'listening' if continuous else 'ready'})
    except Exception as e:send({'state':'unavailable','error':str(e)})

class Microphone:
    def __init__(self):
        self.process=None;self.commands=mp.Queue(8);self.results=mp.Queue(64);self.suppressed=mp.Event();self.state='disabled';self.level=0.;self.clipping=False;self.error=None
        self.last_attempt=-1e30;self.input_name=None;self.sample_rate=None;self.accept_after=0
    def set_suppressed(self,value):
        if value:self.suppressed.set();self.accept_after=time.monotonic()
        else:self.suppressed.clear()
    def start_worker(self,settings):
        if self.process and self.process.is_alive():return
        self.last_attempt=time.monotonic()
        if not settings.vosk_model:self.error='Install Vosk, sounddevice, PortAudio and select a small English model in Settings';self.state='unavailable';return
        # Never reuse queues from a stopped/terminated worker (stale close/PTT).
        self.commands=mp.Queue(8);self.results=mp.Queue(64);self.error=None
        self.process=mp.Process(target=mic_worker,args=(self.commands,self.results,settings.model_dump(mode='json'),self.suppressed),daemon=True);self.process.start();self.state='loading'
    def control(self,cmd):
        try:self.commands.put_nowait(cmd)
        except queue.Full:self.error='Microphone control queue full'
    def poll(self):
        texts=[]
        for _ in range(64):
            try:r=self.results.get_nowait()
            except queue.Empty:break
            self.state=r.get('state',self.state);self.level=r.get('level',self.level);self.clipping=r.get('clipping',self.clipping);self.error=r.get('error',self.error)
            self.input_name=r.get('input_device',self.input_name);self.sample_rate=r.get('sample_rate',self.sample_rate)
            if 'result' in r and not self.suppressed.is_set() and r.get('captured_at',0)>=self.accept_after:texts.append(r['result'])
        if self.process and not self.process.is_alive() and self.state not in ('disabled','unavailable'):
            self.state='unavailable';self.error=self.error or 'Microphone worker stopped; retrying automatically in hands-free mode'
        return texts
    def close(self):
        if self.process:
            self.control('close')
            self.process.join(1)
            if self.process.is_alive():self.process.terminate();self.process.join(1)
        self.process=None;self.state='disabled';self.level=0.;self.clipping=False

class Speaker:
    def __init__(self):
        self.process=None;self.thread=None;self.error=None;self.finished=0;self.cancelled=threading.Event();self.priority=9
        self.state='idle';self.engine=None;self.output_name=None;self.frames=0;self.duration=0.;self.last_text=''
    @property
    def busy(self):return bool(self.thread and self.thread.is_alive())
    def status(self):return {'state':self.state,'engine':self.engine,'output_device':self.output_name,'frames':self.frames,'duration_s':round(self.duration,2),'error':self.error,'last_text':self.last_text}
    def stop(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:self.process.terminate()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:pass
        if self.busy:self.state='stopped'
        self.finished=time.monotonic()
    def _execute(self,args,text,env=None):
        if self.cancelled.is_set():return
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:_,err=self.process.communicate(text.encode('utf-8'),timeout=45)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.communicate();raise RuntimeError('Speech synthesis timed out')
        if self.process.returncode and not self.cancelled.is_set():raise RuntimeError(err.decode(errors='replace')[:400] or 'Speech engine exited without audio')
    def _render(self,text,settings,path):
        if settings.tts=='piper':
            self.engine='Piper';self._execute(['piper','--model',settings.piper_model,'--output_file',str(path)],text)
        else:
            binary=shutil.which('espeak-ng') or shutil.which('espeak')
            if os.name=='nt' and not binary:
                self.engine='Windows system voice'
                env=os.environ.copy();env['GT7_SPEECH_WAV']=str(path)
                script="$ErrorActionPreference='Stop'; [Console]::InputEncoding=[System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; $voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; $voice.Volume="+str(settings.voice_volume)+"; $voice.Rate="+str(max(-10,min(10,round((settings.voice_rate-165)/20))))+"; try { $voice.SetOutputToWaveFile($env:GT7_SPEECH_WAV); $voice.Speak([Console]::In.ReadToEnd()) } finally { $voice.Dispose() }"
                self._execute(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],text,env)
            else:
                if not binary:raise RuntimeError('No speech engine found. Install espeak-ng or configure Piper.')
                self.engine='eSpeak NG';self._execute([binary,'-w',str(path),'-v',settings.voice,'-s',str(settings.voice_rate),'-a',str(settings.voice_volume),'--stdin'],text)
    def speak(self,text,settings,priority=2):
        if self.busy:return False
        self.cancelled.clear();self.priority=priority;self.error=None;self.frames=0;self.duration=0.;self.output_name=None;self.last_text=text;self.state='synthesizing'
        def run():
            try:
                import sounddevice as sd,numpy as np
                if settings.voice_volume==0:raise RuntimeError('Engineer volume is zero. Increase speaking volume in Settings.')
                with tempfile.TemporaryDirectory() as folder:
                    path=Path(folder)/'speech.wav';self._render(text,settings,path)
                    if self.cancelled.is_set():return
                    with wave.open(str(path),'rb') as wav:
                        width=wav.getsampwidth();channels=wav.getnchannels();rate=wav.getframerate();raw=wav.readframes(wav.getnframes())
                    if width!=2:raise RuntimeError('Speech engine produced unsupported audio; expected 16-bit PCM')
                    samples=np.frombuffer(raw,dtype=np.int16)
                    if samples.size==0 or not np.any(samples):raise RuntimeError('Speech engine produced silence')
                    samples=samples.reshape(-1,channels)
                    if settings.tts=='piper':samples=(samples.astype(np.float32)*(settings.voice_volume/100)).astype(np.int16)
                    device=sd.query_devices(settings.output_device,'output');self.output_name=device['name']
                    target_rate=int(device.get('default_samplerate') or rate)
                    if target_rate!=rate and 8000<=target_rate<=192000:
                        target_frames=round(len(samples)*target_rate/rate)
                        grid=np.arange(target_frames)*rate/target_rate
                        samples=np.stack([np.interp(grid,np.arange(len(samples)),samples[:,i]) for i in range(channels)],axis=1).astype(np.int16);rate=target_rate
                    self.frames=len(samples);self.duration=self.frames/rate;self.state='playing'
                    if self.cancelled.is_set():return
                    sd.play(samples,rate,device=settings.output_device,blocking=True)
                    self.state='stopped' if self.cancelled.is_set() else 'completed'
            except Exception as error:
                if not self.cancelled.is_set():self.error=str(error);self.state='error'
            finally:
                if self.cancelled.is_set():self.state='stopped'
                self.finished=time.monotonic()
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
