import socket
import threading
import sys
import signal
import argparse
import time

class TCPRelayServer:
    def __init__(self, src_host, src_port, dst_host, dst_port, mode, dump=False, retry_interval=5):
        self.src_host = src_host
        self.src_port = src_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.mode = mode
        self.dump = dump  # True なら標準出力にダンプ
        self.retry_interval = retry_interval  # 再接続の間隔（秒）
        self.server_socket = None
        self.client_sockets = []
        self.upstream_socket = None
        self.downstream_socket = None
        self.running = True

    def start(self):
        """リレーサーバを起動"""
        print(f"Starting relay server in mode: {self.mode}")
        
        if self.mode in ["connect-listen", "connect-connect"]:
            threading.Thread(target=self.connect_upstream, daemon=True).start()
        
        if self.mode in ["listen-connect", "listen-listen"]:
            self.listen_upstream()

        if self.mode in ["connect-listen", "listen-listen"]:
            self.listen_clients()

        if self.mode in ["listen-connect", "connect-connect"]:
            threading.Thread(target=self.connect_downstream, daemon=True).start()

        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.cleanup()

    def connect_upstream(self):
        """ソース側に接続し、再接続機能を追加"""
        while self.running:
            try:
                self.upstream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.upstream_socket.connect((self.src_host, self.src_port))
                print(f"Connected to upstream {self.src_host}:{self.src_port}")
                self.relay_from_upstream()
            except Exception as e:
                print(f"Upstream connection failed: {e}, retrying in {self.retry_interval} seconds...")
                time.sleep(self.retry_interval)

    def listen_upstream(self):
        """ソース側が接続を待ち受ける"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.src_host, self.src_port))
        self.server_socket.listen(1)
        print(f"Listening for upstream connections on {self.src_host}:{self.src_port}")
        threading.Thread(target=self.accept_upstream, daemon=True).start()

    def accept_upstream(self):
        """上流サーバの接続を受け入れる"""
        while self.running:
            try:
                self.upstream_socket, addr = self.server_socket.accept()
                print(f"Upstream connected: {addr}")
                self.relay_from_upstream()
            except Exception as e:
                print(f"Error accepting upstream: {e}")

    def listen_clients(self):
        """デスティネーション側が接続を待ち受ける"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.dst_host, self.dst_port))
        self.server_socket.listen(5)
        print(f"Listening for clients on {self.dst_host}:{self.dst_port}...")
        threading.Thread(target=self.accept_clients, daemon=True).start()

    def accept_clients(self):
        """クライアントを受け入れ、リストに追加"""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"Client connected: {addr}")
                self.client_sockets.append(client_socket)
            except Exception as e:
                if self.running:
                    print(f"Error accepting client: {e}")

    def connect_downstream(self):
        """デスティネーション側に接続し、再接続機能を追加"""
        while self.running:
            try:
                self.downstream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.downstream_socket.connect((self.dst_host, self.dst_port))
                print(f"Connected to downstream {self.dst_host}:{self.dst_port}")
                self.relay_to_downstream()
            except Exception as e:
                print(f"Downstream connection failed: {e}, retrying in {self.retry_interval} seconds...")
                time.sleep(self.retry_interval)

    def relay_from_upstream(self):
        """上流からのデータを中継"""
        try:
            while self.running:
                data = self.upstream_socket.recv(4096)
                if not data:
                    print("Upstream connection closed, reconnecting...")
                    break

                if self.dump:
                    print(data.decode("utf-8", "ignore"))  # 標準出力にそのまま出力

                if self.mode in ["connect-listen", "listen-listen"]:
                    for client_socket in self.client_sockets[:]:
                        try:
                            client_socket.sendall(data)
                        except Exception:
                            self.client_sockets.remove(client_socket)
                            client_socket.close()

                if self.mode in ["listen-connect", "connect-connect"]:
                    if self.downstream_socket:
                        self.downstream_socket.sendall(data)
        except Exception as e:
            print(f"Error receiving data from upstream: {e}")

    def relay_to_downstream(self):
        """下流サーバからのデータを中継"""
        try:
            while self.running:
                data = self.downstream_socket.recv(4096)
                if not data:
                    print("Downstream connection closed, reconnecting...")
                    break

                if self.dump:
                    print(data.decode("utf-8", "ignore"))  # 標準出力にそのまま出力

                if self.upstream_socket:
                    self.upstream_socket.sendall(data)
        except Exception as e:
            print(f"Error receiving data from downstream: {e}")

    def handle_exit(self, signum, frame):
        """終了シグナルを処理"""
        print("Shutting down relay server...")
        self.running = False
        self.cleanup()

    def cleanup(self):
        """すべてのソケットをクリーンに閉じる"""
        print("Closing connections...")

        for client_socket in self.client_sockets:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            client_socket.close()
        self.client_sockets.clear()

        for sock in [self.upstream_socket, self.downstream_socket, self.server_socket]:
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                sock.close()

        print("Server shut down.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCP Relay Server with reconnect and dump")
    parser.add_argument("src", help="Source address (host:port)")
    parser.add_argument("dst", help="Destination address (host:port)")
    parser.add_argument("--mode", choices=["connect-listen", "listen-connect", "connect-connect", "listen-listen"], default="connect-listen", help="Connection mode")
    parser.add_argument("--dump", action="store_true", help="Dump transmitted data to stdout")

    args = parser.parse_args()
    src_host, src_port = args.src.split(":")
    dst_host, dst_port = args.dst.split(":")

    relay_server = TCPRelayServer(src_host, int(src_port), dst_host, int(dst_port), args.mode, args.dump)
    relay_server.start()
