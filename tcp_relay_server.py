import socket
import threading
import sys
import signal
import argparse
import time
import errno


class TCPRelayServer:
    """
    上流 → 下流 への一方向リレー。
    - mode:
        connect-listen : 上流に connect / 下流を listen（複数クライアント）
        listen-connect : 上流を listen / 下流に connect（1対1）
        connect-connect: 上下とも connect（1対1-1対1）
        listen-listen  : 上流を listen / 下流を listen（複数クライアント）
    """

    def __init__(self, src_host, src_port, dst_host, dst_port, mode,
                 dump=False, retry_interval=5):
        self.src_host = src_host
        self.src_port = src_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.mode = mode
        self.dump = dump
        self.retry_interval = retry_interval

        # 接続用ソケット
        self.upstream_socket = None       # 上流との 1 対 1
        self.downstream_socket = None     # connect-* のときの下流との 1 対 1
        self.client_sockets = []          # *-listen のときの複数クライアント

        # listen 用ソケット
        self.upstream_server_socket = None
        self.client_server_socket = None

        self.running = True
        self.client_lock = threading.Lock()

        # GUI / CUI 向け通知用コールバック
        self.on_upstream_status_change = None    # func(bool)
        self.on_downstream_status_change = None  # func(bool)
        self.on_client_count_change = None       # func(int)
        self.on_log = None                       # func(str)
        self.on_client_list_change = None        # func(list[str])

        self._cleaned = False

    # ---------------------------------------
    # ログ
    # ---------------------------------------
    def _log(self, msg: str):
        """通常ログ（GUIにもCUIにも流す）"""
        print(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _log_dump(self, text: str):
        """
        dump用のログ。
        - GUI（on_logあり）のとき：ターミナルには出さず GUI ログだけに出す
        - CUI（on_logなし）のとき：ターミナルにだけ出す
        """
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass
        else:
            print(text)

    # ---------------------------------------
    # 下流（listen 系）: クライアント数・一覧・状態を通知
    # ---------------------------------------
    def _notify_downstream_listen_state(self, reason: str = ""):
        """client_sockets の内容からクライアント数・状態・一覧を通知"""
        with self.client_lock:
            count = len(self.client_sockets)
            info_list = []
            for s in self.client_sockets:
                try:
                    addr, port = s.getpeername()
                    info_list.append(f"{addr}:{port}")
                except OSError:
                    # 切断済みの場合はここでは無視（送信時に掃除）
                    pass

        dbg = f"[DEBUG] listen-side state ({reason}) clients={count} [{', '.join(info_list)}]"
        print(dbg)
        if self.on_log:
            try:
                self.on_log(dbg)
            except Exception:
                pass

        if self.on_client_count_change:
            try:
                self.on_client_count_change(count)
            except Exception:
                pass

        if self.on_downstream_status_change:
            try:
                self.on_downstream_status_change(count > 0)
            except Exception:
                pass

        if self.on_client_list_change:
            try:
                self.on_client_list_change(info_list)
            except Exception:
                pass

    # ---------------------------------------
    # 下流（connect 系）: 1クライアント相当として状態通知
    # ---------------------------------------
    def _notify_downstream_connect_state(self, connected: bool, reason: str = ""):
        """connect-* モードのときのクライアント数・一覧・状態"""
        count = 1 if connected else 0
        info_list = []

        if connected and self.downstream_socket:
            try:
                addr, port = self.downstream_socket.getpeername()
                info_list.append(f"{addr}:{port}")
            except OSError:
                pass

        dbg = f"[DEBUG] connect-side state ({reason}) connected={connected} count={count} [{', '.join(info_list)}]"
        print(dbg)
        if self.on_log:
            try:
                self.on_log(dbg)
            except Exception:
                pass

        if self.on_client_count_change:
            try:
                self.on_client_count_change(count)
            except Exception:
                pass

        if self.on_downstream_status_change:
            try:
                self.on_downstream_status_change(connected)
            except Exception:
                pass

        if self.on_client_list_change:
            try:
                self.on_client_list_change(info_list)
            except Exception:
                pass

    # ---------------------------------------
    # メイン
    # ---------------------------------------
    def start(self):
        # 再起動に備えてリセット
        self.running = True
        self._cleaned = False

        self._log(f"Starting relay server in mode: {self.mode}")

        # 上流設定
        try:
            if self.mode in ["connect-listen", "connect-connect"]:
                self._log("[DEBUG] starting connect_upstream thread")
                threading.Thread(target=self.connect_upstream, daemon=True).start()

            if self.mode in ["listen-connect", "listen-listen"]:
                self._log(f"[DEBUG] trying to listen upstream on {self.src_host}:{self.src_port}")
                self._listen_upstream_or_die()
        except OSError as e:
            self._log(
                f"ERROR: failed to set up upstream on {self.src_host}:{self.src_port}: {e}. "
                f"Server will not start."
            )
            self.running = False

        # 下流設定
        if self.running:
            try:
                if self.mode in ["connect-listen", "listen-listen"]:
                    self._log(f"[DEBUG] trying to listen downstream (clients) on {self.dst_host}:{self.dst_port}")
                    self._listen_clients_or_die()

                if self.mode in ["listen-connect", "connect-connect"]:
                    self._log("[DEBUG] starting connect_downstream thread")
                    threading.Thread(target=self.connect_downstream, daemon=True).start()
            except OSError as e:
                self._log(
                    f"ERROR: failed to set up downstream on {self.dst_host}:{self.dst_port}: {e}. "
                    f"Server will not start."
                )
                self.running = False

        # メインループ
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    # ---------------------------------------
    # 上流 connect
    # ---------------------------------------
    def connect_upstream(self):
        while self.running:
            s = None
            try:
                self._log(f"[DEBUG] connect_upstream: trying {self.src_host}:{self.src_port}")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # 接続試行がブロックされるのを防ぐためタイムアウトを設定
                s.settimeout(self.retry_interval)
                s.connect((self.src_host, self.src_port))
                s.settimeout(None) # 接続後はブロックモードに戻す
                self.upstream_socket = s

                self._log(f"Connected to upstream {self.src_host}:{self.src_port}")
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(True)
                    except Exception:
                        pass

                self.relay_from_upstream()

            except OSError as e:
                if not self.running:
                    # 停止中に出たエラーは無視
                    break

                if e.errno == errno.EADDRINUSE:
                    self._log(
                        f"ERROR: upstream connect local port already in use "
                        f"({self.src_host}:{self.src_port}): {e}. Stopping relay server."
                    )
                    self.running = False
                    break

                self._log(
                    f"Upstream connection failed: {e}, retrying in {self.retry_interval} seconds..."
                )
                time.sleep(self.retry_interval)

            except Exception as e:
                if not self.running:
                    break
                self._log(f"Upstream connection failed (unexpected): {e}")
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
                self._log("[DEBUG] connect_upstream: disconnected, loop end or retry")

    # ---------------------------------------
    # 上流 listen
    # ---------------------------------------
    def _listen_upstream_or_die(self):
        """上流を listen。失敗したら例外を投げて start() 側で止める。"""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self.src_host, self.src_port))
            srv.listen(1)
        except OSError:
            srv.close()
            raise
        self.upstream_server_socket = srv

        self._log(f"Listening for upstream connections on {self.src_host}:{self.src_port}")
        threading.Thread(target=self._accept_upstream_loop, daemon=True).start()

    def _accept_upstream_loop(self):
        while self.running:
            try:
                self._log("[DEBUG] waiting for upstream accept...")
                sock, addr = self.upstream_server_socket.accept()
                self._log(f"Upstream connected: {addr}")
                
                # 既存の接続があれば強制的に閉じる (listen-connect/listen-listen モードは1対1の upstream)
                if self.upstream_socket:
                    self._log("[DEBUG] closing previous upstream connection")
                    try:
                        self.upstream_socket.close()
                    except Exception:
                        pass
                
                self.upstream_socket = sock
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(True)
                    except Exception:
                        pass

                self.relay_from_upstream()
            except OSError as e:
                if not self.running:
                    break
                self._log(f"Error accepting upstream: {e}")
            except Exception as e:
                if not self.running:
                    break
                self._log(f"Error accepting upstream (unexpected): {e}")
            finally:
                if self.upstream_socket is sock:
                    self.upstream_socket = None
                
                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(False)
                    except Exception:
                        pass
                self._log("[DEBUG] upstream accept loop: upstream disconnected")

    # ---------------------------------------
    # 下流 listen（複数クライアント）
    # ---------------------------------------
    def _listen_clients_or_die(self):
        """下流クライアントを listen。失敗したら例外を投げて start() 側で止める。"""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((self.dst_host, self.dst_port))
            srv.listen(5)
        except OSError:
            srv.close()
            raise
        self.client_server_socket = srv

        self._log(f"Listening for clients on {self.dst_host}:{self.dst_port}...")
        threading.Thread(target=self._accept_clients_loop, daemon=True).start()

    def _accept_clients_loop(self):
        while self.running:
            try:
                self._log("[DEBUG] waiting for downstream client accept...")
                client_socket, addr = self.client_server_socket.accept()
                self._log(f"Client connected: {addr}")

                with self.client_lock:
                    self.client_sockets.append(client_socket)
                    dbg = f"[DEBUG] client_sockets append: now {len(self.client_sockets)}"
                    print(dbg)
                    if self.on_log:
                        try:
                            self.on_log(dbg)
                        except Exception:
                            pass

                self._notify_downstream_listen_state(reason="accept")
            except OSError as e:
                if not self.running:
                    break
                self._log(f"Error accepting client: {e}")
            except Exception as e:
                if not self.running:
                    break
                self._log(f"Error accepting client (unexpected): {e}")

    # ---------------------------------------
    # 下流 connect（1対1）
    # ---------------------------------------
    def connect_downstream(self):
        while self.running:
            s = None
            try:
                self._log(f"[DEBUG] connect_downstream: trying {self.dst_host}:{self.dst_port}")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # 接続試行がブロックされるのを防ぐためタイムアウトを設定
                s.settimeout(self.retry_interval)
                s.connect((self.dst_host, self.dst_port))
                s.settimeout(None) # 接続後はブロックモードに戻す
                self.downstream_socket = s

                self._log(f"Connected to downstream {self.dst_host}:{self.dst_port}")
                self._notify_downstream_connect_state(True, reason="connect_downstream_connected")

                # 接続維持ループ: 接続が切断されるまで待機する
                while self.running and self.downstream_socket is s:
                    try:
                        # ゼロバイト受信 (MSG_PEEK) を試みて接続状態を確認
                        s.settimeout(0.5) # 一時的に短いタイムアウトを設定
                        # データを消費せず、ソケットが切れたかをチェックする
                        data = s.recv(1, socket.MSG_PEEK) 
                        s.settimeout(None) # ブロックモードに戻す

                        if data == b'':
                            # 0バイトのデータ受信は接続が正常に切断されたことを示す
                            self._log("[DEBUG] Downstream socket detected closed (recv(1) peek returned empty).")
                            break
                        
                        # データが届いている場合は無視（一方向リレーのため）
                        time.sleep(0.1) # サーバー負荷軽減のため短い待機

                    except socket.timeout:
                        # データが来ていないだけなので継続
                        continue
                    except OSError as e:
                        # 接続が切れたことによるエラー
                        self._log(f"[DEBUG] Downstream socket detected error: {e}")
                        break
                    except Exception as e:
                        self._log(f"[DEBUG] Downstream socket check failed (unexpected): {e}")
                        break

            except OSError as e:
                if not self.running:
                    break

                if e.errno == errno.EADDRINUSE:
                    self._log(
                        f"ERROR: downstream connect local port already in use "
                        f"({self.dst_host}:{self.dst_port}): {e}. Stopping relay server."
                    )
                    self.running = False
                    break

                self._log(
                    f"Downstream connection failed: {e}, retrying in {self.retry_interval} seconds..."
                )
                time.sleep(self.retry_interval)

            except Exception as e:
                if not self.running:
                    break
                self._log(f"Downstream connection failed (unexpected): {e}")
                time.sleep(self.retry_interval)

            finally:
                if self.downstream_socket is s:
                    try:
                        s.close()
                    except Exception:
                        pass
                    self.downstream_socket = None
                    self._notify_downstream_connect_state(False, reason="connect_downstream_disconnected")
                    self._log("[DEBUG] connect_downstream: disconnected, loop end or retry")

    # ---------------------------------------
    # 中継（上流 → 下流）
    # ---------------------------------------
    def relay_from_upstream(self):
        try:
            while self.running and self.upstream_socket:
                try:
                    data = self.upstream_socket.recv(4096)
                except OSError as e:
                    if not self.running:
                        # 終了処理中の recv エラーは無視
                        break
                    self._log(f"Error receiving data from upstream (OSError): {e}")
                    break

                if not data:
                    self._log("Upstream connection closed.")
                    if self.on_upstream_status_change:
                        try:
                            self.on_upstream_status_change(False)
                        except Exception:
                            pass
                    break

                self._log(f"[DEBUG] relay_from_upstream: received {len(data)} bytes")

                if self.dump:
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        text = repr(data)
                    self._log_dump(text)

                # 下流が listen 側（複数クライアント）
                if self.mode in ["connect-listen", "listen-listen"]:
                    with self.client_lock:
                        targets = list(self.client_sockets)

                    self._log(f"[DEBUG] relay_from_upstream: broadcasting to {len(targets)} clients")

                    dead = []
                    for s in targets:
                        try:
                            s.sendall(data)
                        except Exception as e:
                            try:
                                addr, port = s.getpeername()
                                self._log(f"Error sending to client {addr}:{port}: {e}")
                            except OSError:
                                self._log(f"Error sending to client <unknown>: {e}")
                            dead.append(s)

                    if dead:
                        with self.client_lock:
                            for s in dead:
                                try:
                                    self.client_sockets.remove(s)
                                    self._log("[DEBUG] client_sockets remove dead client")
                                except ValueError:
                                    pass
                                try:
                                    s.close()
                                except Exception:
                                    pass
                        self._notify_downstream_listen_state(reason="send_error")

                # 下流が connect 側（1 対 1）
                if self.mode in ["listen-connect", "connect-connect"]:
                    if self.downstream_socket:
                        try:
                            self.downstream_socket.sendall(data)
                            self._log("[DEBUG] relay_from_upstream: sent to downstream (connect-side)")
                        except Exception as e:
                            self._log(f"Error sending to downstream: {e}")
                            try:
                                self.downstream_socket.close()
                            except Exception:
                                pass
                            self.downstream_socket = None
                            self._notify_downstream_connect_state(False, reason="send_error")

        except Exception as e:
            if self.running:
                self._log(f"Error receiving data from upstream: {e}")

    # ---------------------------------------
    # 終了処理
    # ---------------------------------------
    def handle_exit(self, signum=None, frame=None):
        """GUIやシグナルから呼ぶ。ここでは running=False にするだけ。"""
        self._log("Shutting down relay server (handle_exit)...")
        self.running = False

    def cleanup(self):
        """start() の finally から一度だけ呼ばれる想定。"""
        if self._cleaned:
            return
        self._cleaned = True

        self._log("Closing connections...")

        # クライアントソケット
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

        # listen / connect ソケット
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

        # 状態リセット通知
        if self.mode in ["connect-listen", "listen-listen"]:
            self._notify_downstream_listen_state(reason="cleanup")
        else:
            self._notify_downstream_connect_state(False, reason="cleanup")

        if self.on_upstream_status_change:
            try:
                self.on_upstream_status_change(False)
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
    try:
        src_host, src_port = args.src.split(":")
        dst_host, dst_port = args.dst.split(":")
    except ValueError:
        print("Error: Source and Destination must be in the format host:port")
        sys.exit(1)


    relay_server = TCPRelayServer(
        src_host, int(src_port),
        dst_host, int(dst_port),
        args.mode,
        dump=args.dump,
        retry_interval=args.retry,
    )

    signal.signal(signal.SIGINT, relay_server.handle_exit)
    # SIGTERM は Windowsでは使えないため、Linux/macOS向け
    try:
        signal.signal(signal.SIGTERM, relay_server.handle_exit)
    except ValueError:
        pass # Windowsでは無視する

    relay_server.start()


if __name__ == "__main__":
    main()