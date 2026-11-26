"""把最新快照(和上一份对比)渲染成一页静态看板 out/<SYM>.html。只陈述数据, 不给买卖建议。"""
import datetime as dt, glob, html, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAT = {"exchange": ("交易所", "var(--s1)"), "project": ("项目方", "var(--s2)"),
       "contract": ("合约/DeFi", "var(--s3)"), "unlabeled": ("未标注地址", "var(--s0)")}


def fm(x, d=1):
    a = abs(x)
    if a >= 1e9: return f"{x / 1e9:.{d}f}B"
    if a >= 1e6: return f"{x / 1e6:.{d}f}M"
    if a >= 1e3: return f"{x / 1e3:.{d}f}K"
    return f"{x:.{d}f}"


def pct(x, d=1): return f"{x * 100:.{d}f}%"
def short(a): return a[:6] + "…" + a[-4:]
def esc(s): return html.escape(str(s or ""))


def line_svg(pts, w=560, h=170, fmt="price", title=""):
    """单序列折线 + 十字线悬停。pts=[[ms, v], ...]"""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, lo, hi = min(xs), max(xs), min(ys), max(ys)
    pad = (hi - lo) * 0.1 or hi * 0.05 or 1; lo -= pad; hi += pad
    L, R, T, B = 52, 10, 10, 24
    X = lambda x: L + (x - x0) / (x1 - x0 or 1) * (w - L - R)
    Y = lambda y: T + (hi - y) / (hi - lo) * (h - T - B)
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(pts))
    ticks = "".join(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                    f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" class="ax" text-anchor="end">{fmtv(v, fmt)}</text>'
                    for v in [lo + (hi - lo) * k / 3 for k in range(4)])
    xl = "".join(f'<text x="{X(x):.1f}" y="{h - 6}" class="ax" text-anchor="{a}">{dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc):%m-%d %H:%M}</text>'
                 for x, a in [(x0, "start"), ((x0 + x1) / 2, "middle"), (x1, "end")])
    data = json.dumps([[round(X(x), 1), round(Y(y), 1), dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc).strftime("%m-%d %H:%M UTC"), fmtv(y, fmt)] for x, y in pts])
    return (f'<svg class="chart line" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}" data-pts=\'{data}\'>'
            f'{ticks}{xl}<path d="{path}" class="ln"/><line class="xh" y1="{T}" y2="{h - B}"/><circle class="dot" r="4"/>'
            f'<rect x="{L}" y="{T}" width="{w - L - R}" height="{h - T - B}" class="hit"/></svg>')


def fmtv(v, f):
    return {"price": f"${v:.4f}", "usd": "$" + fm(v), "fund": f"{v * 100:.4f}%"}[f]


def funding_svg(fr, w=560, h=150):
    vals = [v for _, v in fr]; m = max(abs(v) for v in vals) or 1e-6
    L, R, T, B = 52, 10, 10, 24; mid = T + (h - T - B) / 2; bw = (w - L - R) / len(fr)
    bars = ""
    for i, (t, v) in enumerate(fr):
        bh = abs(v) / m * (h - T - B) / 2; y = mid - bh if v >= 0 else mid
        tip = f"{dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc):%m-%d %H:%M UTC} · {v * 100:.4f}%"
        bars += (f'<g class="bar" data-tip="{tip}"><rect x="{L + i * bw:.1f}" y="{T}" width="{bw:.1f}" height="{h - T - B}" class="hit"/>'
                 f'<rect x="{L + i * bw + 1:.1f}" y="{y:.1f}" width="{max(bw - 2, 1):.1f}" height="{max(bh, 1):.1f}" rx="2" '
                 f'fill="{"var(--pos)" if v >= 0 else "var(--neg)"}"/></g>')
    ax = (f'<line x1="{L}" x2="{w - R}" y1="{mid}" y2="{mid}" class="base"/>'
          f'<text x="{L - 6}" y="{T + 8}" class="ax" text-anchor="end">+{m * 100:.3f}%</text>'
          f'<text x="{L - 6}" y="{mid + 4}" class="ax" text-anchor="end">0</text>'
          f'<text x="{L - 6}" y="{h - B}" class="ax" text-anchor="end">-{m * 100:.3f}%</text>')
    return f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="资金费率">{ax}{bars}</svg>'


def stack_bar(by_cat):
    segs, legend, rest = "", "", 1 - sum(by_cat.values())
    for k in ["exchange", "project", "contract", "unlabeled"]:
        v = by_cat.get(k, 0)
        if v <= 0: continue
        name, col = CAT[k]
        segs += f'<div class="seg" style="width:{v * 100:.2f}%;background:{col}" data-tip="{name} {pct(v)}"></div>'
        legend += f'<span class="lg"><i style="background:{col}"></i>{name} <b>{pct(v)}</b></span>'
    segs += f'<div class="seg" style="width:{rest * 100:.2f}%;background:var(--rest)" data-tip="前100名以外 {pct(rest)}"></div>'
    legend += f'<span class="lg"><i style="background:var(--rest)"></i>前100名以外 <b>{pct(rest)}</b></span>'
    return f'<div class="stack">{segs}</div><div class="legend">{legend}</div>'


def flags(cur, prev):
    out, tok, p = [], cur["token"], cur["perp"]
    oi = p["oi_hist"]
    if len(oi) >= 25:
        ch = oi[-1][1] / oi[-25][1] - 1
        if abs(ch) >= 0.2: out.append(("serious", f"合约持仓量 24h {'+' if ch > 0 else ''}{pct(ch)}"))
    if abs(p["funding"]) >= 0.0005: out.append(("warning", f"资金费率 {p['funding'] * 100:.3f}%/8h, 偏离常态"))
    to_ex = sum(t["usd"] for t in cur["transfers"] if t["to_cat"] == "exchange" and t["from_cat"] != "exchange")
    fr_ex = sum(t["usd"] for t in cur["transfers"] if t["from_cat"] == "exchange" and t["to_cat"] != "exchange")
    if to_ex - fr_ex >= 1e6: out.append(("warning", f"大额净转入交易所 ${fm(to_ex - fr_ex)}(近 {cur['transfers_covered_h']}h)"))
    if prev:
        pb = {h["addr"]: h["bal"] for h in prev["holders"]}
        for h in cur["holders"][:50]:
            d = h["bal"] - pb.get(h["addr"], 0)
            if abs(d) / tok["supply"] >= 0.005:
                out.append(("warning", f"大户 {esc(h['name'] or short(h['addr']))} 持仓 {'+' if d > 0 else ''}{fm(d)} 枚({pct(d / tok['supply'], 2)} 供应)"))
        if prev["dex"]["liq_usd"] and cur["dex"]["liq_usd"] / prev["dex"]["liq_usd"] - 1 <= -0.2:
            out.append(("serious", f"DEX 流动性较上次快照 {pct(cur['dex']['liq_usd'] / prev['dex']['liq_usd'] - 1)}"))
    return out


def flow_kind(t):
    if t["to_cat"] == "exchange" and t["from_cat"] != "exchange": return "转入交易所"
    if t["from_cat"] == "exchange" and t["to_cat"] != "exchange": return "转出交易所"
    if "exchange" == t["to_cat"] == t["from_cat"]: return "交易所内部"
    if "project" in (t["to_cat"], t["from_cat"]): return "项目方地址"
    return "地址间"


def render(sym):
    files = sorted(glob.glob(str(HERE / "data" / sym / "*.json")))
    cur = json.loads(Path(files[-1]).read_text()); prev = json.loads(Path(files[-2]).read_text()) if len(files) > 1 else None
    tok, p, sh = cur["token"], cur["perp"], cur["share"]
    oi = p["oi_hist"]; oi_ch = oi[-1][1] / oi[-25][1] - 1 if len(oi) >= 25 else None
    pb = {h["addr"]: h["bal"] for h in prev["holders"]} if prev else {}
    rows = ""
    for i, h in enumerate(cur["holders"][:20]):
        d = h["bal"] - pb[h["addr"]] if h["addr"] in pb else None
        dtxt = "—" if not prev else ("新进" if d is None else (("+" if d > 0 else "") + fm(d) if abs(d) >= 1 else "0"))
        rows += (f'<tr><td>{i + 1}</td><td><a href="https://eth.blockscout.com/address/{h["addr"]}" target="_blank" rel="noopener">{short(h["addr"])}</a></td>'
                 f'<td>{esc(h["name"]) or "<span class=m>—</span>"}</td><td><i class="sw" style="background:{CAT[h["cat"]][1]}"></i>{CAT[h["cat"]][0]}</td>'
                 f'<td class="n">{fm(h["bal"])}</td><td class="n">{pct(h["bal"] / tok["supply"], 2)}</td><td class="n">{dtxt}</td></tr>')
    trows = ""
    for t in sorted(cur["transfers"], key=lambda t: -t["usd"])[:15]:
        nm = lambda c, n, a: esc(n) if n else short(a)
        trows += (f'<tr><td>{t["ts"][5:16].replace("T", " ")}</td><td>{flow_kind(t)}</td><td>{nm(t["from_cat"], t["from_name"], t["from"])}</td>'
                  f'<td>{nm(t["to_cat"], t["to_name"], t["to"])}</td><td class="n">{fm(t["amt"])}</td><td class="n">${fm(t["usd"])}</td>'
                  f'<td><a href="https://eth.blockscout.com/tx/{t["tx"]}" target="_blank" rel="noopener">查看</a></td></tr>')
    fl = flags(cur, prev)
    fl_html = "".join(f'<li class="f {lv}"><span class="ic">{"▲" if lv == "serious" else "●"}</span>{m}</li>' for lv, m in fl) or \
        '<li class="f ok"><span class="ic">✓</span>当前没有触发任何异常规则</li>'
    dexrows = "".join(f'<tr><td>{esc(x["dex"])}</td><td>{esc(x["pair"])}</td><td class="n">${fm(x["liq"])}</td><td class="n">${fm(x["vol24"])}</td></tr>' for x in cur["dex"]["top"])
    kpis = [("价格", f"${p['price']:.4f}", f"24h {p['chg24']:+.2f}%"),
            ("持币地址", f"{cur['holders_count']:,}", "链上 ERC-20"),
            ("前 10 地址占比", pct(sh["top10"]), f"前 100: {pct(sh['top100'])}"),
            ("交易所地址持有", pct(sh["by_cat"].get("exchange", 0)), "前100中已标注的"),
            ("DEX 流动性", "$" + fm(cur["dex"]["liq_usd"]), f"24h 成交 ${fm(cur['dex']['vol24_usd'])}"),
            ("合约持仓量", "$" + fm(oi[-1][1]), f"24h {oi_ch * 100:+.1f}%" if oi_ch is not None else "—"),
            ("资金费率", f"{p['funding'] * 100:.4f}%", "每 8 小时"),
            ("合约 24h 成交", "$" + fm(p["qvol24"]), "Binance USDⓈ-M")]
    kpi_html = "".join(f'<div class="k"><div class="kl">{a}</div><div class="kv">{b}</div><div class="ks">{c}</div></div>' for a, b, c in kpis)
    upd = dt.datetime.fromisoformat(cur["ts"]).strftime("%Y-%m-%d %H:%M UTC")
    return fill(TEMPLATE, sym=sym, project=esc(tok["project"]), upd=upd, kpis=kpi_html, flags=fl_html,
                           stack=stack_bar(sh["by_cat"]), rows=rows, trows=trows or '<tr><td colspan=7 class=m>窗口内没有超过门槛的转账</td></tr>',
                           big=fm(tok["big_usd"], 0), cov=cur["transfers_covered_h"], dexrows=dexrows,
                           price=line_svg(p["close_1h"], fmt="price", title="7 天价格"),
                           oi=line_svg(oi, fmt="usd", title="48 小时合约持仓量"), fund=funding_svg(p["funding_hist"]),
                           prevnote=f"对比上次快照 {dt.datetime.fromisoformat(prev['ts']):%m-%d %H:%M UTC}" if prev else "首次快照, 变化列下次更新后出现",
                           addr=tok["address"])


def fill(tpl, **kw):
    """模板里用 %%key%% 占位(避免和 CSS 花括号冲突)。"""
    for k, v in kw.items(): tpl = tpl.replace(f"%%{k}%%", str(v))
    return tpl


TEMPLATE = open(HERE / "template.html", encoding="utf-8").read() if (HERE / "template.html").exists() else ""

if __name__ == "__main__":
    (HERE / "out").mkdir(exist_ok=True)
    for sym in sys.argv[1:] or [t["symbol"] for t in json.loads((HERE / "tokens.json").read_text())]:
        (HERE / "out" / f"{sym}.html").write_text(render(sym), encoding="utf-8")
        print("wrote", HERE / "out" / f"{sym}.html")
