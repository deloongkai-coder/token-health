#!/bin/bash
# 每小时: 采集 → 渲染 → 发布到 docs/ (GitHub Pages) → 推送。失败不推送。
set -e
cd "$(dirname "$0")"
python3 collect.py
python3 render.py
mkdir -p docs && cp out/*.html docs/
python3 - <<'PY'
import json
toks = json.load(open("tokens.json"))
items = "".join(f'<li><a href="{t["symbol"]}.html">{t["symbol"]}</a> · {t["project"]}</li>' for t in toks)
open("docs/index.html", "w").write(f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>代币健康度看板 · Kai</title><style>body{{background:#0e1116;color:#ece6da;font:16px -apple-system,"PingFang SC",sans-serif;max-width:720px;margin:60px auto;padding:0 20px}}a{{color:#3987e5}}li{{margin:8px 0}}</style><h1>代币健康度看板</h1><p>链上持仓 + 交易所数据, 每小时更新。只呈现公开数据, 不构成投资建议。</p><ul>{items}</ul><p style="color:#7c8088">Kai · DELOONG KACHMO PTE. LTD. · Singapore</p>')
PY
git add docs
if ! git diff --cached --quiet; then
  git commit -q -m "update $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -q origin main
fi
