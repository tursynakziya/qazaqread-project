// Reading page: records the student's voice and streams it to the server,
// which recognises Kazakh speech live (Vosk). Correctly read words light up
// green, wrong or skipped ones yellow. At the end the full recording is
// uploaded and scored on the server.
(function () {
  const words = JSON.parse(document.getElementById('text-words').textContent);
  const serverSpeech = JSON.parse(document.getElementById('server-speech').textContent);
  const liveUrl = document.getElementById('live-url').dataset.url;
  const LIMIT_MS = JSON.parse(document.getElementById('reading-seconds').textContent) * 1000;
  const spans = Array.from(document.querySelectorAll('#passage .word'));
  const $ = id => document.getElementById(id);
  const ui = {
    start: $('btn-start'), pause: $('btn-pause'), finish: $('btn-finish'), restart: $('btn-restart'),
    pauseIcon: $('pause-icon'), pauseText: $('pause-text'), status: $('status'), timer: $('timer'),
    rec: $('rec-badge'), readCount: $('read-count'), okCount: $('ok-count'), errCount: $('err-count'),
    wpm: $('live-wpm'), progress: $('progress'),
    bars: Array.from(document.querySelectorAll('#level-bars span')), form: $('submit-form'),
    uploading: $('uploading'), micError: $('mic-error'), micErrorText: $('mic-error-text'),
  };
  const csrf = ui.form.querySelector('[name=csrfmiddlewaretoken]').value;

  function warn(text) {
    if (text) $('support-warning-text').textContent = text;
    $('support-warning').classList.remove('hidden');
  }
  if (!window.isSecureContext) {
    warn('Микрофон тек https:// немесе http://127.0.0.1 / http://localhost мекенжайында жұмыс істейді. Сайтты осы мекенжайлардың бірімен ашыңыз.');
  } else if (!serverSpeech) {
    warn();
  }

  const normalize = w => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '').replace(/ё/g, 'е');
  const expected = words.map(normalize);

  let state = 'idle';            // idle | recording | paused | uploading | failed
  let stream, recorder, chunks = [], audioCtx, analyser, processor, levelTimer, sendTimer, watchdog;
  let elapsedMs = 0, startedAt = 0, tick;
  let heardText = '', sid = '', pending = [], sending = false, liveFailures = 0, liveBroken = false;
  let loudSeen = false;
  let status = [];               // per word: 'ok' | 'bad' | undefined
  let position = 0;              // index of the next expected word

  // ---------- passage font size
  let scale = 1;
  const passage = $('passage');
  function setScale(v) {
    scale = Math.min(1.4, Math.max(0.8, v));
    passage.style.fontSize = `${scale}em`;
    $('font-label').textContent = `${Math.round(scale * 100)}%`;
  }
  $('font-dec').addEventListener('click', () => setScale(scale - 0.1));
  $('font-inc').addEventListener('click', () => setScale(scale + 0.1));

  // ---------- comparing what was heard with the text
  function similar(a, b) {
    if (a === b) return true;
    if (!a || !b) return false;
    if (Math.abs(a.length - b.length) > 2) return false;
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
    }
    return d[a.length][b.length] <= Math.max(1, Math.floor(a.length / 5));
  }

  // Recomputed from scratch on every update, because the recogniser may revise its last words.
  function track() {
    const heard = heardText.split(/\s+/).map(normalize).filter(Boolean);
    const st = [];
    let pos = 0;
    for (let i = 0; i < heard.length && pos < expected.length; i++) {
      const h = heard[i];
      const last = i === heard.length - 1;   // may still be a half-spoken word
      // Re-reading a word after a mistake fixes it; repeating a correct word is ignored.
      if (pos > 0 && !similar(expected[pos], h) && similar(expected[pos - 1], h)) { st[pos - 1] = 'ok'; continue; }
      let found = -1;
      for (let k = pos; k < Math.min(pos + 4, expected.length); k++) {
        if (similar(expected[k], h)) { found = k; break; }
      }
      if (found >= 0) {
        for (let j = pos; j < found; j++) st[j] = 'bad';
        st[found] = 'ok';
        pos = found + 1;
      } else if (!last && similar(expected[pos], h + heard[i + 1])) {
        st[pos++] = 'ok'; i++;               // recogniser split one word in two
      } else if (!last) {
        st[pos++] = 'bad';
      }
    }
    status = st;
    position = pos;
    render();
    if (position >= expected.length && state === 'recording') {
      setStatus('done_all', 'Жарайсың! Мәтін аяқталды. Нәтиже дайындалуда…');
      setTimeout(finish, 1200);
    }
  }

  function render() {
    let ok = 0, bad = 0;
    spans.forEach((s, i) => {
      const st = status[i];
      if (st === 'ok') ok++; else if (st === 'bad') bad++;
      s.classList.toggle('bg-green-200', st === 'ok');
      s.classList.toggle('text-green-900', st === 'ok');
      s.classList.toggle('bg-yellow-200', st === 'bad');
      s.classList.toggle('text-yellow-900', st === 'bad');
      s.classList.toggle('ring-2', i === position && state !== 'idle');
      s.classList.toggle('ring-primary', i === position && state !== 'idle');
    });
    if (spans[position] && state === 'recording') {
      const r = spans[position].getBoundingClientRect();
      if (r.bottom > window.innerHeight - 40 || r.top < 80) spans[position].scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    ui.readCount.textContent = position;
    ui.okCount.textContent = ok;
    ui.errCount.textContent = bad;
    ui.progress.style.width = `${Math.round(100 * position / Math.max(1, expected.length))}%`;
    const minutes = currentMs() / 60000;
    ui.wpm.textContent = minutes > 0.1 && ok ? Math.round(ok / minutes) : '—';
  }

  function showHeard() {
    $('heard-box').classList.remove('hidden');
    const shown = heardText.replace(/\[unk\]/g, '?').trim();
    $('heard').textContent = shown ? shown.split(/\s+/).slice(-12).join(' ') : '…';
  }

  // ---------- timer
  const currentMs = () => elapsedMs + (state === 'recording' ? Date.now() - startedAt : 0);
  const clock = ms => { const t = Math.ceil(ms / 1000); return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };
  // Counts down the reading minute and stops the recording when it runs out.
  function showTime() {
    const left = Math.max(0, LIMIT_MS - currentMs());
    ui.timer.textContent = clock(left);
    ui.timer.classList.toggle('text-error', left <= 10000);
    $('time-bar').style.width = `${100 * left / LIMIT_MS}%`;
    $('time-bar').classList.toggle('bg-error', left <= 10000);
    render();
    if (left === 0 && state === 'recording') {
      setStatus('timer_off', 'Уақыт бітті! Нәтиже дайындалуда…');
      finish();
    }
  }

  // ---------- audio: level meter + 16 kHz PCM stream for live recognition
  function downsample(input, rate) {
    const ratio = rate / 16000;
    const out = new Int16Array(Math.floor(input.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const from = Math.floor(i * ratio), to = Math.min(input.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = from; j < to; j++) sum += input[j];
      const v = Math.max(-1, Math.min(1, sum / Math.max(1, to - from)));
      out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    return out;
  }

  function startAudio() {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      // Created after the permission prompt, so the browser may start it suspended.
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
      const source = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      levelTimer = setInterval(() => {
        analyser.getByteFrequencyData(data);
        if (state === 'recording' && Math.max(...data) > 90) loudSeen = true;
        ui.bars.forEach((bar, i) => {
          const v = state === 'recording' ? data[i * 2] / 255 : 0;
          bar.style.height = `${Math.max(4, Math.round(v * 32))}px`;
        });
      }, 100);
      if (serverSpeech) {
        processor = audioCtx.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = e => {
          if (state === 'recording' && !liveBroken) pending.push(downsample(e.inputBuffer.getChannelData(0), audioCtx.sampleRate));
        };
        source.connect(processor);
        processor.connect(audioCtx.destination);   // silent output; needed for processing to run
        sendTimer = setInterval(sendChunk, 700);
      }
    } catch (err) { console.warn(err); }
  }

  async function sendChunk(final) {
    if (sending || liveBroken || (!pending.length && !final)) return;
    const size = pending.reduce((n, a) => n + a.length, 0);
    const pcm = new Int16Array(size);
    let offset = 0;
    pending.forEach(a => { pcm.set(a, offset); offset += a.length; });
    pending = [];
    sending = true;
    const mySid = sid;
    try {
      const resp = await fetch(`${liveUrl}?sid=${mySid}${final ? '&final=1' : ''}`, {
        method: 'POST', body: pcm.buffer, keepalive: !!final,
        headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/octet-stream' },
      });
      if (!resp.ok) throw new Error(resp.status);
      const json = await resp.json();
      liveFailures = 0;
      if (mySid === sid && state === 'recording') {
        heardText = json.text || '';
        showHeard();
        track();
      }
    } catch (err) {
      console.warn('Live recognition failed:', err);
      if (++liveFailures >= 3) {
        liveBroken = true;
        warn('Сөздерді оқу кезінде белгілеу уақытша жұмыс істемей тұр. Оқуды жалғастыра бер — аяқтаған соң жүйе дауысыңды бәрібір таниды.');
      }
    } finally {
      sending = false;
    }
  }

  // If nothing has been recognised after a while, explain why instead of staying silent.
  function startWatchdog() {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => {
      if (state !== 'recording' || heardText.trim() || liveBroken) return;
      if (!loudSeen) {
        warn('Микрофоннан дыбыс келмей тұр. Дұрыс микрофон таңдалғанын тексеріңіз (Windows: Параметрлер → Жүйе → Дыбыс → Кіріс), дауыстап оқыңыз.');
      } else if (serverSpeech) {
        warn('Дауысың естіліп тұр, бірақ сөздер әлі танылмады. Микрофонға жақынырақ отырып, анық әрі қаттырақ оқы.');
      }
    }, 8000);
  }

  // ---------- controls
  function setStatus(icon, text) {
    ui.status.innerHTML = `<span class="material-symbols-outlined text-[20px]">${icon}</span>`;
    ui.status.append(text);
  }
  function show(el, on) { el.classList.toggle('hidden', !on); }
  const newSid = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : `s${Date.now()}${Math.random().toString(36).slice(2)}`);

  async function start() {
    ui.micError.classList.add('hidden');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      ui.micError.classList.remove('hidden');
      ui.micErrorText.textContent = 'Микрофон қолжетімсіз: сайтты http://127.0.0.1:8000 немесе https:// мекенжайымен ашыңыз.';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      ui.micError.classList.remove('hidden');
      if (err && err.name === 'NotFoundError') ui.micErrorText.textContent = 'Микрофон табылмады. Құрылғыны қосып, бетті жаңартыңыз.';
      else if (err && err.name === 'NotReadableError') ui.micErrorText.textContent = 'Микрофонды басқа бағдарлама (Zoom, Teams, т.б.) қолданып тұр. Оны жауып, қайта көріңіз.';
      return;
    }
    const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4'].find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    recorder.start(1000);
    state = 'recording';
    startedAt = Date.now();
    sid = newSid(); heardText = ''; pending = []; liveFailures = 0; liveBroken = false; loudSeen = false;
    tick = setInterval(showTime, 200);
    startAudio();
    startWatchdog();
    if (serverSpeech) showHeard();
    show(ui.start, false); show(ui.pause, true); show(ui.finish, true); show(ui.restart, true); show(ui.rec, true);
    setStatus('graphic_eq', 'Жазу жүріп жатыр — оқи бер!');
    render();
  }

  function togglePause() {
    if (state === 'recording') {
      elapsedMs = Math.min(LIMIT_MS, elapsedMs + Date.now() - startedAt);
      state = 'paused';
      recorder.pause();
      ui.pauseIcon.textContent = 'play_arrow'; ui.pauseText.textContent = 'Жалғастыру';
      show(ui.rec, false);
      setStatus('pause_circle', 'Кідіртілді. Дайын болсаң, жалғастыр.');
    } else if (state === 'paused') {
      state = 'recording';
      startedAt = Date.now();
      recorder.resume();
      startWatchdog();
      ui.pauseIcon.textContent = 'pause'; ui.pauseText.textContent = 'Кідірту';
      show(ui.rec, true);
      setStatus('graphic_eq', 'Жазу жүріп жатыр — оқи бер!');
    }
  }

  function releaseDevices() {
    clearInterval(tick); clearInterval(levelTimer); clearInterval(sendTimer); clearTimeout(watchdog);
    if (serverSpeech && sid && !liveBroken) { pending = []; sending = false; sendChunk(true); }   // frees the server recogniser
    if (processor) { processor.onaudioprocess = null; processor = null; }
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (audioCtx) audioCtx.close().catch(() => {});
  }

  function restart() {
    if (recorder && recorder.state !== 'inactive') { recorder.onstop = null; recorder.stop(); }
    releaseDevices();
    state = 'idle'; elapsedMs = 0; position = 0; status = []; heardText = ''; chunks = []; sid = '';
    $('heard-box').classList.add('hidden');
    show(ui.start, true); show(ui.pause, false); show(ui.finish, false); show(ui.restart, false); show(ui.rec, false);
    ui.pauseIcon.textContent = 'pause'; ui.pauseText.textContent = 'Кідірту';
    showTime();
    setStatus('mic', 'Дайын болсаң, «Оқуды бастау» батырмасын бас.');
    render();
  }

  function finish() {
    if (state !== 'recording' && state !== 'paused') return;
    if (state === 'recording') elapsedMs = Math.min(LIMIT_MS, elapsedMs + Date.now() - startedAt);
    state = 'uploading';
    ui.uploading.classList.remove('hidden');
    recorder.onstop = upload;
    recorder.stop();
    releaseDevices();
  }

  async function upload() {
    const data = new FormData(ui.form);
    const type = recorder.mimeType || 'audio/webm';
    const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
    data.append('audio', new Blob(chunks, { type }), `reading.${ext}`);
    data.append('transcript', heardText.trim());
    data.append('duration', (elapsedMs / 1000).toFixed(1));
    try {
      const resp = await fetch(ui.form.action, { method: 'POST', body: data, headers: { 'X-Requested-With': 'fetch' } });
      if (!resp.ok) throw new Error(resp.status);
      const json = await resp.json();
      window.location.href = json.redirect;
    } catch (err) {
      ui.uploading.classList.add('hidden');
      state = 'failed';
      setStatus('error', 'Жіберу сәтсіз аяқталды. Интернетті тексеріп, «Оқуды аяқтау» батырмасын қайта бас.');
      recorder.onstop = null;
      ui.finish.onclick = () => { state = 'uploading'; ui.uploading.classList.remove('hidden'); upload(); };
    }
  }

  ui.start.addEventListener('click', start);
  ui.pause.addEventListener('click', togglePause);
  ui.restart.addEventListener('click', restart);
  ui.finish.addEventListener('click', finish);
  window.addEventListener('beforeunload', e => { if (['recording', 'paused', 'failed'].includes(state)) e.preventDefault(); });
})();
