# TCP Relay Server

## English

### Overview
TCP Relay Server forwards upstream traffic to a downstream destination in a single direction. It offers four connection modes, automatic reconnection, optional data dumping, and a GUI for operating multiple relays in parallel.

**Note:** Only one-way flows (upstream -> downstream) are supported. Bidirectional relaying is not implemented.

### Features
- Four relay modes: `connect-listen`, `listen-connect`, `connect-connect`, `listen-listen`
- Automatic reconnection when a link drops (`--retry` seconds, default 5)
- Multiple downstream clients in `connect-listen` and `listen-listen` modes
- Optional payload dump to stdout/log area (`--dump` or GUI checkbox)
- GUI with multi-tab management and auto-saved settings

### Requirements
- Python 3.x
- tkinter (bundled with standard Python; already included in the packaged GUI binary)

### Installation
1. Clone the repository:
   ```sh
   git clone https://github.com/tanaka-ryuya/TCPRelayServer.git
   cd TCPRelayServer
   ```
2. (Optional) Create a virtual environment:
   ```sh
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
3. No extra pip packages are required for the CLI or GUI.

### CLI Usage
Run `tcp_relay_server.py` (or `dist\\tcp_relay_server.exe`) with the required endpoints:
```sh
python tcp_relay_server.py <src_host>:<src_port> <dst_host>:<dst_port> --mode <mode> [--dump] [--retry <seconds>]
```

Arguments:
- `<src_host>:<src_port>`: Upstream source to read from
- `<dst_host>:<dst_port>`: Downstream destination to write to
- `--mode`: One of `connect-listen`, `listen-connect`, `connect-connect`, `listen-listen` (default: `connect-listen`)
- `--dump`: Print relayed data
- `--retry <seconds>`: Reconnect interval (default: 5)

### GUI Usage
- From source: `python relay_gui.py`
- Packaged binary: `dist\\relay_gui.exe`

Operation per tab:
1. Set upstream host/port and downstream host/port.
2. Choose mode and (optional) enable "dump to log".
3. Set reconnect interval seconds.
4. Click `Start` to run / `Stop` to halt the relay for that tab.
5. Use the `+` button to add another tab (defaults chain from the previous tab). Right-click a tab header or use the `タブを閉じる` button to remove it.

Configuration is automatically saved to `relay_gui_config.json` on exit and loaded on the next start. Logs and connection status are shown in each tab.

### License
MIT License

### Author
[TANAKA RYUYA](https://github.com/tanaka-ryuya/TCPRelayServer)

---

## 日本語

### 概要
TCP Relay Server は、上流から下流への一方向通信を中継する Python 製ツールです。4 種類の接続モード、切断時の自動再接続、データダンプ、複数タブを扱える GUI を備えています。

**注意:** 上流 -> 下流 の一方向のみ対応です。双方向リレーは非対応です。

### 特長
- 接続モード: `connect-listen` / `listen-connect` / `connect-connect` / `listen-listen`
- 切断時の自動再接続（`--retry` 秒、デフォルト 5 秒）
- `connect-listen` と `listen-listen` では複数クライアントを受け付け
- 送信データのダンプ表示（`--dump` または GUI のチェック）
- GUI 版で複数タブ管理と設定の自動保存

### 必要要件
- Python 3.x
- tkinter（標準同梱。GUI の exe 版にも含まれます）

### セットアップ
1. リポジトリを取得:
   ```sh
   git clone https://github.com/tanaka-ryuya/TCPRelayServer.git
   cd TCPRelayServer
   ```
2. （任意）仮想環境を作成:
   ```sh
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
3. 追加ライブラリのインストールは不要です。

### CLI の使い方
`tcp_relay_server.py`（または `dist\\tcp_relay_server.exe`）を次のように実行します:
```sh
python tcp_relay_server.py <上流ホスト>:<上流ポート> <下流ホスト>:<下流ポート> --mode <モード> [--dump] [--retry 秒]
```

引数:
- `<上流ホスト>:<上流ポート>`: データを受け取る上流側
- `<下流ホスト>:<下流ポート>`: データを届ける下流側
- `--mode`: `connect-listen` / `listen-connect` / `connect-connect` / `listen-listen`（デフォルト: `connect-listen`）
- `--dump`: 送信データを標準出力に表示
- `--retry 秒`: 再接続までの待ち時間（デフォルト 5 秒）

### GUI の使い方
- ソースから起動: `python relay_gui.py`
- 同梱バイナリ: `dist\\relay_gui.exe`

各タブの操作手順:
1. 上流/下流のホスト・ポートを設定。
2. モードを選択し、必要なら「dump to log」をオン。
3. 再接続間隔（秒）を入力。
4. `Start` で中継開始、`Stop` で停止。
5. `+` ボタンでタブを追加（直前タブの設定を元に自動補完）。タブヘッダーを右クリック、または「タブを閉じる」ボタンでタブを削除。

設定は終了時に `relay_gui_config.json` に自動保存され、次回起動時に読み込まれます。ログと接続状態はタブ内で確認できます。

### ライセンス
MIT License

### 作者
[TANAKA RYUYA](https://github.com/tanaka-ryuya/TCPRelayServer)
