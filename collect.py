"""代币健康度看板 · 数据采集(全部免 key 公共接口)。

每跑一次存一份快照 data/<SYM>/<UTC时间>.json, 和上一份比出变化。
来源: Blockscout(持仓/转账/地址标签) · DexScreener(DEX 流动性) · Binance 合约公共接口(持仓量/资金费率/价格)。
只呈现数据与异常, 不给任何买卖建议。
"""
import datetime as dt, json, sys, time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
TOKENS = json.loads((HERE / "tokens.json").read_text())
BS = {"eth": "https://eth.blockscout.com/api/v2"}
EXCHANGES = ["binance", "coinbase", "okx", "okex", "bybit", "kraken", "bitget", "gate", "kucoin", "htx", "huobi",
             "upbit", "bithumb", "crypto.com", "mexc", "robinhood", "bitfinex", "gemini", "bitstamp", "wintermute"]
S = requests.Session(); S.headers["User-Agent"] = "token-health-dashboard/0.1"


def get(url, **params):
    for i in range(4):
        r = S.get(url, params=params or None, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (i + 1)); continue
        r.raise_for_status(); return r.json()
    r.raise_for_status()


def label(addr: dict, project: str):
    """返回 (类别, 显示名)。类别: project / exchange / contract / unlabeled"""
    md = addr.get("metadata") or {}
    tags = md.get("tags") or []
    names = [t.get("name", "") for t in tags] + [addr.get("name") or ""]
    entity = " ".join(str((t.get("meta") or {}).get("main_entity", "")) for t in tags)
    text = (" ".join(names) + " " + entity).lower()
    show = next((n for n in names if n), None)
    if project.lower() in text: return "project", show
    if any(k in text for k in EXCHANGES): return "exchange", show
    if addr.get("is_contract"): return "contract", show or "合约"
    return "unlabeled", show


def holders(tok, n_pages=2):
    base, out, params = BS[tok["chain"]], [], {}
    for _ in range(n_pages):
        d = get(f"{base}/tokens/{tok['address']}/holders", **params)
        out += d["items"]
        if not d.get("next_page_params"): break
        params = d["next_page_params"]; time.sleep(0.3)
    dec = 10 ** tok["decimals"]
    res = []
    for h in out:
        cat, name = label(h["address"], tok["project"])
        res.append({"addr": h["address"]["hash"], "bal": int(h["value"]) / dec, "cat": cat, "name": name})
    return res


def big_transfers(tok, price, min_usd, max_pages=40, hours=24):
    """最近 hours 小时内 ≥ min_usd 的转账。分页有上限, 返回实际覆盖的时间窗(诚实标注)。"""
    base, params, out, oldest = BS[tok["chain"]], {}, [], None
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    dec = 10 ** tok["decimals"]
    for _ in range(max_pages):
        d = get(f"{base}/tokens/{tok['address']}/transfers", **params)
        for t in d["items"]:
            ts = dt.datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
            oldest = ts
            if ts < cutoff: break
            amt = int(t["total"]["value"]) / dec
            if amt * price >= min_usd:
                fc, fn = label(t["from"], tok["project"]); tc, tn = label(t["to"], tok["project"])
                out.append({"ts": t["timestamp"], "amt": amt, "usd": amt * price, "tx": t["transaction_hash"],
                            "from": t["from"]["hash"], "from_cat": fc, "from_name": fn,
                            "to": t["to"]["hash"], "to_cat": tc, "to_name": tn})
        if (oldest and oldest < cutoff) or not d.get("next_page_params"): break
        params = d["next_page_params"]; time.sleep(0.3)
    covered_h = (dt.datetime.now(dt.timezone.utc) - oldest).total_seconds() / 3600 if oldest else 0
    return out, round(min(covered_h, hours), 2)


def dex(tok):
    d = get(f"https://api.dexscreener.com/latest/dex/tokens/{tok['address']}")
    pairs = [p for p in d.get("pairs") or [] if p.get("chainId") == {"eth": "ethereum"}[tok["chain"]]]
    pairs.sort(key=lambda p: -(p.get("liquidity") or {}).get("usd", 0))
    return {"liq_usd": sum((p.get("liquidity") or {}).get("usd", 0) for p in pairs),
            "vol24_usd": sum((p.get("volume") or {}).get("h24", 0) for p in pairs),
            "top": [{"dex": p["dexId"], "pair": f"{p['baseToken']['symbol']}/{p['quoteToken']['symbol']}",
                     "liq": (p.get("liquidity") or {}).get("usd", 0), "vol24": (p.get("volume") or {}).get("h24", 0)} for p in pairs[:5]]}


def perp(sym):
    F = "https://fapi.binance.com"
    pi = get(f"{F}/fapi/v1/premiumIndex", symbol=sym)
    t24 = get(f"{F}/fapi/v1/ticker/24hr", symbol=sym)
    oih = get(f"{F}/futures/data/openInterestHist", symbol=sym, period="1h", limit=48)
    fr = get(f"{F}/fapi/v1/fundingRate", symbol=sym, limit=21)
    kl = get(f"{F}/fapi/v1/klines", symbol=sym, interval="1h", limit=24 * 7)
    return {"price": float(pi["markPrice"]), "funding": float(pi["lastFundingRate"]),
            "chg24": float(t24["priceChangePercent"]), "qvol24": float(t24["quoteVolume"]),
            "oi_hist": [[int(o["timestamp"]), float(o["sumOpenInterestValue"])] for o in oih],
            "funding_hist": [[int(f["fundingTime"]), float(f["fundingRate"])] for f in fr],
            "close_1h": [[int(k[0]), float(k[4])] for k in kl]}


def snapshot(tok):
    p = perp(tok["perp"])
    hs = holders(tok)
    supply = tok["supply"]
    by = {}
    for h in hs: by[h["cat"]] = by.get(h["cat"], 0) + h["bal"]
    unl = [h for h in hs if h["cat"] == "unlabeled"]
    trs, covered = big_transfers(tok, p["price"], tok["big_usd"])
    return {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "token": tok, "perp": p,
            "holders": hs, "holders_count": int(get(f"{BS[tok['chain']]}/tokens/{tok['address']}")["holders_count"]),
            "share": {"top10": sum(h["bal"] for h in hs[:10]) / supply, "top100": sum(h["bal"] for h in hs) / supply,
                      "by_cat": {k: v / supply for k, v in by.items()},
                      "top10_unlabeled": sum(h["bal"] for h in unl[:10]) / supply},
            "dex": dex(tok), "transfers": trs, "transfers_covered_h": covered}


if __name__ == "__main__":
    only = sys.argv[1:]
    for tok in TOKENS:
        if only and tok["symbol"] not in only: continue
        snap = snapshot(tok)
        d = HERE / "data" / tok["symbol"]; d.mkdir(parents=True, exist_ok=True)
        f = d / (snap["ts"].replace(":", "").replace("+0000", "Z") + ".json")
        f.write_text(json.dumps(snap, ensure_ascii=False))
        print(tok["symbol"], "ok", f.name, "持仓地址", snap["holders_count"], "大额转账", len(snap["transfers"]),
              f"覆盖 {snap['transfers_covered_h']}h")
