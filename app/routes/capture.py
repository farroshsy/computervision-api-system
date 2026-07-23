"""Guided capture at GET /capture — the bank-style "align the card in the box"
flow, so a FUTURE photo arrives structured and high-quality.

The old-archive path (/demo) stays: it evaluates whatever photo already exists.
This page is the other end — capture done RIGHT, so every text block lands in a
known place at good resolution and the OCR has the easiest possible job. It runs
the SAME public /api/v1/ocr/file endpoint, so nothing downstream changes.

Single inline file (no build step); ships inside the same Docker image.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["capture"])

# Aspect ratio (width/height) of the guide frame per document type.
# KTP/SIM are ID-1 cards (85.6 x 53.98 mm -> 1.586). STNK is a larger card,
# KIR is a portrait sheet. The frame shape teaches the user how to hold it.
_ASPECTS = {"KTP": 1.586, "SIM": 1.586, "STNK": 1.42, "KIR": 0.71}

_PAGE = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ambil Foto Terpandu — Verifikasi Dokumen</title>
<style>
  :root { --ok:#135f13; --okbg:#d3f5d3; --bad:#7c1010; --warn:#7a5b00; --warnbg:#fdeec8; }
  body { font-family: system-ui, sans-serif; margin: 0 auto; max-width: 640px; padding: 1rem; color: #222; }
  h1 { font-size: 1.25rem; } .muted { color: #777; font-size: .85rem; }
  select, button { font-size: 1rem; padding: .5rem .8rem; border-radius: 8px; border: 1px solid #888; }
  button { background: #2d5fb8; color: #fff; border: none; cursor: pointer; }
  button.ghost { background: #fff; color: #2d5fb8; border: 1px solid #2d5fb8; }
  button:disabled { opacity: .5; cursor: default; }
  .stage { position: relative; background: #000; border-radius: 12px; overflow: hidden; margin: .8rem 0; }
  video, canvas { display: block; width: 100%; }
  .frame { position: absolute; inset: 0; pointer-events: none; }
  .frame svg { width: 100%; height: 100%; }
  .hint { text-align: center; font-size: .95rem; padding: .5rem; border-radius: 8px; margin: .4rem 0; }
  .hint.good { background: var(--okbg); color: var(--ok); }
  .hint.warn { background: var(--warnbg); color: var(--warn); }
  .row { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
  table { border-collapse: collapse; width: 100%; margin: .6rem 0; }
  th, td { border: 1px solid #ddd; padding: .35rem .6rem; font-size: .85rem; text-align: left; }
  th { background: #f0f0f0; } td.v { font-family: Consolas, monospace; }
  .chip { display:inline-block; background:var(--warnbg); color:var(--warn); border-radius:999px; padding:.15rem .7rem; margin:.15rem .2rem; font-size:.8rem; }
</style></head><body>
<h1>Ambil Foto Terpandu</h1>
<p class="muted">Posisikan dokumen memenuhi bingkai, rata, terang, tanpa silau.
Foto di-crop ke bingkai lalu dibaca lewat API yang sama dengan sistem.
Untuk foto lama/tak berstruktur, gunakan <a href="/demo">/demo</a>.</p>

<div class="row">
  <label>Jenis dokumen
    <select id="doctype">
      <option value="KTP">KTP</option><option value="SIM">SIM</option>
      <option value="STNK">STNK</option><option value="KIR">KIR</option>
    </select>
  </label>
  <button id="startbtn" class="ghost">Nyalakan kamera</button>
</div>

<div class="stage">
  <video id="video" playsinline muted></video>
  <div class="frame" id="frame"></div>
</div>

<div class="hint warn" id="hint">Nyalakan kamera untuk mulai.</div>
<div class="row">
  <button id="shootbtn" disabled>Ambil &amp; Baca</button>
  <label class="ghost" style="padding:.5rem .8rem;border:1px solid #2d5fb8;border-radius:8px;cursor:pointer">
    atau pilih berkas <input type="file" id="filein" accept="image/*,.pdf" hidden>
  </label>
</div>
<div id="out"></div>

<script>
// consume the API — the same geometry any integrator gets from
// GET /api/v1/capture/template (falls back to sane defaults offline)
let ASPECTS = {KTP:1.586, SIM:1.586, STNK:1.42, KIR:0.71};
fetch('/api/v1/capture/template').then(r=>r.json()).then(t=>{
  const m={}; for(const [k,v] of Object.entries(t.doc_types||{})) m[k]=v.frame_aspect_ratio;
  if(Object.keys(m).length){ ASPECTS=m; FRAME=drawFrame(); }
}).catch(()=>{});
let stream = null;
const video = document.getElementById('video');
const hint = document.getElementById('hint');

function drawFrame() {
  const dt = document.getElementById('doctype').value;
  const a = ASPECTS[dt] || 1.586;
  // frame occupies 88% of the shorter axis, centered, at the doc aspect
  const vw = 100, vh = 100; // percentage viewBox
  let fw, fh;
  if (a >= 1) { fw = 88; fh = fw / a; } else { fh = 88; fw = fh * a; }
  const x = (vw - fw) / 2, y = (vh - fh) / 2;
  document.getElementById('frame').innerHTML =
    `<svg viewBox="0 0 100 100" preserveAspectRatio="none">
       <path d="M0 0H100V100H0Z M${x} ${y}H${x+fw}V${y+fh}H${x}Z" fill="rgba(0,0,0,.45)" fill-rule="evenodd"/>
       <rect x="${x}" y="${y}" width="${fw}" height="${fh}" fill="none" stroke="#4ad07a" stroke-width=".6" rx="2"/>
     </svg>`;
  return {x, y, fw, fh};
}
let FRAME = drawFrame();
document.getElementById('doctype').addEventListener('change', () => { FRAME = drawFrame(); });

document.getElementById('startbtn').onclick = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}}});
    video.srcObject = stream; await video.play();
    document.getElementById('shootbtn').disabled = false;
    hint.className = 'hint good'; hint.textContent = 'Isi bingkai dengan dokumen, rata & terang.';
    setInterval(checkQuality, 700);
  } catch (e) {
    hint.className = 'hint warn';
    hint.textContent = 'Kamera tak tersedia — pakai "pilih berkas" atau /demo.';
  }
};

// Rough live quality read on the framed region: too dark / low detail.
const probe = document.createElement('canvas');
function checkQuality() {
  if (!video.videoWidth) return;
  const g = probe.getContext('2d');
  probe.width = 64; probe.height = 64;
  g.drawImage(video, 0, 0, 64, 64);
  const d = g.getImageData(0, 0, 64, 64).data;
  let sum = 0, sq = 0, n = 64 * 64;
  for (let i = 0; i < d.length; i += 4) { const v = (d[i]+d[i+1]+d[i+2])/3; sum += v; sq += v*v; }
  const mean = sum / n, varr = sq / n - mean * mean;
  if (mean < 55) setHint('warn', 'Terlalu gelap — cari cahaya lebih terang.');
  else if (varr < 180) setHint('warn', 'Kurang tajam / silau — jauhkan pantulan, fokuskan.');
  else setHint('good', 'Bagus — tekan Ambil & Baca.');
}
function setHint(cls, msg) { hint.className = 'hint ' + cls; hint.textContent = msg; }

document.getElementById('shootbtn').onclick = () => {
  const vw = video.videoWidth, vh = video.videoHeight;
  // crop to the on-screen frame rectangle (percent -> pixels)
  const sx = FRAME.x/100*vw, sy = FRAME.y/100*vh, sw = FRAME.fw/100*vw, sh = FRAME.fh/100*vh;
  const c = document.createElement('canvas'); c.width = sw; c.height = sh;
  c.getContext('2d').drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
  c.toBlob(b => send(b, 'capture.jpg'), 'image/jpeg', 0.92);
};
document.getElementById('filein').onchange = e => { if (e.target.files[0]) send(e.target.files[0], e.target.files[0].name); };

async function send(blob, name) {
  document.getElementById('out').innerHTML = '<p class="muted">Membaca dokumen…</p>';
  const fd = new FormData();
  fd.append('file', new File([blob], name, {type: blob.type || 'image/jpeg'}));
  fd.append('document_type', document.getElementById('doctype').value);
  const r = await fetch('/api/v1/ocr/file', {method: 'POST', body: fd});
  render(await r.json());
}

function render(body) {
  const d = body.data || body;
  const fields = d.fields || {};
  const reasons = (d.validation || {}).reasons || [];
  let rows = '';
  for (const [k, v] of Object.entries(fields)) {
    const val = (v && typeof v === 'object') ? v.value : v;
    if (val == null || val === '') continue;
    rows += `<tr><td>${k}</td><td class="v">${val}</td></tr>`;
  }
  document.getElementById('out').innerHTML =
    `<h2>Terdeteksi: ${body.document_type || '-'}</h2>` +
    (reasons.length ? reasons.map(r => `<span class="chip">${r}</span>`).join('') : '') +
    (rows ? `<table><tr><th>field</th><th>nilai</th></tr>${rows}</table>`
          : '<p class="muted">tidak ada field terbaca — coba foto ulang lebih terang & rata</p>');
}
</script></body></html>"""


@router.get("/capture", response_class=HTMLResponse, include_in_schema=False)
async def capture_page() -> str:
    return _PAGE
