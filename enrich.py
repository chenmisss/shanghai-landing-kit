#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公租房通勤计算管线（第 1 步）
读取 listings.csv 里的房源,调用高德 Web 服务 API 计算每个房源到目的地的:
  - 驾车距离/时间
  - 地铁/公交时间与换乘线路
  - 最近轨交站与步行距离
结果存入 enrich_cache.json(断点续传,中断后重跑即可)并导出 result.csv。
运行: python enrich.py   (Windows)  /  python3 enrich.py   (Mac)
无需安装任何第三方库,Python 3.9+ 自带的标准库即可。
"""
import csv, http.client, json, os, sys, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
HOST = "restapi.amap.com"
WORKERS = 12
PACE = 0.36  # 全局限速:个人 Key 上限 3 次/秒,压在 2.8 以下

# ---------- 读配置 ----------
CFG_PATH = os.path.join(BASE, "config.json")
if not os.path.exists(CFG_PATH):
    sys.exit("[错误] 没找到 config.json。请把 config.example.json 复制一份改名为 config.json,"
             "填入你的高德 Key(注册方法见 README 第一步)。")
try:
    CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except Exception as e:
    sys.exit(f"[错误] config.json 不是合法的 JSON:{e}")
KEY = (CFG.get("amap_web_key") or "").strip()
if not KEY or "粘贴" in KEY:
    sys.exit("[错误] config.json 里的 amap_web_key 还没填。需要【Web服务】类型的 Key。")
DEST_NAME = (CFG.get("destination_name") or "").strip() or "莘庄地铁站"
CITY = (CFG.get("city") or "上海").strip()

# ---------- 高德请求客户端(限速+重试) ----------
_pace_lock = threading.Lock()
_next_t = [0.0]
DAILY_DEAD = set()
_plock = threading.Lock()

def log(msg):
    with _plock:
        print(msg, flush=True)

def _pace():
    with _pace_lock:
        now = time.time()
        t = max(now, _next_t[0])
        _next_t[0] = t + PACE
    d = t - time.time()
    if d > 0:
        time.sleep(d)

def call(service, params):
    if service in DAILY_DEAD:
        return None
    params = dict(params, key=KEY, output="JSON")
    path = f"/{service}?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        _pace()
        try:
            conn = http.client.HTTPSConnection(HOST, timeout=18)
            conn.request("GET", path)
            r = conn.getresponse()
            d = json.loads(r.read().decode("utf-8"))
            conn.close()
        except Exception as e:
            log(f"  [网络重试{attempt}] {type(e).__name__}")
            time.sleep(0.8)
            continue
        info = str(d.get("infocode", ""))
        if d.get("status") == "1":
            return d
        if info == "10001":
            sys.exit("[错误] 高德返回 INVALID_USER_KEY:Key 无效。请确认 config.json 里的 "
                     "amap_web_key 是【Web服务】类型(不是 Web端/JS API 类型),且没有多余空格。")
        if info in ("10021", "10020", "10019"):
            time.sleep(1.0 + 0.7 * attempt)
            continue
        if info in ("10044", "10045", "10003"):
            log(f"  [警告] {service} 今日配额用完({info}),该项数据将留空,明天重跑会自动补上")
            DAILY_DEAD.add(service)
            return None
        log(f"  [接口异常] {service}: {d.get('info')} {info}")
        return None
    return None

def s(v):
    return v if isinstance(v, str) else ""

# ---------- 上海行政区(用于地理编码结果校验,其他城市自动跳过) ----------
BOX = {
 "黄浦区": (121.45, 121.53, 31.19, 31.25), "徐汇区": (121.39, 121.48, 31.09, 31.22),
 "长宁区": (121.28, 121.45, 31.16, 31.24), "静安区": (121.41, 121.49, 31.20, 31.33),
 "普陀区": (121.33, 121.46, 31.20, 31.30), "虹口区": (121.45, 121.53, 31.23, 31.35),
 "杨浦区": (121.49, 121.57, 31.23, 31.35), "闵行区": (121.27, 121.54, 30.97, 31.25),
 "宝山区": (121.29, 121.56, 31.23, 31.49), "嘉定区": (121.13, 121.35, 31.21, 31.43),
 "浦东新区": (121.49, 122.13, 30.74, 31.41), "金山区": (121.15, 121.49, 30.67, 30.93),
 "松江区": (121.09, 121.41, 30.94, 31.16), "青浦区": (120.84, 121.33, 30.97, 31.29),
 "奉贤区": (121.32, 121.78, 30.81, 31.03), "崇明区": (121.08, 121.99, 31.26, 31.88),
}
ADCODE = {"黄浦区":"310101","徐汇区":"310104","长宁区":"310105","静安区":"310106","普陀区":"310107",
 "虹口区":"310109","杨浦区":"310110","闵行区":"310112","宝山区":"310113","嘉定区":"310114",
 "浦东新区":"310115","金山区":"310116","松江区":"310117","青浦区":"310118","奉贤区":"310120","崇明区":"310151"}

def in_box(dist, loc):
    if not loc:
        return False
    if dist not in BOX:
        return True
    lon, lat = map(float, loc.split(","))
    b = BOX[dist]
    return b[0] <= lon <= b[1] and b[2] <= lat <= b[3]

# ---------- 读房源表 ----------
CSV_PATH = os.path.join(BASE, "listings.csv")
if not os.path.exists(CSV_PATH):
    sys.exit("[错误] 没找到 listings.csv(房源表)。仓库自带一份上海公租房快照,请确认文件在脚本同目录。")
recs = []
with open(CSV_PATH, encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f)):
        name = (row.get("项目名称") or "").strip()
        addr = (row.get("地址") or "").strip()
        if not name or not addr:
            continue
        recs.append({"_id": f"r{i}", "项目名称": name, "区域": (row.get("区域") or "").strip(),
                     "地址": addr, "户型": (row.get("户型") or "").strip(),
                     "最低租金": row.get("最低租金"), "最高租金": row.get("最高租金"),
                     "最小面积": row.get("最小面积"), "最大面积": row.get("最大面积"),
                     "联系电话": (row.get("联系电话") or "").strip()})
if not recs:
    sys.exit("[错误] listings.csv 里没有读到有效房源(至少要有 项目名称 和 地址 两列)。")
print(f"读入房源 {len(recs)} 条;目的地:{DEST_NAME}({CITY})")

# ---------- 缓存 ----------
CACHE_PATH = os.path.join(BASE, "enrich_cache.json")
cache = json.load(open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else {}
for k in ("geo", "drive", "transit", "metro"):
    cache.setdefault(k, {})
_cache_lock = threading.Lock()
_done = [0]

def save_ckpt(force=False):
    with _cache_lock:
        _done[0] += 1
        if force or _done[0] % 25 == 0:
            json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)

# ---------- 第 0 步:目的地定位 ----------
dest_cached = cache.get("dest", {})
if dest_cached.get("name") == DEST_NAME and dest_cached.get("loc"):
    DEST = dest_cached["loc"]
else:
    d = call("v3/place/text", {"keywords": DEST_NAME, "city": CITY, "citylimit": "true", "offset": 1})
    pois = (d or {}).get("pois", []) or []
    if pois and s(pois[0].get("location")):
        DEST = pois[0]["location"]
        print(f"目的地定位:{s(pois[0].get('name'))} -> {DEST}")
    else:
        d = call("v3/geocode/geo", {"address": DEST_NAME, "city": CITY})
        gl = (d or {}).get("geocodes", []) or []
        if not (gl and s(gl[0].get("location"))):
            sys.exit(f"[错误] 定位不到目的地「{DEST_NAME}」,请在 config.json 里换个更具体的写法(如加上区名)。")
        DEST = gl[0]["location"]
        print(f"目的地定位(地址解析):{DEST}")
    cache["dest"] = {"name": DEST_NAME, "loc": DEST}
    # 目的地变了,旧的通勤结果全部作废
    cache["drive"], cache["transit"] = {}, {}
    save_ckpt(True)

# ---------- 第 1 步:逐条地理编码(注意:高德批量接口会错位,必须逐条) ----------
COARSE = ("市", "区县", "未知", "乡镇")

def geocode_one(r):
    addr, dist, name = r["地址"], r["区域"], r["项目名称"]
    with _cache_lock:
        if cache["geo"].get(addr, {}).get("loc"):
            return
    res = None
    d = call("v3/geocode/geo", {"address": addr, "city": ADCODE.get(dist, CITY)})
    gl = (d or {}).get("geocodes", []) or []
    if gl:
        g = gl[0]
        if s(g.get("location")) and s(g.get("level")) not in COARSE and in_box(dist, g["location"]):
            res = {"loc": g["location"], "src": "geo"}
    if not res:
        d = call("v3/place/text", {"keywords": name, "city": ADCODE.get(dist, CITY), "citylimit": "true", "offset": 10})
        for p in (d or {}).get("pois", []) or []:
            if (not dist or s(p.get("adname")) == dist) and s(p.get("location")):
                res = {"loc": p["location"], "src": "poi-name", "fmt": s(p.get("name"))}
                break
    if not res:
        d = call("v3/place/text", {"keywords": addr, "city": ADCODE.get(dist, CITY), "citylimit": "true", "offset": 10})
        for p in (d or {}).get("pois", []) or []:
            if (not dist or s(p.get("adname")) == dist) and s(p.get("location")):
                res = {"loc": p["location"], "src": "poi-addr", "fmt": s(p.get("name"))}
                break
    with _cache_lock:
        cache["geo"][addr] = res or {"loc": "", "src": "fail"}
    save_ckpt()
    if _done[0] % 50 == 0:
        log(f"  地理编码进度 ~{_done[0]}")

todo = [r for r in recs if not cache["geo"].get(r["地址"], {}).get("loc")]
print(f"[1/3] 地理编码:待处理 {len(todo)} 条(限速约 2.8 次/秒,请耐心)")
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(geocode_one, todo))
save_ckpt(True)
fails = [r for r in recs if cache["geo"].get(r["地址"], {}).get("src") == "fail"]
fbs = [(r, cache["geo"][r["地址"]]) for r in recs if cache["geo"].get(r["地址"], {}).get("src", "").startswith("poi")]
if fbs:
    print(f"  有 {len(fbs)} 条用了名称/地址模糊匹配定位,建议在地图上抽查:")
    for r, g in fbs[:20]:
        print(f"    {r['区域']} {r['项目名称']} -> {g.get('fmt','')}")
if fails:
    print(f"  [注意] {len(fails)} 条定位失败,将被跳过:")
    for r in fails[:20]:
        print(f"    {r['区域']} {r['项目名称']} | {r['地址']}")
print(f"[1/3] 完成:{len(recs)-len(fails)}/{len(recs)}")

# ---------- 第 2 步:驾车距离/时间(距离测量接口,100 个/批) ----------
todo = [r for r in recs if cache["geo"].get(r["地址"], {}).get("loc") and r["_id"] not in cache["drive"]]
print(f"[2/3] 驾车测算:待处理 {len(todo)} 条")
for i in range(0, len(todo), 100):
    chunk = todo[i:i+100]
    origins = "|".join(cache["geo"][r["地址"]]["loc"] for r in chunk)
    d = call("v3/distance", {"origins": origins, "destination": DEST, "type": "1"})
    for res in (d or {}).get("results", []) or []:
        if not isinstance(res, dict):
            continue
        oid, dist_m, dur = s(res.get("origin_id")), s(res.get("distance")), s(res.get("duration"))
        if not (oid.isdigit() and dist_m.isdigit() and dur.isdigit()):
            continue
        idx = int(oid) - 1
        if 0 <= idx < len(chunk):
            cache["drive"][chunk[idx]["_id"]] = {"km": round(int(dist_m)/1000, 1), "min": round(int(dur)/60)}
    save_ckpt(True)
print(f"[2/3] 完成:{len(cache['drive'])} 条")

# ---------- 第 3 步:公交/地铁路线 + 最近轨交站(并行) ----------
def transit_one(r):
    loc = cache["geo"].get(r["地址"], {}).get("loc")
    if not loc:
        return
    d = call("v3/direction/transit/integrated", {"origin": loc, "destination": DEST, "city": CITY, "strategy": "0"})
    out = None
    transits = ((d or {}).get("route", {}) or {}).get("transits", []) or []
    if transits:
        t = transits[0]
        lines, first_stop = [], ""
        for seg in t.get("segments", []) or []:
            bl = (seg.get("bus", {}) or {}).get("buslines", []) or []
            if bl:
                nm = s(bl[0].get("name"))
                lines.append(nm.split("(")[0])
                if not first_stop:
                    first_stop = s((bl[0].get("departure_stop", {}) or {}).get("name"))
        out = {"min": round(int(t["duration"])/60), "km": round(int(t.get("distance", 0))/1000, 1),
               "walk_m": int(t.get("walking_distance", 0)), "lines": " → ".join(lines), "first_stop": first_stop}
    with _cache_lock:
        cache["transit"][r["_id"]] = out
    save_ckpt()
    if _done[0] % 100 == 0:
        log(f"  通勤测算进度 ~{_done[0]}")

def metro_one(r):
    loc = cache["geo"].get(r["地址"], {}).get("loc")
    if not loc:
        return
    d = call("v3/place/around", {"location": loc, "types": "150500", "radius": "3000",
                                 "sortrule": "distance", "offset": 1, "page": 1})
    pois = (d or {}).get("pois", []) or []
    out = None
    if pois:
        p = pois[0]
        out = {"name": s(p.get("name")), "dist_m": int(s(p.get("distance")) or 0), "lines": s(p.get("address"))}
    with _cache_lock:
        cache["metro"][r["_id"]] = out
    save_ckpt()

jobs = []
drv = cache["drive"]
for r in sorted(recs, key=lambda x: drv.get(x["_id"], {}).get("km", 9999)):
    if not cache["geo"].get(r["地址"], {}).get("loc"):
        continue
    if r["_id"] not in cache["transit"]:
        jobs.append(("t", r))
    if r["_id"] not in cache["metro"]:
        jobs.append(("m", r))
print(f"[3/3] 公交路线+最近轨交站:待处理 {len(jobs)} 个任务(这是最慢的一步)")
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(lambda j: (transit_one if j[0] == "t" else metro_one)(j[1]), jobs))
save_ckpt(True)

# ---------- 导出 result.csv ----------
rows = []
for r in recs:
    g = cache["geo"].get(r["地址"], {})
    d = cache["drive"].get(r["_id"]) or {}
    t = cache["transit"].get(r["_id"]) or {}
    m = cache["metro"].get(r["_id"]) or {}
    rows.append({"项目名称": r["项目名称"], "区域": r["区域"], "地址": r["地址"], "户型": r["户型"],
                 "最低租金": r["最低租金"], "最高租金": r["最高租金"],
                 "最小面积": r["最小面积"], "最大面积": r["最大面积"], "联系电话": r["联系电话"],
                 "坐标": g.get("loc", ""),
                 "驾车距离km": d.get("km", ""), "驾车时间分": d.get("min", ""),
                 "公交时间分": (t or {}).get("min", ""), "公交线路": (t or {}).get("lines", ""),
                 "最近轨交站": (m or {}).get("name", ""), "到站距离m": (m or {}).get("dist_m", ""),
                 "轨交线路": (m or {}).get("lines", "")})
rows.sort(key=lambda x: (x["公交时间分"] if isinstance(x["公交时间分"], int) else 99999))
out_csv = os.path.join(BASE, "result.csv")
with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

t_ok = sum(1 for v in cache["transit"].values() if v)
print(f"\n全部完成!公交路线 {t_ok} 条 / 驾车 {len(cache['drive'])} 条")
print(f"排名表已导出:{out_csv}(按公交时间从近到远,可用 Excel 打开)")
print("下一步:运行  python build_map.py  生成交互地图")
