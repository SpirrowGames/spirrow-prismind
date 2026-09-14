# デプロイ (sg-ai-server-01)

`deploy/` 配下は本番 systemd unit の正本。ただし **動いている物の一次ソースは
`systemctl cat`**（過去に repo 内 unit のパスが実在しない状態で放置された前例が
あるため、必ず突き合わせる）。

## 構成

| unit | 役割 |
| --- | --- |
| `spirrow-prismind.service` | MCP サーバ本体。`--transport sse` で :8112 を**自分で** listen する |
| `spirrow-prismind-healthcheck.timer` | 2分ごとに `scripts/healthcheck.py` を実行 |
| `spirrow-prismind-healthcheck.service` | 上記の oneshot 実体。MCP レベルで詰まっていたら unit を restart |

多層になっているのは、それぞれ別の壊れ方を捕まえるため:

1. **プロセスが死ぬ** → `Restart=always`（SSE を自プロセスで持つようになったので、
   これが初めて意味を持つ。mcp-proxy 越しでは死ぬのが孫プロセスで発火しなかった）
2. **イベントループが固まる** → `WatchdogSec=60` + サーバ側からの `WATCHDOG=1` ping
3. **HTTP は応答するが MCP が壊れている** → healthcheck timer（`initialize` →
   `tools/list` まで実際に叩く）

## 反映手順

```bash
cd /home/sgadmin/services/spirrow/spirrow-prismind

sudo cp deploy/spirrow-prismind.service /etc/systemd/system/
sudo cp deploy/spirrow-prismind-healthcheck.service /etc/systemd/system/
sudo cp deploy/spirrow-prismind-healthcheck.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl restart spirrow-prismind.service
sudo systemctl enable --now spirrow-prismind-healthcheck.timer
```

## 検証

```bash
# 1. unit が notify で上がっている（Type=notify なので READY=1 が来るまで activating）
systemctl is-active spirrow-prismind.service

# 2. node/npx が居なくなり、python が直接 socket を持っている
systemctl status spirrow-prismind.service | sed -n '/CGroup/,+3p'
ss -ltnp | grep 8112          # 127.0.0.1:8112 で python であること

# 3. MCP が実際に応答する（HTTP 200 だけでは不十分、これが本番で騙された点）
venv/bin/python scripts/healthcheck.py --url http://127.0.0.1:8112/sse
curl -s http://127.0.0.1:8112/health | python3 -m json.tool

# 4. タイマーが回っている
systemctl list-timers spirrow-prismind-healthcheck.timer
```

## ロールバック

```bash
sudo systemctl disable --now spirrow-prismind-healthcheck.timer
# 旧構成に戻す場合は ExecStart を npx mcp-proxy 版に戻し Type=simple にする
# （= 本 PR が直した障害モードごと戻ることになる点に注意）
sudo systemctl daemon-reload && sudo systemctl restart spirrow-prismind.service
```
