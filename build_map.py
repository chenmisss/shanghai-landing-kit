#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build self-contained AMap JSAPI v2.0 map page: 公租房 commute explorer.
Preset mode = 莘庄 full precomputed data; custom mode = any destination
(straight-line instant + progressive real transit/driving via JSAPI plugins)."""
import csv, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "map.html")
CFG_PATH = os.path.join(BASE, "config.json")
if not os.path.exists(CFG_PATH):
    sys.exit("[错误] 没找到 config.json,请先按 README 第一二步配置。")
CFG = json.load(open(CFG_PATH, encoding="utf-8"))
JS_KEY = (CFG.get("amap_js_key") or "").strip()
SEC = (CFG.get("amap_js_security_code") or "").strip()
CITY = (CFG.get("city") or "上海").strip()
if not JS_KEY or "粘贴" in JS_KEY or not SEC or "粘贴" in SEC:
    sys.exit("[错误] config.json 里的 amap_js_key / amap_js_security_code 还没填(要【Web端 JS API】类型 Key 及其安全密钥)。")
CACHE_PATH = os.path.join(BASE, "enrich_cache.json")
if not os.path.exists(CACHE_PATH):
    sys.exit("[错误] 没找到 enrich_cache.json,请先运行 python enrich.py。")
cache = json.load(open(CACHE_PATH, encoding="utf-8"))
dest = cache.get("dest") or {}
if not dest.get("loc"):
    sys.exit("[错误] 缓存里没有目的地,请先运行 python enrich.py。")
DEST_LON, DEST_LAT = dest["loc"].split(",")
DEST_NAME = dest.get("name", "目的地")
geo, drv, tr, mt = cache.get("geo", {}), cache.get("drive", {}), cache.get("transit", {}), cache.get("metro", {})

recs = []
with open(os.path.join(BASE, "listings.csv"), encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f)):
        name = (row.get("项目名称") or "").strip()
        addr = (row.get("地址") or "").strip()
        if name and addr:
            recs.append({"_id": f"r{i}", "n": name, "d": (row.get("区域") or "").strip(), "a": addr,
                         "hx": (row.get("户型") or "").strip(), "ph": (row.get("联系电话") or "").strip(),
                         "rl": row.get("最低租金"), "rh": row.get("最高租金"),
                         "al": row.get("最小面积"), "ah": row.get("最大面积")})

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

rows = []
for r in recs:
    g = geo.get(r["a"]) or {}
    if not g.get("loc"):
        continue
    d = drv.get(r["_id"]) or {}
    t = tr.get(r["_id"]) or None
    m = mt.get(r["_id"]) or None
    lon, lat = map(float, g["loc"].split(","))
    rows.append({
        "n": r["n"], "d": r["d"], "a": r["a"], "hx": r["hx"], "ph": r["ph"],
        "rl": num(r["rl"]), "rh": num(r["rh"]), "al": num(r["al"]), "ah": num(r["ah"]),
        "lon": lon, "lat": lat,
        "dk": d.get("km"), "dm": d.get("min"),
        "tm": t.get("min") if t else None, "tw": t.get("walk_m") if t else None,
        "tl": (t.get("lines") or "") if t else "",
        "mn": (m.get("name") or "") if m else "", "md": m.get("dist_m") if m else None,
        "ml": (m.get("lines") or "") if m else "",
    })

data_js = json.dumps(rows, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>公租房通勤地图</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { height:100%; font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
  #app { display:flex; flex-direction:column; height:100%; }
  header { padding:8px 16px; background:#fff; border-bottom:1px solid #e8e6e0; display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; z-index:10; box-shadow:0 1px 6px rgba(0,0,0,.06); }
  header h1 { font-size:16px; color:#0b0b0b; }
  header h1 #destName { color:#d03b3b; }
  .seg { display:flex; border:1px solid #d5d3cb; border-radius:8px; overflow:hidden; }
  .seg button { border:0; background:#fff; padding:6px 14px; font-size:13px; cursor:pointer; color:#52514e; }
  .seg button.on { background:#0d366b; color:#fff; }
  .seg.disabled { opacity:.35; pointer-events:none; }
  .chips { display:flex; gap:6px; flex-wrap:wrap; }
  .chip { display:flex; align-items:center; gap:6px; font-size:12px; color:#0b0b0b; border:1px solid #d5d3cb; border-radius:20px; padding:4px 10px; cursor:pointer; background:#fff; user-select:none; }
  .chip.off { opacity:.35; }
  .chip .dot { width:12px; height:12px; border-radius:50%; border:1px solid #fff; box-shadow:0 0 0 1px rgba(0,0,0,.15); }
  .ctl { font-size:12px; color:#52514e; display:flex; align-items:center; gap:6px; }
  .ctl input[type=number] { width:76px; padding:5px 8px; border:1px solid #d5d3cb; border-radius:6px; font-size:13px; }
  .ctl select { padding:5px 6px; border:1px solid #d5d3cb; border-radius:6px; font-size:13px; background:#fff; }
  #destInput { width:220px; padding:6px 10px; border:2px solid #0d366b; border-radius:8px; font-size:13px; }
  #resetBtn { padding:6px 12px; border:1px solid #d5d3cb; border-radius:8px; background:#fff; font-size:12px; cursor:pointer; color:#52514e; display:none; }
  #stats { font-size:12px; color:#52514e; margin-left:auto; }
  #modulebar { display:flex; align-items:center; gap:8px; padding:7px 16px; background:#0d366b; overflow-x:auto; }
  #modulebar .lbl { color:#bcd3f0; font-size:12.5px; flex:none; font-weight:600; }
  #modulebar a { color:#fff; font-size:12.5px; text-decoration:none; background:rgba(255,255,255,.14); border-radius:14px; padding:3px 12px; flex:none; transition:background .12s; }
  #modulebar a:hover { background:rgba(255,255,255,.3); }
  #main { flex:1; display:flex; min-height:0; }
  #map { flex:1; }
  #panel { width:330px; background:#fcfcfb; border-left:1px solid #e8e6e0; overflow-y:auto; }
  #panelHead { padding:10px 14px 6px; position:sticky; top:0; background:#fcfcfb; z-index:2; border-bottom:1px solid #f0efec; }
  #panelHead h2 { font-size:13px; color:#52514e; font-weight:600; }
  #moreBtn, #allBtn, #stopBtn { margin:6px 6px 0 0; padding:4px 10px; border:1px solid #0d366b; color:#0d366b; background:#fff; border-radius:6px; font-size:12px; cursor:pointer; display:none; }
  #stopBtn { border-color:#d03b3b; color:#d03b3b; }
  #panelHint { margin-top:6px; }
  .row { padding:8px 14px; border-bottom:1px solid #f0efec; cursor:pointer; display:flex; gap:10px; align-items:baseline; }
  .row:hover { background:#f0f4fa; }
  .row .rank { font-size:11px; color:#8b8a85; width:18px; flex:none; }
  .row .body { flex:1; min-width:0; }
  .row .name { font-size:13px; color:#0b0b0b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row .meta { font-size:11px; color:#52514e; margin-top:2px; }
  .row .t { font-size:14px; font-weight:600; color:#0d366b; flex:none; text-align:right; }
  .row .t small { font-size:10px; font-weight:400; color:#8b8a85; display:block; }
  .row .t .pending { color:#8b8a85; font-weight:400; font-size:12px; }
  .dest-pin { display:flex; flex-direction:column; align-items:center; transform:translateY(-4px); }
  .dest-pin .core { width:18px; height:18px; border-radius:50%; background:#d03b3b; border:3px solid #fff; box-shadow:0 1px 6px rgba(0,0,0,.4); }
  .dest-pin .lbl { margin-top:3px; font-size:12px; font-weight:600; color:#7a1414; background:rgba(255,255,255,.92); padding:2px 8px; border-radius:4px; box-shadow:0 1px 3px rgba(0,0,0,.2); white-space:nowrap; }
  .iw { font-size:12.5px; line-height:1.65; max-width:300px; color:#0b0b0b; }
  .iw h3 { font-size:14px; margin-bottom:2px; }
  .iw .dim { color:#52514e; }
  .iw .big { font-weight:600; color:#0d366b; }
  .iw a { color:#256abf; text-decoration:none; }
  .iw .go { display:inline-block; margin-top:4px; margin-right:8px; padding:3px 10px; border:1px solid #256abf; border-radius:6px; font-size:12px; }
  .hint { font-size:11px; color:#8b8a85; }
  @media (max-width:760px){ #panel{display:none;} #destInput{width:150px;} }
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>公租房 → <span id="destName">__DEST_NAME__</span></h1>
    <div class="ctl">🎯 <input id="destInput" placeholder="输入任意地点，如：陆家嘴 / 张江 / 某小区" autocomplete="off"></div>
    <button id="resetBtn">↺ 回到__DEST_NAME__(全量精算)</button>
    <div class="seg" id="modeSeg">
      <button id="btnTransit" class="on">🚇 地铁/公交</button>
      <button id="btnDrive">🚗 驾车</button>
    </div>
    <div class="chips" id="chips"></div>
    <label class="ctl">区域 <select id="distSel"><option value="">全部</option></select></label>
    <label class="ctl">月租≤ <input type="number" id="rentMax" placeholder="不限" step="100"> 元</label>
    <span id="stats"></span>
  </header>
  <div id="modulebar">
    <span class="lbl">🧳 毕业生落地指南</span>
    <a href="guide.html">⌂ 首页</a>
    <a href="guide.html#hukou">🪪 落户自测</a>
    <a href="guide.html#jifen">📊 积分速算</a>
    <a href="guide.html#zufang">🏘 租房路线</a>
    <a href="guide.html#job">💰 到手工资</a>
    <a href="guide.html#yiliao">🏥 就医指南</a>
    <a href="guide.html#xincheng">🏙 新城通勤</a>
    <a href="guide.html#list">✅ 30天清单</a>
  </div>
  <div id="main">
    <div id="map"></div>
    <div id="panel">
      <div id="panelHead"><h2 id="panelTitle"></h2><button id="moreBtn">再精算 30 个</button><button id="allBtn">精算全部</button><button id="stopBtn">停止</button><div id="panelHint" class="hint"></div></div>
      <div id="list"></div>
    </div>
  </div>
</div>
<script src="https://webapi.amap.com/loader.js"></script>
<script>
const LISTINGS = __DATA__;
LISTINGS.forEach((x, i) => { x.i = i; });
const PRESET = { lon: __DEST_LON__, lat: __DEST_LAT__, name: '__DEST_NAME__' };
const TIME_BUCKETS = [
  { max: 30, label: '≤30分' }, { max: 45, label: '31–45分' }, { max: 60, label: '46–60分' },
  { max: 90, label: '61–90分' }, { max: Infinity, label: '>90分' },
];
const DIST_BUCKETS = [
  { max: 5, label: '≤5km' }, { max: 10, label: '5–10km' }, { max: 15, label: '10–15km' },
  { max: 25, label: '15–25km' }, { max: Infinity, label: '>25km' },
];
const RAMP = ['#0d366b', '#184f95', '#256abf', '#3987e5', '#6da7ec'];
const RADII = [9, 8, 7, 6, 5];
const NODATA = { label: '无数据', color: '#b0aea6', r: 4.5 };

let mode = 'tm';                 // preset 模式下排序/着色指标
let custom = null;               // {lon,lat,name} 自定义目的地
let calc = {};                   // 自定义模式实算结果: i -> {tm,dm,st}
let calcToken = 0;               // 目的地变更后作废旧计算
let calcBusy = false;
let bucketOn = [true, true, true, true, true, true];
let rentMax = null, distSel = '';
let markers = [], infoWindow = null, gmap = null, destMarker = null, AMapRef = null;

function esc(t) {
  return String(t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function buckets() { return custom ? DIST_BUCKETS : TIME_BUCKETS; }
function distKm(x) {
  const D = custom || PRESET, rad = Math.PI / 180;
  const dLat = (x.lat - D.lat) * rad, dLon = (x.lon - D.lon) * rad;
  const a = Math.sin(dLat/2)**2 + Math.cos(D.lat*rad) * Math.cos(x.lat*rad) * Math.sin(dLon/2)**2;
  return 12742 * Math.asin(Math.sqrt(a));
}
function metric(x) { return custom ? distKm(x) : x[mode]; }
function bucketIdx(v) {
  if (v == null) return 5;
  const B = buckets();
  for (let i = 0; i < B.length; i++) if (v <= B[i].max) return i;
  return 4;
}
function fmtRent(x) {
  return (x.rl != null && x.rh != null) ? (x.rl === x.rh ? '¥' + Math.round(x.rl) : '¥' + Math.round(x.rl) + '–' + Math.round(x.rh)) : '¥?';
}
function visible(x) {
  if (distSel && x.d !== distSel) return false;
  if (!bucketOn[bucketIdx(metric(x))]) return false;
  if (rentMax != null && x.rl != null && x.rl > rentMax) return false;
  return true;
}
function iwHtml(x) {
  const tel = /^[0-9-]{7,}$/.test(x.ph) ? '<a href="tel:' + x.ph + '">' + x.ph + '</a>' : x.ph;
  let commute;
  if (!custom) {
    commute = '<div>🚇 <span class="big">' + (x.tm != null ? x.tm + ' 分钟' : '无方案') + '</span>' +
      (x.tl ? ' <span class="dim">' + x.tl + '</span>' : '') + '</div>' +
      '<div>🚗 <span class="big">' + (x.dm != null ? x.dm + ' 分钟' : '—') + '</span>' +
      (x.dk != null ? ' <span class="dim">' + x.dk + ' km</span>' : '') + '</div>';
  } else {
    const c = calc[x.i];
    commute = '<div>直线 <span class="big">' + distKm(x).toFixed(1) + ' km</span> → ' + esc(custom.name) + '</div>';
    if (c && c.st === 'done') {
      commute += '<div>🚇 <span class="big">' + (c.tm != null ? c.tm + ' 分钟' : '无方案') + '</span> · 🚗 <span class="big">' + (c.dm != null ? c.dm + ' 分钟' : '—') + '</span>' +
        ((c.tm == null && c.dm == null) ? ' <a class="go" href="javascript:void(0)" onclick="recalcOne(' + x.i + ')">↻ 重算</a>' : '') + '</div>';
    } else if (c && c.st === 'pending') {
      commute += '<div class="dim">通勤时间计算中…</div>';
    } else {
      commute += '<div class="dim">点击下方「算通勤」获取真实时间</div><a class="go" href="javascript:void(0)" onclick="calcAndRefresh(' + x.i + ')">⏱ 算通勤</a>';
    }
  }
  const D = custom || PRESET;
  const from = x.lon + ',' + x.lat + ',' + encodeURIComponent(x.n);
  const to = D.lon + ',' + D.lat + ',' + encodeURIComponent(D.name);
  return '<div class="iw"><h3>' + x.n + '</h3>' +
    '<div class="dim">' + x.d + ' · ' + x.a + '</div>' +
    '<div>' + x.hx + (x.al != null ? ' · ' + x.al + '–' + x.ah + '㎡' : '') + ' · <b>' + fmtRent(x) + '</b>/月</div>' +
    commute +
    (x.mn ? '<div class="dim">最近站：' + x.mn + (x.md != null ? ' ' + x.md + 'm' : '') + (x.ml ? '（' + x.ml + '）' : '') + '</div>' : '') +
    (x.ph ? '<div class="dim">管家：' + tel + '</div>' : '') +
    '<a class="go" target="_blank" href="https://uri.amap.com/direction?from=' + from + '&to=' + to + '&mode=bus&src=gzf">公交导航 ↗</a>' +
    '<a class="go" target="_blank" href="https://uri.amap.com/direction?from=' + from + '&to=' + to + '&mode=car&src=gzf">驾车导航 ↗</a></div>';
}
function restyle() {
  let shown = 0;
  markers.forEach(mk => {
    const x = mk.getExtData();
    const bi = bucketIdx(metric(x));
    mk.setOptions({ fillColor: bi === 5 ? NODATA.color : RAMP[bi], radius: bi === 5 ? NODATA.r : RADII[bi], zIndex: 20 - bi });
    if (visible(x)) { mk.show(); shown++; } else { mk.hide(); }
  });
  document.getElementById('stats').textContent = '显示 ' + shown + ' / ' + LISTINGS.length + ' 个房源';
  renderChips();
  renderList();
}
function renderChips() {
  const counts = [0, 0, 0, 0, 0, 0];
  LISTINGS.filter(x => !distSel || x.d === distSel).forEach(x => counts[bucketIdx(metric(x))]++);
  const el = document.getElementById('chips');
  el.innerHTML = '';
  const items = [...buckets().map((b, i) => ({ label: b.label, color: RAMP[i] })), NODATA];
  items.forEach((b, i) => {
    if (i === 5 && counts[5] === 0) return;
    const c = document.createElement('span');
    c.className = 'chip' + (bucketOn[i] ? '' : ' off');
    c.innerHTML = '<span class="dot" style="background:' + (b.color || NODATA.color) + '"></span>' + b.label + ' (' + counts[i] + ')';
    c.onclick = () => { bucketOn[i] = !bucketOn[i]; restyle(); };
    el.appendChild(c);
  });
}
function visibleSorted() {
  return LISTINGS.filter(visible).sort((a, b) => distKm(a) - distKm(b));
}
function listRows() {
  const vis = LISTINGS.filter(visible);
  if (!custom) return vis.filter(x => x[mode] != null).sort((a, b) => a[mode] - b[mode]).slice(0, 40);
  const key = (x) => {
    const c = calc[x.i];
    return (c && c.st === 'done' && c.tm != null) ? c.tm : 1e6 + distKm(x);
  };
  return vis.sort((a, b) => key(a) - key(b)).slice(0, 40);
}
function renderList() {
  const rowsv = listRows();
  const el = document.getElementById('list');
  el.innerHTML = '';
  rowsv.forEach((x, i) => {
    const div = document.createElement('div');
    div.className = 'row';
    let right;
    if (!custom) {
      right = '<span class="t">' + x[mode] + '<small>分</small></span>';
    } else {
      const c = calc[x.i];
      if (c && c.st === 'done') {
        right = '<span class="t">🚇' + (c.tm != null ? c.tm : '—') + ' 🚗' + (c.dm != null ? c.dm : '—') + '<small>分钟</small></span>';
      } else if (c && c.st === 'pending') {
        right = '<span class="t"><span class="pending">计算中…</span><small>直线' + distKm(x).toFixed(1) + 'km</small></span>';
      } else {
        right = '<span class="t"><span class="pending">' + distKm(x).toFixed(1) + '<small>直线km</small></span></span>';
      }
    }
    div.innerHTML = '<span class="rank">' + (i + 1) + '</span><span class="body"><div class="name">' + x.n + '</div>' +
      '<div class="meta">' + x.d + ' · ' + fmtRent(x) + (x.mn ? ' · ' + x.mn + ' ' + (x.md || '') + 'm' : '') + '</div></span>' + right;
    div.onclick = () => focusOn(x);
    el.appendChild(div);
  });
  const done = Object.values(calc).filter(c => c.st === 'done').length;
  document.getElementById('panelTitle').textContent = custom
    ? '离「' + custom.name + '」最近 40 个 · 已精算 ' + done + ' 个'
    : '最近 40 个（按' + (mode === 'tm' ? '地铁/公交' : '驾车') + '时间）';
  const uncomputed = custom ? LISTINGS.filter(x => visible(x) && !calc[x.i]).length : 0;
  document.getElementById('moreBtn').style.display = (custom && uncomputed > 0 && !calcBusy) ? 'inline-block' : 'none';
  document.getElementById('allBtn').style.display = (custom && uncomputed > 30 && !calcBusy) ? 'inline-block' : 'none';
  document.getElementById('stopBtn').style.display = (custom && calcBusy) ? 'inline-block' : 'none';
  document.getElementById('panelHint').textContent = custom
    ? '已精算的按通勤时间排前、未算的按直线距离。要 713 个全量精算版:把 config.json 的目的地改成这里,重跑 enrich.py(用你自己的配额,约 15 分钟)。'
    : '';
}
function focusOn(x) {
  gmap.setZoomAndCenter(13, [x.lon, x.lat]);
  infoWindow.setContent(iwHtml(x));
  infoWindow.open(gmap, [x.lon, x.lat]);
  if (custom && !calc[x.i]) calcAndRefresh(x.i);
}
// —— 自定义目的地：实算通勤 ——
function calcOne(x, token) {
  return new Promise(resolve => {
    if (token !== calcToken || !AMapRef || !custom) return resolve();
    calc[x.i] = { st: 'pending' };
    const D = [custom.lon, custom.lat];
    let settled = false;
    const finish = (tm, dm) => {
      if (settled) return;
      settled = true;
      clearTimeout(guard);
      if (token === calcToken) calc[x.i] = { st: 'done', tm: tm, dm: dm };
      resolve();
    };
    const guard = setTimeout(() => finish(null, null), 25000);
    // 每次实算用独立实例：共享实例的并发 search 会互相打断回调
    const tSvc = new AMapRef.Transfer({ city: '__CITY__', policy: (AMapRef.TransferPolicy || {}).LEAST_TIME });
    const dSvc = new AMapRef.Driving({ policy: (AMapRef.DrivingPolicy || {}).LEAST_TIME });
    tSvc.search([x.lon, x.lat], D, (st1, r1) => {
      const tmin = (st1 === 'complete' && r1.plans && r1.plans.length) ? Math.round(r1.plans[0].time / 60) : null;
      dSvc.search([x.lon, x.lat], D, (st2, r2) => {
        const dmin = (st2 === 'complete' && r2.routes && r2.routes.length) ? Math.round(r2.routes[0].time / 60) : null;
        finish(tmin, dmin);
      });
    });
  });
}
window.recalcOne = function (i) {
  delete calc[i];
  calcAndRefresh(i);
};
window.calcAndRefresh = async function (i) {
  const x = LISTINGS[i];
  const token = calcToken;
  await calcOne(x, token);
  if (token !== calcToken) return;
  renderList();
  if (infoWindow.getIsOpen && infoWindow.getIsOpen()) infoWindow.setContent(iwHtml(x));
};
async function autoCompute(n) {
  const token = calcToken;
  calcBusy = true;
  renderList();
  const cand = visibleSorted().filter(x => !calc[x.i]).slice(0, n);
  for (const x of cand) {
    if (token !== calcToken) break;
    await calcOne(x, token);
    if (token !== calcToken) break;
    renderList();
    await new Promise(r => setTimeout(r, 350));
  }
  calcBusy = false;
  renderList();
}
function setCustomDest(lon, lat, name) {
  custom = { lon, lat, name };
  calcToken++;
  calc = {};
  bucketOn = [true, true, true, true, true, true];
  document.getElementById('destName').textContent = name;
  document.getElementById('resetBtn').style.display = 'inline-block';
  document.getElementById('modeSeg').className = 'seg disabled';
  destMarker.setPosition([lon, lat]);
  destMarker.setContent('<div class="dest-pin"><div class="core"></div><div class="lbl">' + esc(name) + '</div></div>');
  infoWindow.close();
  restyle();
  gmap.setZoomAndCenter(11.5, [lon, lat]);
  if (!/nocalc/.test(location.hash)) autoCompute(30);
}
function resetPreset() {
  custom = null;
  calcToken++;
  calc = {};
  bucketOn = [true, true, true, true, true, true];
  document.getElementById('destName').textContent = PRESET.name;
  document.getElementById('destInput').value = '';
  document.getElementById('resetBtn').style.display = 'none';
  document.getElementById('modeSeg').className = 'seg';
  destMarker.setPosition([PRESET.lon, PRESET.lat]);
  destMarker.setContent('<div class="dest-pin"><div class="core"></div><div class="lbl">__DEST_NAME__</div></div>');
  infoWindow.close();
  restyle();
  gmap.setZoomAndCenter(10.6, [121.44, 31.06]);
}
const EMBED_JS_KEY = '__JS_KEY__';
const EMBED_SEC_CODE = '__SEC_CODE__';
function showSetup(err) {
  const hasStored = !!localStorage.getItem('gzf_amap_js_key');
  document.getElementById('map').innerHTML =
    '<div style="max-width:560px;margin:60px auto;background:#fff;border:1px solid #e8e6e0;border-radius:14px;padding:26px 30px;font-size:14px;line-height:1.8">' +
    '<h2 style="font-size:17px;margin-bottom:6px">🔑 首次使用:配置你自己的高德地图 Key(免费,约 2 分钟)</h2>' +
    (err ? '<div style="background:#fdf0e7;border:1px solid #e6b795;color:#7a3d10;border-radius:8px;padding:8px 12px;font-size:13px;margin:8px 0">' + err + '</div>' : '') +
    '<ol style="padding-left:20px;color:#3a3a37;font-size:13.5px">' +
    '<li>打开 <a href="https://lbs.amap.com/" target="_blank" style="color:#256abf">高德开放平台</a> 注册并完成个人实名(免费);</li>' +
    '<li>进入 <a href="https://console.amap.com/dev/key/app" target="_blank" style="color:#256abf">控制台 → 我的应用</a>,创建应用后「添加 Key」,服务平台选 <b>Web端(JS API)</b>;</li>' +
    '<li>把生成的 <b>Key</b> 和配对的 <b>安全密钥</b> 粘贴到下面(只保存在你自己的浏览器里,不会上传给任何人)。</li></ol>' +
    '<label style="display:block;font-size:13px;color:#52514e;margin:10px 0 4px">JS API Key</label>' +
    '<input id="kIn" style="width:100%;padding:9px 10px;border:1px solid #d5d3cb;border-radius:8px;font-size:14px" placeholder="32 位字符,在高德控制台复制">' +
    '<label style="display:block;font-size:13px;color:#52514e;margin:10px 0 4px">安全密钥</label>' +
    '<input id="sIn" style="width:100%;padding:9px 10px;border:1px solid #d5d3cb;border-radius:8px;font-size:14px" placeholder="与该 Key 配对,同在控制台一行显示">' +
    '<button onclick="saveAmapKeys()" style="margin-top:14px;padding:9px 22px;border:0;background:#0d366b;color:#fff;border-radius:8px;font-size:14px;cursor:pointer">保存并加载地图</button>' +
    (hasStored ? ' <a href="javascript:void(0)" onclick="clearAmapKeys()" style="font-size:12px;color:#8b8a85;margin-left:10px">清除已存 Key</a>' : '') +
    '</div>';
  const k = localStorage.getItem('gzf_amap_js_key'), s = localStorage.getItem('gzf_amap_sec');
  if (k) document.getElementById('kIn').value = k;
  if (s) document.getElementById('sIn').value = s;
}
window.clearAmapKeys = function () {
  localStorage.removeItem('gzf_amap_js_key');
  localStorage.removeItem('gzf_amap_sec');
  location.reload();
};
window.saveAmapKeys = function () {
  const k = document.getElementById('kIn').value.trim();
  const s = document.getElementById('sIn').value.trim();
  if (!k || !s) { alert('两个值都要填:Key 和安全密钥'); return; }
  localStorage.setItem('gzf_amap_js_key', k);
  localStorage.setItem('gzf_amap_sec', s);
  location.reload();
};
function bootMap() {
const _k = (EMBED_JS_KEY || localStorage.getItem('gzf_amap_js_key') || '').trim();
const _s = (EMBED_SEC_CODE || localStorage.getItem('gzf_amap_sec') || '').trim();
if (!_k || !_s) { showSetup(''); return; }
window._AMapSecurityConfig = { securityJsCode: _s };
AMapLoader.load({
  key: _k,
  version: '2.0',
  plugins: ['AMap.Scale', 'AMap.ToolBar', 'AMap.AutoComplete', 'AMap.Transfer', 'AMap.Driving'],
}).then((AMap) => {
  // 强制：设置应用标识（必须在 new AMap.Map 之前）
  AMap.getConfig().appname = 'amap-jsapi-skill';
  gmap = new AMap.Map('map', {
    zoom: 10.6,
    center: [121.44, 31.06],
    viewMode: '2D',
    mapStyle: 'amap://styles/whitesmoke',
  });
  gmap.addControl(new AMap.Scale());
  gmap.addControl(new AMap.ToolBar({ position: { bottom: '90px', right: '14px' } }));
  infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -8), autoMove: true, closeWhenClickMap: true });
  AMapRef = AMap;
  destMarker = new AMap.Marker({
    position: [PRESET.lon, PRESET.lat], zIndex: 200, anchor: 'top-center',
    content: '<div class="dest-pin"><div class="core"></div><div class="lbl">__DEST_NAME__</div></div>',
  });
  gmap.add(destMarker);
  LISTINGS.forEach(x => {
    const mk = new AMap.CircleMarker({
      center: [x.lon, x.lat], radius: 6, fillOpacity: 0.88,
      strokeColor: '#ffffff', strokeWeight: 1, strokeOpacity: 0.9,
      cursor: 'pointer', bubble: false, extData: x,
    });
    mk.on('click', () => focusOn(x));
    markers.push(mk);
  });
  gmap.add(markers);
  // 任意目的地：联想输入 / 右键地图选点
  const ac = new AMap.AutoComplete({ input: 'destInput', city: '__CITY__', citylimit: true });
  ac.on('select', (e) => {
    if (!e.poi || !e.poi.location) return;
    setCustomDest(e.poi.location.getLng(), e.poi.location.getLat(), e.poi.name);
  });
  gmap.on('rightclick', (e) => {
    setCustomDest(e.lnglat.getLng(), e.lnglat.getLat(), '地图选点');
  });
  document.getElementById('resetBtn').onclick = resetPreset;
  document.getElementById('moreBtn').onclick = () => autoCompute(30);
  document.getElementById('allBtn').onclick = () => {
    const cnt = LISTINGS.filter(x => visible(x) && !calc[x.i]).length;
    if (!cnt) return;
    const mins = Math.max(1, Math.ceil(cnt * 1.8 / 60));
    if (confirm('将对当前可见的 ' + cnt + ' 个房源逐一实算地铁+驾车路线,约消耗 ' + (cnt * 2) + ' 次 JSAPI 配额、耗时约 ' + mins + ' 分钟(期间可随时点「停止」)。继续?')) autoCompute(cnt);
  };
  document.getElementById('stopBtn').onclick = () => {
    calcToken++;
    calcBusy = false;
    for (const k in calc) if (calc[k].st === 'pending') delete calc[k];
    renderList();
  };
  document.getElementById('btnTransit').onclick = () => { mode = 'tm'; setSeg(); restyle(); };
  document.getElementById('btnDrive').onclick = () => { mode = 'dm'; setSeg(); restyle(); };
  function setSeg() {
    document.getElementById('btnTransit').className = mode === 'tm' ? 'on' : '';
    document.getElementById('btnDrive').className = mode === 'dm' ? 'on' : '';
  }
  document.getElementById('rentMax').addEventListener('input', (e) => {
    rentMax = e.target.value ? Number(e.target.value) : null;
    restyle();
  });
  const distCount = {};
  LISTINGS.forEach(x => { distCount[x.d] = (distCount[x.d] || 0) + 1; });
  const sel = document.getElementById('distSel');
  Object.keys(distCount).sort((a, b) => distCount[b] - distCount[a]).forEach(d => {
    const o = document.createElement('option');
    o.value = d; o.textContent = d + ' (' + distCount[d] + ')';
    sel.appendChild(o);
  });
  sel.addEventListener('change', () => {
    distSel = sel.value;
    restyle();
    const vis = markers.filter(mk => visible(mk.getExtData()));
    if (distSel && vis.length) gmap.setFitView(vis, false, [60, 60, 60, 60]);
  });
  restyle();
  // #dest=lon,lat,名称 直达自定义目的地
  const hm = location.hash.match(/dest=([0-9.]+),([0-9.]+),([^&]+)/);
  if (hm) {
    let nm = hm[3];
    try { nm = decodeURIComponent(nm); } catch (e) { /* 保留原文 */ }
    setCustomDest(parseFloat(hm[1]), parseFloat(hm[2]), nm);
  }
}).catch(e => {
  console.error(e);
  showSetup('地图加载失败:' + e + '。若是自己粘贴的 Key,请确认类型为「Web端(JS API)」且安全密钥与之配对。');
});
}
bootMap();
</script>
</body>
</html>
"""

base = (html.replace("__DATA__", data_js)
        .replace("__DEST_LON__", DEST_LON).replace("__DEST_LAT__", DEST_LAT)
        .replace("__DEST_NAME__", DEST_NAME).replace("__CITY__", CITY))
open(OUT, "w", encoding="utf-8").write(base.replace("__JS_KEY__", JS_KEY).replace("__SEC_CODE__", SEC))
OUT_SHARE = os.path.join(BASE, "map-share.html")
open(OUT_SHARE, "w", encoding="utf-8").write(base.replace("__JS_KEY__", "").replace("__SEC_CODE__", ""))
print(f"个人版:{OUT}(内嵌你的 Key,自己用,勿外传)")
print(f"分享版:{OUT_SHARE}(不含任何 Key,发给别人;对方打开后按引导粘自己的 Key,存对方本机)")
print(f"两个文件各内嵌 {len(rows)} 个房源数据。")
