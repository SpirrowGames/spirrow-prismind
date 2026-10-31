# T02 runbook — ツール worker 詰まりの検知と自動 restart（{{HOST_SERVICES}}）

operator が本番ホストで実行する手順。`{{...}}` は [[platform:infra-registry]] の値に読み替える。結果は PR の該当欄（S1 / journald / テスト A / テスト B）に
**出力をそのまま**貼る。順番は 1 → 2 → 3 → 4 → 5。

背景: ツール本体は `ThreadPoolExecutor(max_workers=1)` 上で動く。外部呼び出しが 1 本返らないと、
後ろに並んだ `get_identity` などがすべて待たされる。それでもイベントループは生きているので、
watchdog・`tools/list`・従来の `/health` は応答を返し続け、3 層の監視をすべてすり抜ける（2026-09-14、
15.5 時間）。この PR で `/health` に `tool_executor` を足し、healthcheck は
`busy_seconds > --max-tool-busy`（既定 600 秒）を unhealthy とする。

---

## 1. S1 — 本番の現状確認（デプロイ前に行う）

```bash
systemctl cat spirrow-prismind.service spirrow-prismind-healthcheck.service spirrow-prismind-healthcheck.timer
systemctl list-timers
journalctl -u 'spirrow-prismind*' --since 2026-09-14 --until 2026-09-16 --no-pager
```

journal が永続化されているか:

```bash
systemd-analyze cat-config systemd/journald.conf | grep -Ei '^\s*(Storage|SystemMaxUse|MaxRetentionSec)='
ls -ld /var/log/journal
journalctl --disk-usage
```

判定:

- **永続**: `Storage=persistent`、または `Storage=auto`（既定値）で `/var/log/journal` がある。
  → 2 は飛ばす。PR に「journal は既に永続のため journald の設定は変更していない」と 1 行書く。
- **揮発**: `Storage=volatile`、または `Storage=auto` で `/var/log/journal` がない。
  → 2 を実行する。

第 3 層（healthcheck timer）が 9/14 時点で入っていなかったと分かっても、3 以降は省略しない。

## 2. journald を永続化する（S1 で揮発だった場合のみ）

上限なしの永続化は不可（msg-095）。`/etc/systemd/journald.conf` 本体は書き換えずに drop-in を足す。
ロールバックはこのファイルを消すだけで済む。

```bash
# 変更前の値を残す
systemd-analyze cat-config systemd/journald.conf > /tmp/journald-before.txt

sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/60-spirrow-persistent.conf >/dev/null <<'CONF'
# T02 (spirrow-prismind): keep the journal across reboots, with a ceiling.
# Applies to every unit on this host, not only prismind.
[Journal]
Storage=persistent
SystemMaxUse=4G
MaxRetentionSec=90day
CONF

# 反映には journald の再起動が要る（設定ファイルを置いただけでは効かない — msg-096）
sudo systemctl restart systemd-journald
sudo journalctl --flush

# 変更後の記録
systemd-analyze cat-config systemd/journald.conf > /tmp/journald-after.txt
diff -u /tmp/journald-before.txt /tmp/journald-after.txt
ls -ld /var/log/journal
journalctl --disk-usage
```

PR に貼るもの: `diff -u` の出力、変更後の `journalctl --disk-usage`、`/var/log/journal` があるか。

ロールバック:

```bash
sudo rm /etc/systemd/journald.conf.d/60-spirrow-persistent.conf
sudo systemctl restart systemd-journald
# /var/log/journal に溜まった過去分は残る。消すかどうかは別途判断する
```

## 3. デプロイ

コードの反映は `deploy/README.md` の手順どおり（`uv.lock` はこの PR で変わらない）。unit の反映:

```bash
cd {{PATH_SERVICES}}/spirrow-prismind
sudo cp deploy/spirrow-prismind-healthcheck.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart spirrow-prismind.service

# /health に tool_executor が出ていること（idle なら busy=false）
curl -s http://127.0.0.1:8112/health | python3 -m json.tool

# healthcheck を 1 回手で回し、新しい識別子で journal に出ること
sudo systemctl start spirrow-prismind-healthcheck.service
journalctl -t prismind-healthcheck -n 5 --no-pager
```

## 4. 実機テスト A — `kill -STOP` で本番プロセスを止める

本番が 1〜2 分止まる。利用の少ない時間に行う。

```bash
PID=$(systemctl show -p MainPID --value spirrow-prismind.service); echo "$PID"; date -Is
sudo kill -STOP "$PID"

# 3 分ほど待ってから
systemctl show -p MainPID --value spirrow-prismind.service    # 別の PID になっていること
# -u を 2 つ並べると OR になる（-u と -t の組み合わせは AND なので使わない）
journalctl -u spirrow-prismind.service -u spirrow-prismind-healthcheck.service --since "-10 min" --no-pager
```

PR に貼るもの: watchdog（`Watchdog timeout`、約 60 秒）と healthcheck の `RESTART_EVENT` の
どちらが先に restart したかが分かる journal の抜粋。watchdog が先なら healthcheck は
restart 後の健全なサーバを見るだけで、`RESTART_EVENT` が出ないのが正しい動き。

## 5. 実機テスト B — 9/14 型（ツール worker の詰まり）

本番とは別のインスタンスを transient unit で 8113 番に立て、memory backend を偽サーバに向ける。
偽サーバは `/health` にだけ即答し、それ以外は 5 秒ごとに 1 バイト返し続ける。httpx の
`timeout=10.0` は読み取り 1 回ごとの上限なので、いつまでもタイムアウトせず worker が塞がる。
**本番の unit・本番の config・本番コードには触らない。**

```bash
cd {{PATH_SERVICES}}/spirrow-prismind
PY={{PATH_SERVICES}}/spirrow-prismind/venv/bin/python
mkdir -p /tmp/prismind-hangtest

# (a) テスト用 config: 本番のコピーの memory 先だけを差し替える。ログはファイルに書かない
cp config.toml /tmp/prismind-hangtest/config.toml
sed -i -E \
  -e 's|^memory_server_url *=.*|memory_server_url = "http://127.0.0.1:18080"|' \
  -e 's|^memory_server_type *=.*|memory_server_type = "rest"|' \
  -e 's|^file *=.*|file = ""|' \
  /tmp/prismind-hangtest/config.toml
grep -E '^(memory_server_url|memory_server_type|file) *=' /tmp/prismind-hangtest/config.toml

# (b) 偽サーバ（別端末、または nohup）
nohup "$PY" deploy/hangtest/trickle_server.py --port 18080 --interval 5 \
  > /tmp/prismind-hangtest/trickle.log 2>&1 &
echo $! > /tmp/prismind-hangtest/trickle.pid

# (c) テスト用インスタンス
sudo systemd-run --unit=spirrow-prismind-hangtest \
  -p Type=notify -p NotifyAccess=main -p User={{USER_SERVICES}} \
  -p WorkingDirectory={{PATH_SERVICES}}/spirrow-prismind \
  -E PYTHONUNBUFFERED=1 -E PRISMIND_CONFIG=/tmp/prismind-hangtest/config.toml \
  "$PY" -m spirrow_prismind.server --transport sse --host 127.0.0.1 --port 8113
curl -s http://127.0.0.1:8113/health | python3 -m json.tool      # busy=false

# (d) memory を読むツールを 1 本投げて worker を塞ぐ（返ってこないのが正しい）
nohup "$PY" deploy/hangtest/call_tool.py --url http://127.0.0.1:8113/sse \
  get_identity '{"identity_name": "hangtest"}' > /tmp/prismind-hangtest/call.log 2>&1 &
echo $! > /tmp/prismind-hangtest/call.pid
sleep 40
curl -s http://127.0.0.1:8113/health | python3 -m json.tool      # busy=true, current_tool=get_identity, busy_seconds>30
"$PY" scripts/healthcheck.py --url http://127.0.0.1:8113/sse     # restart なし、報告だけ。tools/list は通る

# (e) 判定と restart。stamp は本番と分ける（本番の間引きに影響させない）
OLD=$(systemctl show -p MainPID --value spirrow-prismind-hangtest)
sudo systemd-cat -t prismind-healthcheck "$PY" scripts/healthcheck.py \
  --url http://127.0.0.1:8113/sse \
  --restart-unit spirrow-prismind-hangtest \
  --max-tool-busy 30 \
  --stamp /run/prismind-hangtest.stamp
NEW=$(systemctl show -p MainPID --value spirrow-prismind-hangtest); echo "$OLD -> $NEW"
journalctl -t prismind-healthcheck -g RESTART_EVENT --since "-15 min" --no-pager
```

期待する結果: `RESTART_EVENT` が 1 行出て、`"unit": "spirrow-prismind-hangtest"`,
`"reason": "tool_busy"`, `"current_tool": "get_identity"`, `"restarted": true`,
`"systemctl_rc": 0` になっていること。MainPID が変わっていること。
`OPERATOR_NOTICE` の行も同じ時刻に出る（composer への配線は別タスク、現状は journal のみ）。

片付け:

```bash
kill "$(cat /tmp/prismind-hangtest/call.pid)" "$(cat /tmp/prismind-hangtest/trickle.pid)"
sudo systemctl stop spirrow-prismind-hangtest
sudo rm -f /run/prismind-hangtest.stamp
rm -rf /tmp/prismind-hangtest
systemctl status spirrow-prismind-hangtest --no-pager   # not found / inactive であること
```

PR に貼るもの: (d) の 2 回目の `/health`、(e) の `OLD -> NEW` と `RESTART_EVENT` の行。

## restart 履歴の見方（DoD 4）

```bash
journalctl -t prismind-healthcheck -g RESTART_EVENT --no-pager
```

1 行が 1 回の restart、または間引きで見送った 1 回分（`"restarted": false`）。専用ファイルはない。
テスト B の行は `"unit": "spirrow-prismind-hangtest"` で区別できる。
