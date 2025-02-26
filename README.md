<details open>
  <summary>🇺🇸 English</summary>

  # TCP Relay Server

  ## Overview
  The **TCP Relay Server** is a Python-based TCP relay tool that allows forwarding data between a source and a destination. It supports multiple modes, automatic reconnection, and optional data dumping for debugging.

  **Note:** This relay server only supports protocols where data is unidirectionally transmitted from the source to the destination. Bidirectional communication is not supported.

  ## Features
  - Supports **four relay modes**:
    - `connect-listen`: Connect to an upstream server and listen for downstream clients.
    - `listen-connect`: Listen for an upstream connection and connect to a downstream server.
    - `connect-connect`: Connect to both upstream and downstream servers.
    - `listen-listen`: Listen for both upstream and downstream connections.
  - **Automatic reconnection** when a connection is lost.
  - **Multiple client support** in `connect-listen` and `listen-listen` modes.
  - **Data dumping** option to output transmitted data to stdout.
  - **Graceful shutdown** using signal handling.

  ## Requirements
  - Python 3.x

  ## Installation
  Clone the repository and install any required dependencies if necessary:
  ```sh
  $ git clone https://github.com/yourrepo/tcp-relay-server.git
  $ cd tcp-relay-server
  ```
  <button onclick="navigator.clipboard.writeText('$ git clone https://github.com/yourrepo/tcp-relay-server.git\n$ cd tcp-relay-server')">Copy</button>

  ## Usage
  Run the relay server with the required parameters:
  ```sh
  $ python relay_server.py <source_address>:<source_port> <destination_address>:<destination_port> --mode <mode> [--dump]
  ```
  <button onclick="navigator.clipboard.writeText('$ python relay_server.py <source_address>:<source_port> <destination_address>:<destination_port> --mode <mode> [--dump]')">Copy</button>

  ### Arguments
  | Argument | Description |
  |----------|-------------|
  | `<source_address>:<source_port>` | The address and port of the upstream source. |
  | `<destination_address>:<destination_port>` | The address and port of the downstream destination. |
  | `--mode` | Relay mode (one of `connect-listen`, `listen-connect`, `connect-connect`, `listen-listen`). Default: `connect-listen`. |
  | `--dump` | Optional. Prints relayed data to stdout. |

  ## Signal Handling
  The relay server can be stopped gracefully using:
  - `CTRL+C` (SIGINT)
  - `kill <PID>` (SIGTERM)

  Upon termination, all sockets will be closed properly.

  ## License
  MIT License

  ## Author
  [TANAKA RYUYA](https://github.com/tanaka-ryuya/TCPRelayServer)

</details>

<details>
  <summary>🇯🇵 日本語</summary>

  # TCPリレーサーバ

  ## 概要
  **TCPリレーサーバ** は、PythonベースのTCPリレーツールで、データを送受信する際にソースと宛先の間を中継します。複数のモード、自動再接続、デバッグ用のデータダンプオプションをサポートしています。

  **注意:** 本リレーサーバは、ソースからデスティネーションへ一方向にデータを送り続けるプロトコルのみをサポートしています。双方向通信には対応していません。

  ## 特徴
  - **4つのリレーモード** をサポート:
    - `connect-listen`: 上流のサーバに接続し、下流のクライアントを待機。
    - `listen-connect`: 上流の接続を待機し、下流のサーバへ接続。
    - `connect-connect`: 上流・下流の両方のサーバに接続。
    - `listen-listen`: 上流・下流の両方の接続を待機。
  - **自動再接続** により、接続が切れても再接続。
  - `connect-listen` と `listen-listen` モードでは**複数のクライアント** をサポート。
  - **データダンプ** オプションで送受信データを標準出力に表示可能。
  - **シグナル処理** による安全なシャットダウン。

  ## 必要環境
  - Python 3.x

  ## インストール
  リポジトリをクローンし、必要な依存関係をインストールします。
  ```sh
  $ git clone https://github.com/yourrepo/tcp-relay-server.git
  $ cd tcp-relay-server
  ```
  <button onclick="navigator.clipboard.writeText('$ git clone https://github.com/yourrepo/tcp-relay-server.git\n$ cd tcp-relay-server')">Copy</button>

  ## 使い方
  必要なパラメータを指定してリレーサーバを実行:
  ```sh
  $ python relay_server.py <source_address>:<source_port> <destination_address>:<destination_port> --mode <mode> [--dump]
  ```
  <button onclick="navigator.clipboard.writeText('$ python relay_server.py <source_address>:<source_port> <destination_address>:<destination_port> --mode <mode> [--dump]')">Copy</button>

  ## シグナル処理
  サーバは以下の方法で安全に停止できます:
  - `CTRL+C` (SIGINT)
  - `kill <PID>` (SIGTERM)

  停止時にすべてのソケットが適切に閉じられます。

  ## ライセンス
  MIT License

  ## 作者
  [TANAKA RYUYA](https://github.com/tanaka-ryuya/TCPRelayServer)

</details>

