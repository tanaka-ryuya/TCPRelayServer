import socket
import threading
import sys
import signal
import argparse
import time


class TCPRelayServer:
    def __init__(self, src_host, src_port, dst_host, dst_port, mode,
                 dump=False, retry_interval=5):
        self.src_host = src_host
        self.src_port = src_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.mode = mode
        self.dump = dump  # True なら標準出力にダンプ
        self.retry_interval = retry_interval  # 再接続の間隔（秒）

        # 通信ソケット
        self.upstream_socket = None          # 上流との 1 対 1
        self.downstream_socket = None        # connect-* のときの下流との 1 対 1
        self.client_sockets = []             # *-listen のときの複数クライアント

        # 待ち受け用ソケット（listen-listen 用に分離）
        self.upstream_server_socket = None
        self.client_server_socket = None

        self.running = True
        self.client_lock = threading.Lock()

        # コールバック（GUIなどから差し込む用・CUIでは基本 None のまま）
        self.on_upstream_status_change = None    # func(connected: bool)
        self.on_downstream_status_change = None  # func(connected: bool)
        self.on_client_count_change = None       # func(count: int)
        self.on_log = None                       # func(message: str)

    # ========================
    # ログヘルパ
    # ========================
    def _log(self, msg: str):
        print(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    # ========================
    # メインループ
    # ========================
    def start(self):
        """リレーサーバを起動"""
        self._log(f"Starting relay server in mode: {self.mode}")

        # 上流側：connect か listen か
        if self.mode in ["connect-listen", "connect-connect"]:
            threading.Thread(target=self.connect_upstream, daemon=True).start()

        if self.mode in ["listen-connect", "listen-listen"]:
            self.listen_upstream()

        # 下流側：connect か listen か
        if self.mode in ["connect-listen", "listen-listen"]:
            self.listen_clients()

        if self.mode in ["listen-connect", "connect-connect"]:
            threading.Thread(target=self.connect_downstream, daemon=True).start()

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.cleanup()

    # ========================
    # 上流側（ソース）
    # ========================
    def connect_upstream(self):
        """上流にクライアントとして接続し、切れたら再接続"""
        while self.running:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.src_host, self.src_port))
                self.upstream_socket = s
                self._log(f"Connected to upstream {self.src_host}:{self.src_port}")
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(True)
                    except Exception:
                        pass

                # 上流からの受信をひたすら中継（一方向）
                self.relay_from_upstream()
            except Exception as e:
                self._log(f"Upstream connection failed: {e}, retrying in {self.retry_interval} seconds...")
                time.sleep(self.retry_interval)
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
                self.upstream_socket = None
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(False)
                    except Exception:
                        pass

    def listen_upstream(self):
        """上流側からの接続を待ち受け"""
        self.upstream_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.upstream_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.upstream_server_socket.bind((self.src_host, self.src_port))
        self.upstream_server_socket.listen(1)
        self._log(f"Listening for upstream connections on {self.src_host}:{self.src_port}")
        threading.Thread(target=self.accept_upstream, daemon=True).start()

    def accept_upstream(self):
        """上流クライアントの接続を受け入れ"""
        while self.running:
            try:
                sock, addr = self.upstream_server_socket.accept()
                self._log(f"Upstream connected: {addr}")
                self.upstream_socket = sock
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(True)
                    except Exception:
                        pass
                self.relay_from_upstream()
            except Exception as e:
                if self.running:
                    self._log(f"Error accepting upstream: {e}")
            finally:
                # relay_from_upstream が抜けてきたとき
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(False)
                    except Exception:
                        pass

    # ========================
    # 下流側（シンク）
    # ========================
    def listen_clients(self):
        """下流クライアント（複数）を待ち受け"""
        self.client_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.client_server_socket.bind((self.dst_host, self.dst_port))
        self.client_server_socket.listen(5)
        self._log(f"Listening for clients on {self.dst_host}:{self.dst_port}...")
        threading.Thread(target=self.accept_clients, daemon=True).start()

    def accept_clients(self):
        """クライアントを受け入れ、リストに追加"""
        while self.running:
            try:
                client_socket, addr = self.client_server_socket.accept()
                self._log(f"Client connected: {addr}")
                with self.client_lock:
                    self.client_sockets.append(client_socket)
                    if self.on_client_count_change:
                        try:
                            self.on_client_count_change(len(self.client_sockets))
                        except Exception:
                            pass
            except Exception as e:
                if self.running:
                    self._log(f"Error accepting client: {e}")

    def connect_downstream(self):
        """下流へクライアントとして接続（受信はしない、送信用のみ）"""
        while self.running:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.dst_host, self.dst_port))
                self.downstream_socket = s
                self._log(f"Connected to downstream {self.dst_host}:{self.dst_port}")
                if self.on_downstream_status_change:
                    try:
                        self.on_downstream_status_change(True)
                    except Exception:
                        pass

                # 一方向なのでここでは recv はしない
                while self.running:
                    time.sleep(1)
            except Exception as e:
                self._log(f"Downstream connection failed: {e}, retrying in {self.retry_interval} seconds...")
                time.sleep(self.retry_interval)
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
                self.downstream_socket = None
                if self.on_downstream_status_change:
                    try:
                        self.on_downstream_status_change(False)
                    except Exception:
                        pass

    # ========================
    # 中継処理（上流 → 下流のみ）
    # ========================
    def relay_from_upstream(self):
        """上流からのデータを下流へ一方向に中継"""
        try:
            while self.running and self.upstream_socket:
                data = self.upstream_socket.recv(4096)
                if not data:
                    self._log("Upstream connection closed, reconnecting...")
                    if self.on_upstream_status_change:
                        try:
                            self.on_upstream_status_change(False)
                        except Exception:
                            pass
                    break

                if self.dump:
                    # テキストっぽいならそのまま、ダメなら repr
                    try:
                        self._log(data.decode("utf-8"))
                    except UnicodeDecodeError:
                        self._log(repr(data))

                # 下流が listen 側（複数クライアント）
                if self.mode in ["connect-listen", "listen-listen"]:
                    with self.client_lock:
                        for client_socket in self.client_sockets[:]:
                            try:
                                client_socket.sendall(data)
                            except Exception:
                                # 送信できなければ切断扱い
                                self.client_sockets.remove(client_socket)
                                try:
                                    client_socket.close()
                                except Exception:
                                    pass
                                if self.on_client_count_change:
                                    try:
                                        self.on_client_count_change(len(self.client_sockets))
                                    except Exception:
                                        pass

                # 下流が connect 側（1 対 1）
                if self.mode in ["listen-connect", "connect-connect"]:
                    if self.downstream_socket:
                        try:
                            self.downstream_socket.sendall(data)
                        except Exception as e:
                            self._log(f"Error sending to downstream: {e}")
                            try:
                                self.downstream_socket.close()
                            except Exception:
                                pass
                            self.downstream_socket = None
                            if self.on_downstream_status_change:
                                try:
                                    self.on_downstream_status_change(False)
                                except Exception:
                                    pass
        except Exception as e:
            self._log(f"Error receiving data from upstream: {e}")

    # ========================
    # 終了処理
    # ========================
    def handle_exit(self, signum=None, frame=None):
        """終了シグナルを処理"""
        self._log("Shutting down relay server...")
        self.running = False
        self.cleanup()

    def cleanup(self):
        """すべてのソケットをクリーンに閉じる"""
        self._log("Closing connections...")

        with self.client_lock:
            for client_socket in self.client_sockets:
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    client_socket.close()
                except Exception:
                    pass
            self.client_sockets.clear()
            if self.on_client_count_change:
                try:
                    self.on_client_count_change(0)
                except Exception:
                    pass

        for sock in [
            self.upstream_socket,
            self.downstream_socket,
            self.upstream_server_socket,
            self.client_server_socket,
        ]:
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass

        self._log("Server shut down.")


def main():
    parser = argparse.ArgumentParser(description="TCP Relay Server (one-way: upstream -> downstream)")
    parser.add_argument("src", help="Source address (host:port)")
    parser.add_argument("dst", help="Destination address (host:port)")
    parser.add_argument(
        "--mode",
        choices=["connect-listen", "listen-connect", "connect-connect", "listen-listen"],
        default="connect-listen",
        help="Connection mode",
    )
    parser.add_argument("--dump", action="store_true", help="Dump transmitted data to stdout")
    parser.add_argument("--retry", type=int, default=5, help="Reconnect interval in seconds")

    args = parser.parse_args()
    src_host, src_port = args.src.split(":")
    dst_host, dst_port = args.dst.split(":")

    relay_server = TCPRelayServer(
        src_host, int(src_port),
        dst_host, int(dst_port),
        args.mode,
        dump=args.dump,
        retry_interval=args.retry,
    )

    # シグナルハンドラはメインスレッド側で登録
    signal.signal(signal.SIGINT, relay_server.handle_exit)
    signal.signal(signal.SIGTERM, relay_server.handle_exit)

    relay_server.start()


if __name__ == "__main__":
    main()
