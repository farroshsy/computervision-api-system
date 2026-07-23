"""Single-file console at GET /demo — no build step, no dependencies.

A reviewer drags a document photo in and sees extraction + verification
live; a developer copies working curl/JS snippets for every endpoint.
Intentionally inline HTML/CSS/JS so it ships inside the same Docker
image and works the moment the container starts.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["demo"])

_PAGE = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Konsol — API Verifikasi Dokumen Kendaraan & Pengemudi</title>
<style>
  :root { --ok:#135f13; --okbg:#d3f5d3; --bad:#7c1010; --badbg:#fbd3d3; --warn:#7a5b00; --warnbg:#fdeec8; }
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin: 1.2rem 0 .4rem; }
  fieldset { border: 1px solid #ccc; border-radius: 10px; margin: 1rem 0; padding: 1rem; }
  legend { font-weight: 600; }
  label { display: block; margin: .5rem 0 .15rem; font-size: .9rem; }
  input, select { padding: .4rem; width: 100%; max-width: 340px; box-sizing: border-box; }
  button { margin-top: .8rem; padding: .5rem 1.2rem; font-size: 1rem; cursor: pointer; border-radius: 8px; border: 1px solid #888; background: #fff; }
  button:hover { background: #f0f0f0; }
  pre { background: #f6f6f6; border-radius: 8px; padding: 1rem; overflow-x: auto; font-size: .8rem; }
  table { border-collapse: collapse; width: 100%; margin: .6rem 0; }
  th, td { border: 1px solid #ddd; padding: .35rem .6rem; font-size: .85rem; text-align: left; }
  th { background: #f0f0f0; }
  td.v { font-family: Consolas, monospace; }
  .decision { font-size: 1.2rem; font-weight: 700; padding: .4rem 1rem; border-radius: 8px; display: inline-block; margin: .6rem 0; }
  .match, .GO { background: var(--okbg); color: var(--ok); }
  .no_match, .NO_GO { background: var(--badbg); color: var(--bad); }
  .needs_review, .REVIEW, .UNKNOWN { background: var(--warnbg); color: var(--warn); }
  .chip { display: inline-block; background: var(--warnbg); color: var(--warn); border-radius: 999px; padding: .15rem .7rem; margin: .15rem .2rem; font-size: .8rem; }
  .chip.okc { background: var(--okbg); color: var(--ok); }
  .chip.warnc { background: var(--warnbg); color: var(--warn); }
  .muted { color: #777; font-size: .85rem; }
  /* a requirement the customer asked for that we did NOT extract — the old
     table simply omitted the row, so an absence was invisible */
  tr.miss td { background: var(--warnbg); color: var(--warn); }
  .cols { display: flex; gap: 1rem; flex-wrap: wrap; }
  .cols > div { flex: 1 1 260px; }
  img.preview { max-width: 240px; max-height: 180px; border-radius: 8px; border: 1px solid #ccc; display: block; margin-top: .4rem; }
  /* the customer's spec draws a numbered box around each wanted field; the API
     now returns those boxes, so the console draws them back onto the photo */
  .shot { position: relative; display: inline-block; margin-top: .4rem; }
  .shot img.preview { margin-top: 0; }
  .shot svg.boxes { position: absolute; left: 0; top: 0; width: 100%; height: 100%; pointer-events: none; }
  .shot svg.boxes rect { fill: none; stroke: #e8b400; stroke-width: 2; vector-effect: non-scaling-stroke; }
  .shot svg.boxes text { fill: #111; font: 700 11px system-ui, sans-serif; paint-order: stroke; stroke: #e8b400; stroke-width: 6px; stroke-linejoin: round; }
  td.v .badge-inferred { background:#fff4d6; border:1px solid #e8b400; color:#7a5c00; font-size:.72rem; padding:0 .3rem; border-radius:4px; margin-left:.35rem; }
  /* gallery of the customer's own 42 documents */
  .tabs { display:flex; gap:.4rem; flex-wrap:wrap; margin:.4rem 0; }
  .tabs button { margin:0; padding:.3rem .8rem; font-size:.85rem; }
  .tabs button.on { background:#2d5fb8; color:#fff; border-color:#2d5fb8; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)); gap:.5rem; margin-top:.5rem; }
  .card { border:1px solid #ddd; border-radius:8px; padding:.25rem; cursor:pointer; background:#fff; text-align:center; }
  .card:hover { border-color:#2d5fb8; box-shadow:0 0 0 2px #dbe6fb; }
  .card.on { border-color:#2d5fb8; box-shadow:0 0 0 2px #2d5fb8; }
  .card img { width:100%; height:74px; object-fit:cover; border-radius:5px; display:block; background:#f2f2f2; }
  .card .cap { font-size:.62rem; color:#666; margin-top:.2rem; word-break:break-all; line-height:1.15; }
  .card .pdf { height:74px; display:flex; align-items:center; justify-content:center; color:#999; font-size:.75rem; background:#f2f2f2; border-radius:5px; }
  img.preview.big { max-width:100%; max-height:420px; }
  .viewmodes { display:flex; gap:.3rem; margin-bottom:.3rem; }
  .viewmodes button { margin:0; padding:.25rem .6rem; font-size:.78rem; }
  .viewmodes button.on { background:#e8b400; border-color:#c99b00; }
  /* the OCR's own view: every text line it detected */
  .shot svg.boxes rect.ocrline { stroke:#2d5fb8; stroke-width:1; opacity:.55; }
  /* pipeline stages */
  .stage { border:1px solid #ddd; border-left:4px solid #2d5fb8; border-radius:6px; padding:.45rem .6rem; margin:.4rem 0; }
  .stage h3 { margin:0 0 .15rem; font-size:.85rem; }
  .stage .n { font-family:Consolas,monospace; color:#111; }
  .stage.drop { border-left-color:#e8b400; background:#fffdf5; }
  .stage.final { border-left-color:#135f13; background:#f6fdf6; }
  .arrow { text-align:center; color:#bbb; font-size:.9rem; line-height:1; }
  details { margin-top: .6rem; }
  .bar { background: #eee; border-radius: 4px; height: 10px; }
  .bar > i { display: block; height: 10px; border-radius: 4px; background: #4a7edd; }
  .drop { border: 2px dashed #bbb; border-radius: 8px; padding: .45rem .6rem; }
  .drop.over { border-color: #2d5fb8; background: #eef3fc; }
  .drop .hint { display: block; color: #888; font-size: .78rem; margin-top: .2rem; }
</style>
</head>
<body>
<h1>API Verifikasi Dokumen — Konsol</h1>
<p class="muted">Foto diproses lalu dibuang; tidak ada data yang disimpan di server.
Referensi API lengkap: <a href="/docs">/docs</a> (Swagger) · <a href="/openapi.json">/openapi.json</a><br>
Foto BARU? Pakai <a href="/capture">ambil foto terpandu (/capture)</a> — bingkai kartu + gerbang kualitas untuk hasil terbaik.</p>

<fieldset>
  <legend>Bukti &amp; laporan terukur</legend>
  <p class="muted">
    <a href="/demo/evidence">Bukti sebelum/sesudah pada dokumen asli (28/28 pada foto bagus)</a> ·
    <a href="/demo/report">Laporan evaluasi penuh — 41 foto, 197 field</a> ·
    <a href="/demo/standard">Standar foto referensi (contoh + kriteria data baru)</a>
  </p>
</fieldset>

<fieldset>
  <legend>Kunci API</legend>
  <input id="apikey" placeholder="X-API-Key (kosongkan jika autentikasi nonaktif)">
</fieldset>

<fieldset>
  <legend>0 · Galeri — seluruh dokumen KYC pelanggan <span id="kyc_count" class="muted"></span></legend>
  <p class="muted">Klik satu dokumen: pipeline berjalan sungguhan, lalu setiap tahap ditampilkan —
    apa yang <b>dilihat</b> OCR, <b>di mana</b> tiap field ditemukan, apa yang <b>dibuang</b>, dan hasil akhirnya.
    Dokumen asli; tidak pernah meninggalkan mesin ini.</p>
  <div id="kyc_tabs" class="tabs"></div>
  <div id="kyc_grid" class="grid"></div>

  <div id="kyc_detail" hidden>
    <h2 id="kyc_title"></h2>
    <div class="cols">
      <div style="flex:1 1 380px">
        <div class="viewmodes">
          <button type="button" class="vm on" data-mode="fields" onclick="setMode('fields')">Kotak field (hasil)</button>
          <button type="button" class="vm" data-mode="ocr" onclick="setMode('ocr')">Yang dilihat OCR</button>
          <button type="button" class="vm" data-mode="none" onclick="setMode('none')">Foto asli</button>
        </div>
        <div class="shot" id="kyc_shot">
          <img id="kyc_img" class="preview big">
          <svg id="kyc_svg" class="boxes" viewBox="0 0 1 1" preserveAspectRatio="none"></svg>
        </div>
        <div id="kyc_legend" class="muted"></div>
      </div>
      <div style="flex:1 1 380px">
        <div id="kyc_pipe"></div>
      </div>
    </div>
    <div id="kyc_out"></div>
  </div>
</fieldset>

<fieldset>
  <legend>1 · Ekstraksi field (OCR)</legend>
  <div class="cols"><div>
    <label>Foto dokumen (JPG/PNG/WebP/PDF)</label><div class="drop" data-autorun="1"><input type="file" id="ex_file" accept="image/*,.pdf" onchange="preview(this,'ex_prev')"><span class="hint">atau seret &amp; letakkan foto ke sini — langsung diekstrak</span></div>
    <label>Jenis dokumen</label>
    <select id="ex_type"><option>AUTO</option><option>KTP</option><option>SIM</option><option>STNK</option><option>KIR</option></select>
    <button onclick="extract()">Ekstrak</button>
    <div id="ex_samples" class="muted" style="margin-top:.6rem"></div>
  </div><div><div class="shot"><img id="ex_prev" class="preview" hidden><svg id="ex_boxes" class="boxes" viewBox="0 0 1 1" preserveAspectRatio="none"></svg></div></div></div>
  <div id="ex_out"></div>
</fieldset>

<fieldset>
  <legend>2 · Verifikasi satu dokumen terhadap klaim</legend>
  <div class="cols"><div>
    <label>Foto dokumen</label><div class="drop"><input type="file" id="v_file" accept="image/*,.pdf" onchange="preview(this,'v_prev')"><span class="hint">atau seret &amp; letakkan foto ke sini</span></div>
    <label>Jenis dokumen</label>
    <select id="v_type"><option>SIM</option><option>KTP</option><option>STNK</option><option>KIR</option></select>
    <label>Nama yang diklaim</label><input id="v_name">
    <label>NIK yang diklaim (KTP)</label><input id="v_nik">
    <label>Nomor SIM yang diklaim</label><input id="v_sim">
    <label>Plat nomor yang diklaim (STNK/KIR)</label><input id="v_plate">
    <label>Golongan SIM yang disyaratkan (mis. BII,BII UMUM)</label><input id="v_classes">
    <button onclick="verify()">Verifikasi</button>
  </div><div><img id="v_prev" class="preview" hidden></div></div>
  <div id="v_out"></div>
</fieldset>

<fieldset>
  <legend>3 · Cek keberangkatan — bolehkah pengemudi ini membawa truk ini? (GO / NO_GO / REVIEW)</legend>
  <div class="cols"><div>
    <label>Foto SIM</label><div class="drop"><input type="file" id="t_sim" accept="image/*,.pdf"><span class="hint">seret foto SIM ke sini</span></div>
    <label>Foto STNK</label><div class="drop"><input type="file" id="t_stnk" accept="image/*,.pdf"><span class="hint">seret foto STNK ke sini</span></div>
    <label>Foto KIR</label><div class="drop"><input type="file" id="t_kir" accept="image/*,.pdf"><span class="hint">seret foto KIR ke sini</span></div>
  </div><div>
    <label>Nama pengemudi</label><input id="t_name">
    <label>Nomor SIM</label><input id="t_simno">
    <label>Plat truk yang ditugaskan</label><input id="t_plate">
    <label>Golongan SIM disyaratkan</label><input id="t_classes" placeholder="BII,BII UMUM">
  </div></div>
  <button onclick="trip()">Cek keberangkatan</button>
  <div id="t_out"></div>
</fieldset>

<fieldset>
  <legend>Untuk developer — integrasi copy-paste</legend>
  <p class="muted">Tiga panggilan yang sama dengan halaman ini. Resep lengkap di docs/API_COOKBOOK.md.</p>
<pre>
# Extract
curl -X POST http://HOST/api/v1/ocr/file -H "X-API-Key: KEY" \\
  -F "file=@document.jpg" -F "document_type=AUTO"

# Verify one document
curl -X POST http://HOST/api/v1/verify/document -H "X-API-Key: KEY" \\
  -F "file=@sim.jpg" -F "document_type=SIM" \\
  -F "claimed_name=BUDI SANTOSO" -F "claimed_sim_number=1427-8708-000059"

# Trip gate
curl -X POST http://HOST/api/v1/verify/trip -H "X-API-Key: KEY" \\
  -F "sim_file=@sim.jpg" -F "stnk_file=@stnk.jpg" -F "kir_file=@kir.jpg" \\
  -F "driver_name=BUDI SANTOSO" -F "plate=B 9437 SRU" -F "required_classes=BII"
</pre>
</fieldset>

<script>
const REASON_HELP = {
  resolution_too_low: 'resolusi foto di bawah minimum — minta foto ulang',
  grayscale_possible_photocopy: 'input abu-abu: kemungkinan fotokopi/scan, bukan kartu fisik — keputusan sesuai kebijakan',
  missing_card_header: 'kata kunci field ada tetapi kop resmi kartu tidak terbaca — kemungkinan replika ketikan',
  low_ocr_quality: 'teks terbaca dengan keyakinan rendah',
  very_low_text_content: 'hampir tidak ada teks pada foto',
  nik_pattern_not_found: 'NIK 16 digit tidak ditemukan',
  missing_ktp_markers: 'penanda KTP tidak ada',
  document_type_mismatch: 'foto adalah dokumen yang BERBEDA dari yang dideklarasikan — lihat detected_type, minta dokumen yang benar',
  wrong_document_type: 'foto berbeda dengan jenis dokumen pada slot pengiriman — minta ulang',
  blurry_image: 'foto buram — minta foto ulang',
  image_too_dark: 'foto terlalu gelap — minta foto ulang',
  nik_dob_mismatch: 'tanggal lahir pada NIK tidak cocok dengan tanggal tercetak',
  nik_gender_mismatch: 'konvensi +40 pada NIK tidak cocok dengan jenis kelamin tercetak',
};
function headers() {
  const k = document.getElementById('apikey').value.trim();
  return k ? {'X-API-Key': k} : {};
}
function preview(inp, imgId) {
  const img = document.getElementById(imgId);
  if (inp.files[0] && inp.files[0].type.startsWith('image/')) {
    img.src = URL.createObjectURL(inp.files[0]); img.hidden = false;
  } else { img.hidden = true; }
}
function chips(reasons) {
  if (!reasons || !reasons.length) return '<span class="chip okc">tanpa catatan validasi</span>';
  return reasons.map(r => `<span class="chip" title="${REASON_HELP[r] || ''}">${r}</span>`).join('');
}
// legacy alias keys duplicate their canonical twin — show the canonical
const ALIAS_OF = {plate_number: 'nomor_polisi', vin_chassis: 'nomor_rangka',
                  engine_number: 'nomor_mesin', owner_name: 'owner',
                  address: 'alamat', masa_berlaku: 'valid_until',
                  id_number: 'sim_number', valid_to: 'expiry_date'};
function fieldsTable(fields) {
  if (!fields || !Object.keys(fields).length) return '<p class="muted">tidak ada field terekstrak</p>';
  let rows = '';
  for (const [k, v] of Object.entries(fields)) {
    const twin = ALIAS_OF[k];
    if (twin && fields[twin] != null && fields[twin] !== '') continue;
    const val = (v && typeof v === 'object') ? v.value : v;
    const conf = (v && typeof v === 'object' && v.confidence != null) ? Number(v.confidence).toFixed(2) : '';
    const src = (v && typeof v === 'object' && v.provenance && v.provenance.method) ? v.provenance.method : '';
    if (val == null || val === '') continue;
    rows += `<tr><td>${k}</td><td class="v">${val}</td><td>${conf}</td><td class="muted">${src}</td></tr>`;
  }
  return `<table><tr><th>field</th><th>nilai</th><th>conf</th><th>sumber</th></tr>${rows}</table>`;
}
function scoreBars(scores) {
  if (!scores) return '';
  const max = Math.max(...Object.values(scores), 1);
  return Object.entries(scores).map(([t, s]) =>
    `<div style="display:flex;align-items:center;gap:.5rem;margin:.15rem 0">
       <span style="width:3.2rem">${t}</span>
       <div class="bar" style="flex:1"><i style="width:${Math.round(100 * s / max)}%"></i></div>
       <span class="muted">${s}</span></div>`).join('');
}
function checksTable(checks) {
  if (!checks || !checks.length) return '';
  const rows = checks.map(c =>
    `<tr><td>${c.field}</td><td class="v">${c.claimed ?? ''}</td><td class="v">${c.extracted ?? ''}</td>
     <td>${c.result ?? c.status ?? (c.match === true ? 'match' : c.match === false ? 'no_match' : '')}</td></tr>`).join('');
  return `<h2>Pemeriksaan</h2><table><tr><th>field</th><th>diklaim</th><th>terekstrak</th><th>hasil</th></tr>${rows}</table>`;
}
// What the CUSTOMER grades on (README.txt / the Logisly deck), and the keys we
// may satisfy each requirement with. The field table below can only show what
// WAS extracted — it renders no row for a field that came back empty, which is
// exactly how three missing KIR requirements went unnoticed. This panel shows
// the absences.
const SPEC = {
  KIR:  [['Title', ['title']],
         ['Nomor polisi', ['nomor_polisi','vehicle_id']],
         ['Lulus / tidak lulus', ['hasil_uji_normalized','hasil_uji']],
         ['Masa berlaku', ['masa_berlaku','valid_until']],
         ['Dimensi / kubikasi', ['dimensi','kubikasi']]],
  STNK: [['Title', ['title']],
         ['Nomor polisi', ['nomor_polisi']],
         ['Jenis kendaraan', ['model','brand','tipe']],
         ['Tahun pembuatan', ['year','tahun_pembuatan']],
         ['Jenis registrasi', ['jenis_registrasi','jenis']],
         ['Masa berlaku STNK', ['berlaku_sampai','tax_valid_to','masa_berlaku']],
         ['Masa berlaku pajak', ['tax_valid_to']]],
  SIM:  [['Title', ['title']],
         ['Tipe SIM', ['tipe_sim','class']],
         ['Nomor SIM', ['sim_number','id_number']],
         ['Masa berlaku', ['expiry_date','masa_berlaku']]],
  KTP:  [['NIK', ['nik']],
         ['Nama', ['nama','name']],
         ['Tanggal lahir', ['tanggal_lahir']],
         ['Jenis kelamin', ['jenis_kelamin']],
         // spec item 5 = the "PROVINSI …/KABUPATEN …" header, NOT the address:
         // the old row showed `alamat` and quietly passed for a field we never
         // extracted at all.
         ['Tempat registrasi', ['provinsi','kota']]],
};
// Draw the API's per-field boxes back onto the photo, numbered in spec order —
// the same picture the customer's own deck drew by hand.
function drawBoxes(svgId, docType, fields) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  svg.innerHTML = '';
  const spec = SPEC[docType];
  if (!spec || !fields) return;
  let n = 0;
  for (const [, keys] of spec) {
    n++;
    let bb = null;
    for (const k of keys) {
      const f = fields[k];
      if (f && typeof f === 'object' && f.bbox && f.bbox.norm) { bb = f.bbox.norm; break; }
    }
    if (!bb) continue;                       // no box for a value we could not locate
    const w = Math.max(0.001, bb.x1 - bb.x0), h = Math.max(0.001, bb.y1 - bb.y0);
    svg.insertAdjacentHTML('beforeend',
      `<rect x="${bb.x0}" y="${bb.y0}" width="${w}" height="${h}"></rect>`);
    // the label sits in pixel space, so it must not be squashed by the viewBox
    const px = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    px.setAttribute('x', bb.x0); px.setAttribute('y', Math.max(0.03, bb.y0 - 0.008));
    px.setAttribute('transform', `scale(1,1)`);
    px.setAttribute('style', 'font-size:0.045px');
    px.textContent = String(n);
    svg.appendChild(px);
  }
}
function specTable(docType, fields) {
  const spec = SPEC[docType];
  if (!spec) return '';
  fields = fields || {};
  let rows = '', got = 0;
  for (const [label, keys] of spec) {
    let val = null, via = '';
    for (const k of keys) {
      const f = fields[k];
      const v = (f && typeof f === 'object') ? f.value : f;
      if (v != null && v !== '') { val = v; via = k; break; }
    }
    if (val) got++;
    const rec = fields[via];
    const inferred = rec && typeof rec === 'object' && rec.provenance && rec.provenance.inferred;
    const badge = inferred ? ' <span class="badge-inferred">disimpulkan</span>' : '';
    rows += val
      ? `<tr><td>${label}</td><td class="v">${val}${badge}</td><td class="muted">${via}</td></tr>`
      : `<tr class="miss"><td>${label}</td><td class="v"><b>TIDAK TEREKSTRAK</b></td>`
        + `<td class="muted">perlu ditinjau manual</td></tr>`;
  }
  const pct = Math.round(100 * got / spec.length);
  const cls = got === spec.length ? 'okc' : 'warnc';
  return `<h2>Kelengkapan sesuai permintaan customer `
    + `<span class="chip ${cls}">${got}/${spec.length} (${pct}%)</span></h2>`
    + `<table><tr><th>diminta customer</th><th>nilai</th><th>dari field</th></tr>${rows}</table>`;
}
function docBlock(body) {
  const d = body.data || body;              // /ocr/file nests under data
  const validation = d.validation || body.validation || {};
  const det = (body.meta && body.meta.detection) || null;
  return (body.document_type ? `<h2>Terdeteksi: ${body.document_type}</h2>` : '') +
    (det && det.scores ? scoreBars(det.scores) : '') +
    ((validation.reasons !== undefined || d.validation) ? `<h2>Validasi</h2>` + chips(validation.reasons) : '') +
    specTable(body.document_type, d.fields || body.extracted) +
    `<h2>Semua field terekstrak</h2>` + fieldsTable(d.fields || body.extracted) +
    checksTable(body.checks);
}
function render(el, body, decisionKey) {
  const decision = decisionKey ? body[decisionKey] : null;
  let inner = decision ? `<div class="decision ${decision}">${String(decision).toUpperCase()}</div>` : '';
  if (body.documents) {                      // /verify/trip, and MULTI wallet photos
    for (const [key, doc] of Object.entries(body.documents)) {
      // /verify/trip keys by name; /ocr/file MULTI is an ARRAY, so key is "0"/"1"
      // — use the sub-document's own type rather than showing "— 0".
      const name = doc.document_type || key;
      inner += `<h2>— ${name} ${doc.decision ? `<span class="decision ${doc.decision}" style="font-size:.9rem">${doc.decision}</span>` : ''}</h2>` + docBlock(doc);
    }
  } else {
    inner += docBlock(body);
  }
  el.innerHTML = inner +
    `<details><summary>JSON mentah</summary><pre>${JSON.stringify(body, null, 2)}</pre></details>`;
}
let BUSY = false;
async function post(url, fd) {
  BUSY = true;
  try {
    const r = await fetch(url, {method: 'POST', body: fd, headers: headers()});
    return await r.json();
  } finally { BUSY = false; }
}
function guard() {
  if (BUSY) { alert('Masih memproses dokumen sebelumnya — tunggu sebentar.'); return true; }
  return false;
}
async function loadSamples() {
  try {
    const r = await fetch('/demo/samples');
    const b = await r.json();
    if (!b.samples || !b.samples.length) return;
    const el = document.getElementById('ex_samples');
    el.innerHTML = 'Uji cepat — dokumen asli, dijalankan LANGSUNG lewat API yang sama: ' +
      b.samples.map(n => `<button type="button" onclick="runSample('${n}')">${n}</button>`).join(' ');
  } catch (e) {}
}
async function runSample(name) {
  if (guard()) return;
  const out = document.getElementById('ex_out');
  out.innerHTML = '<p class="muted">Mengambil foto & menjalankan OCR + verifikasi… (proses nyata, bukan rekaman)</p>';
  const blob = await (await fetch('/demo/samples/' + encodeURIComponent(name))).blob();
  const img = document.getElementById('ex_prev');
  img.src = URL.createObjectURL(blob); img.hidden = false;
  const fd = new FormData();
  fd.append('file', new File([blob], name, {type: blob.type || 'image/jpeg'}));
  fd.append('document_type', 'AUTO');
  const res = await post('/api/v1/ocr/file', fd);
  render(out, res, null);
  drawBoxes('ex_boxes', res.document_type, (res.data || {}).fields);
}
loadSamples();

// ---------------------------------------------------------------- galeri KYC
// The customer's own 42 documents, and — for each one — the pipeline laid open:
// what OCR saw, where each field was found, what was thrown away, what shipped.
let KYC = {}, KYC_TYPE = null, LAST = null, MODE = 'fields';

async function loadKyc() {
  try {
    const b = await (await fetch('/demo/kyc')).json();
    KYC = b.groups || {};
    const types = Object.keys(KYC);
    if (!types.length) return;
    document.getElementById('kyc_count').textContent = `— ${b.total} dokumen asli`;
    document.getElementById('kyc_tabs').innerHTML = types.map(t =>
      `<button type="button" class="tab" data-t="${t}" onclick="showType('${t}')">${t} (${KYC[t].length})</button>`).join('');
    showType(types[0]);
  } catch (e) {}
}
function showType(t) {
  KYC_TYPE = t;
  document.querySelectorAll('#kyc_tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
  document.getElementById('kyc_grid').innerHTML = KYC[t].map(f => {
    const src = `/demo/kyc/${encodeURIComponent(f.folder)}/${encodeURIComponent(f.name)}`;
    const isPdf = f.name.toLowerCase().endsWith('.pdf');
    const thumb = isPdf ? `<div class="pdf">PDF</div>` : `<img loading="lazy" src="${src}" alt="">`;
    return `<div class="card" data-n="${f.name}" onclick="runKyc('${f.folder}','${f.name}',this)">
              ${thumb}<div class="cap">${f.name}</div></div>`;
  }).join('');
}
async function runKyc(folder, name, card) {
  if (guard()) return;
  document.querySelectorAll('.card').forEach(c => c.classList.remove('on'));
  if (card) card.classList.add('on');
  const src = `/demo/kyc/${encodeURIComponent(folder)}/${encodeURIComponent(name)}`;
  const detail = document.getElementById('kyc_detail');
  detail.hidden = false;
  document.getElementById('kyc_title').textContent = name;
  document.getElementById('kyc_img').src = src;
  document.getElementById('kyc_svg').innerHTML = '';
  document.getElementById('kyc_pipe').innerHTML = '<p class="muted">Menjalankan pipeline sungguhan di server… (OCR CPU: 5–120 detik)</p>';
  document.getElementById('kyc_out').innerHTML = '';
  const blob = await (await fetch(src)).blob();
  const fd = new FormData();
  fd.append('file', new File([blob], name, {type: blob.type || 'image/jpeg'}));
  fd.append('document_type', 'AUTO');
  const res = await post('/api/v1/ocr/file', fd);
  LAST = res;
  renderPipeline(res);
  render(document.getElementById('kyc_out'), res, null);
  setMode(MODE);
}
function setMode(m) {
  MODE = m;
  document.querySelectorAll('.viewmodes button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  const svg = document.getElementById('kyc_svg');
  const legend = document.getElementById('kyc_legend');
  svg.innerHTML = '';
  if (!LAST) return;
  const trace = (LAST.meta || {}).trace || {};
  if (m === 'ocr') {
    // every text line the OCR detected — this is the raw material, before any
    // field logic runs at all
    const its = (trace.ocr || {}).items || [];
    for (const it of its) {
      if (!it.norm) continue;
      svg.insertAdjacentHTML('beforeend',
        `<rect class="ocrline" x="${it.norm.x0}" y="${it.norm.y0}" width="${Math.max(0.001, it.norm.x1 - it.norm.x0)}" height="${Math.max(0.001, it.norm.y1 - it.norm.y0)}"></rect>`);
    }
    legend.textContent = `${its.length} baris teks terdeteksi oleh OCR — belum ada makna, baru piksel jadi teks.`;
  } else if (m === 'fields') {
    drawBoxes('kyc_svg', LAST.document_type, (LAST.data || {}).fields);
    const spec = SPEC[LAST.document_type] || [];
    legend.innerHTML = spec.map((s, i) => `${i + 1}. ${s[0]}`).join(' · ') +
      '<br>Kotak bernomor = field yang diminta pelanggan, persis seperti di dek mereka.';
  } else {
    legend.textContent = 'Foto asli, tanpa anotasi.';
  }
}
// The pipeline, stage by stage, with the real numbers from THIS document.
function renderPipeline(res) {
  const trace = (res.meta || {}).trace || {};
  const det = (res.meta || {}).detection || {};
  const ocr = trace.ocr || {};
  const stages = trace.fields_by_stage || {};
  const dropped = trace.dropped || [];
  const fields = (res.data || {}).fields || {};
  const nf = Object.keys(fields).length;
  const arrow = '<div class="arrow">▼</div>';

  const stageNames = {
    rule_extractor: 'Ekstraktor aturan (label : nilai)',
    spatial_pairing: 'Geometri — pasangkan label dengan nilai di sebelahnya',
    field_detector: 'Detektor terlatih (YOLO) — potong kotak field lalu OCR ulang',
    nik_embedded_dob: 'Turunan dari NIK (tanggal lahir)',
    nik_embedded_sex: 'Turunan dari NIK (jenis kelamin)',
    inferred_from_validity: 'Disimpulkan dari sertifikat yang masih berlaku',
    alias: 'Alias (salinan field kanonik)',
  };
  const stageRows = Object.entries(stages).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<tr><td>${stageNames[k] || k}</td><td class="v">${v}</td></tr>`).join('');

  const dropRows = dropped.map(d =>
    `<tr><td class="v">${d.field}</td><td class="v">${d.value}</td><td>${d.reason}</td></tr>`).join('');

  document.getElementById('kyc_pipe').innerHTML =
    `<div class="stage"><h3>1 · OCR — piksel jadi teks</h3>
       <span class="n">${ocr.lines || 0}</span> baris teks · <span class="n">${ocr.seconds || '?'}</span> detik (CPU)
       <div class="muted">Foto asli dipakai apa adanya; pra-proses agresif justru merusak foto nyata.</div></div>` + arrow +
    `<div class="stage"><h3>2 · Deteksi jenis dokumen</h3>
       <span class="n">${res.document_type}</span>
       ${det.scores ? scoreBars(det.scores) : ''}</div>` + arrow +
    `<div class="stage"><h3>3 · Menemukan field — dari tahap mana nilainya datang</h3>
       <table><tr><th>Tahap</th><th>Field</th></tr>${stageRows || '<tr><td colspan="2" class="muted">—</td></tr>'}</table></div>` + arrow +
    `<div class="stage drop"><h3>4 · Validasi — yang dibuang, bukan ditebak</h3>
       ${dropped.length
         ? `<table><tr><th>Field</th><th>Nilai terbaca</th><th>Alasan dibuang</th></tr>${dropRows}</table>
            <div class="muted">Nilai ini <b>terbaca</b>, lalu <b>ditolak</b>. Field jadi <b>needs_review</b> —
            manusia memeriksanya. Nilai salah yang terlanjur dikirim tidak pernah diperiksa siapa pun.</div>`
         : '<span class="muted">Tidak ada nilai yang perlu dibuang pada dokumen ini.</span>'}</div>` + arrow +
    `<div class="stage final"><h3>5 · Hasil</h3>
       <span class="n">${nf}</span> field terekstrak · <span class="n">${Object.values(fields).filter(f => f && f.bbox).length}</span> punya kotak lokasi
       <div class="muted">Setiap nilai membawa <code>bbox</code> (di mana ia dibaca) dan <code>provenance</code> (tahap mana yang menghasilkannya).</div></div>`;
}
loadKyc();
// seret & letakkan: setiap zona .drop mengisi input file di dalamnya;
// zona ekstraksi langsung menjalankan prosesnya
document.querySelectorAll('.drop').forEach(zone => {
  const input = zone.querySelector('input[type=file]');
  ['dragenter', 'dragover'].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove('over'); }));
  zone.addEventListener('drop', e => {
    if (!e.dataTransfer.files.length) return;
    input.files = e.dataTransfer.files;
    input.dispatchEvent(new Event('change'));
    if (zone.dataset.autorun) extract();
  });
});
// jangan biarkan browser membuka berkas bila meleset dari zona
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => e.preventDefault());
async function extract() {
  if (guard()) return;
  const f = document.getElementById('ex_file').files[0];
  if (!f) return alert('Pilih foto dulu');
  document.getElementById('ex_out').innerHTML =
    '<p class="muted">Menjalankan OCR + ekstraksi… (proses nyata di server)</p>';
  const fd = new FormData();
  fd.append('file', f);
  fd.append('document_type', document.getElementById('ex_type').value);
  const res = await post('/api/v1/ocr/file', fd);
  render(document.getElementById('ex_out'), res, null);
  drawBoxes('ex_boxes', res.document_type, (res.data || {}).fields);
}
async function verify() {
  if (guard()) return;
  const f = document.getElementById('v_file').files[0];
  if (!f) return alert('Pilih foto dulu');
  const fd = new FormData();
  fd.append('file', f);
  fd.append('document_type', document.getElementById('v_type').value);
  const pairs = [['claimed_name','v_name'],['claimed_nik','v_nik'],['claimed_sim_number','v_sim'],
                 ['claimed_plate','v_plate'],['required_classes','v_classes']];
  for (const [k, id] of pairs) { const v = document.getElementById(id).value; if (v) fd.append(k, v); }
  render(document.getElementById('v_out'), await post('/api/v1/verify/document', fd), 'decision');
}
async function trip() {
  if (guard()) return;
  const fd = new FormData();
  const files = [['sim_file','t_sim'],['stnk_file','t_stnk'],['kir_file','t_kir']];
  let any = false;
  for (const [k, id] of files) { const f = document.getElementById(id).files[0]; if (f) { fd.append(k, f); any = true; } }
  if (!any) return alert('Pilih minimal satu foto dokumen');
  const pairs = [['driver_name','t_name'],['sim_number','t_simno'],['plate','t_plate'],['required_classes','t_classes']];
  for (const [k, id] of pairs) { const v = document.getElementById(id).value; if (v) fd.append(k, v); }
  render(document.getElementById('t_out'), await post('/api/v1/verify/trip', fd), 'decision');
}
</script>
</body>
</html>"""


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
async def demo_page() -> str:
    return _PAGE


_MISSING_PAGE = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Belum ada berkas</title></head>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto">
<h1>Berkas belum tersedia</h1>
<p>Halaman ini dilayani dari folder <code>evidence/</code> yang di-mount
saat runtime (berisi dokumen asli = data pribadi, sehingga TIDAK pernah
ikut dalam image Docker maupun repositori).</p>
<p>Cara mengisinya: jalankan
<code>python scripts/eval_before_after.py --labels &lt;folder-data&gt;</code>
dan/atau <code>python scripts/eval_real_docs.py --labels &lt;folder-data&gt;</code>
— keduanya menyalin HTML hasilnya ke <code>evidence/</code> secara
otomatis. Untuk Docker: letakkan berkas pada folder <code>./evidence</code>
di samping <code>docker-compose.yml</code>.</p>
<p><a href="/demo">&larr; kembali ke konsol</a></p></body></html>"""


def _serve_evidence_file(filename: str) -> HTMLResponse:
    from pathlib import Path

    from app.config import settings
    base = Path(getattr(settings, "EVIDENCE_DIR", "evidence"))
    path = base / filename
    if not path.is_file():
        return HTMLResponse(_MISSING_PAGE, status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/demo/evidence", response_class=HTMLResponse, include_in_schema=False)
async def evidence_page() -> HTMLResponse:
    """Bukti sebelum/sesudah pada dokumen asli (dari folder runtime)."""
    return _serve_evidence_file("evidence_before_after.html")


@router.get("/demo/report", response_class=HTMLResponse, include_in_schema=False)
async def eval_report_page() -> HTMLResponse:
    """Laporan evaluasi penuh 41 foto (dari folder runtime)."""
    return _serve_evidence_file("eval_report.html")


@router.get("/demo/standard", response_class=HTMLResponse, include_in_schema=False)
async def reference_standard_page() -> HTMLResponse:
    """Standar foto referensi — 4 contoh + kriteria (dari folder runtime)."""
    return _serve_evidence_file("reference_standard.html")


def _samples_dir():
    from pathlib import Path

    from app.config import settings
    return Path(getattr(settings, "EVIDENCE_DIR", "evidence")) / "samples"


@router.get("/demo/samples", include_in_schema=False)
async def list_samples() -> dict:
    """Contoh dokumen (mount runtime) untuk uji satu klik di konsol."""
    base = _samples_dir()
    names = []
    if base.is_dir():
        names = sorted(p.name for p in base.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    return {"samples": names}


def _kyc_dir():
    """The customer's own 42-document set, mounted read-only at runtime."""
    from pathlib import Path
    for base in (Path("/app/evidence/samples/Customer KYC"),
                 Path("evidence/samples/Customer KYC")):
        if base.is_dir():
            return base
    return None


@router.get("/demo/kyc", include_in_schema=False)
async def list_kyc() -> dict:
    """Every document in the customer's KYC set, grouped by type.

    These are REAL identity documents. They are mounted read-only, served only
    to this machine's own browser, and never leave it.
    """
    base = _kyc_dir()
    groups: dict = {}
    if base:
        # folder name on disk -> the type the API reports
        folders = {"ID": "KTP", "Driver License": "SIM", "STNK": "STNK", "KIR": "KIR"}
        for folder, doc_type in folders.items():
            d = base / folder
            if not d.is_dir():
                continue
            files = sorted(p.name for p in d.iterdir()
                           if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".pdf"))
            if files:
                groups[doc_type] = [{"folder": folder, "name": n} for n in files]
    total = sum(len(v) for v in groups.values())
    return {"groups": groups, "total": total}


@router.get("/demo/kyc/{folder}/{name}", include_in_schema=False)
async def get_kyc(folder: str, name: str):
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    base = _kyc_dir()
    if base is None:
        raise HTTPException(status_code=404, detail="kyc set not mounted")
    # no traversal: both parts must be plain names, and the result must still
    # sit inside the mounted set
    if Path(folder).name != folder or Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid path")
    path = (base / folder / name).resolve()
    if not str(path).startswith(str(base.resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)


@router.get("/demo/samples/{name}", include_in_schema=False)
async def get_sample(name: str):
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="invalid name")
    path = _samples_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="sample not found")
    return FileResponse(path)
