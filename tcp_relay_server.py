import socket
import threading
import sys
import signal

class TCPRelayServer:
    def __init__(self, src_host, src_port, dst_host, dst_port):
        self.src_host = src_host
        self.src_port = src_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.server_socket = None
        self.upstream_socket = None
        self.client_sockets = []
        self.running = True

    def start(self):
        """リレーサーバを起動"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.dst_host, self.dst_port))
        self.server_socket.listen(5)

        print(f"Listening for clients on {self.dst_host}:{self.dst_port}...")

        # データソース（上流サーバ）に接続
        self.upstream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.upstream_socket.connect((self.src_host, self.src_port))
            print(f"Connected to upstream server {self.src_host}:{self.src_port}")
        except Exception as e:
            print(f"Failed to connect to upstream server: {e}")
            self.cleanup()
            sys.exit(1)

        # クライアント受付スレッド
        threading.Thread(target=self.accept_clients, daemon=True).start()

        # データ転送スレッド
        threading.Thread(target=self.relay_data, daemon=True).start()

        # 終了シグナルをキャッチ
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        # Windows 互換のメインループ
        try:
            while self.running:
                pass  # Windows では signal.pause() が使えないため、ループで待つ
        except KeyboardInterrupt:
            pass

        self.cleanup()

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

    def relay_data(self):
        """上流サーバからのデータを受信し、すべてのクライアントに転送"""
        while self.running:
            try:
                data = self.upstream_socket.recv(4096)
                if not data:
                    print("Upstream connection closed.")
                    break

                # すべてのクライアントに転送
                for client_socket in self.client_sockets[:]:
                    try:
                        client_socket.sendall(data)
                    except Exception:
                        print("Client disconnected.")
                        self.client_sockets.remove(client_socket)
                        client_socket.close()
            except Exception as e:
                print(f"Error receiving data from upstream: {e}")
                break

        # 🔥 上流サーバの接続を明示的に閉じる
        self.running = False
        self.cleanup()

    def handle_exit(self, signum, frame):
        """終了シグナルを処理"""
        print("Shutting down relay server...")
        self.running = False
        self.cleanup()

    def cleanup(self):
        """すべてのソケットをクリーンに閉じる"""
        print("Closing connections...")

        # クライアントの接続を閉じる
        for client_socket in self.client_sockets:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            client_socket.close()

        # 上流サーバとの接続を安全に閉じる
        if self.upstream_socket:
            try:
                self.upstream_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.upstream_socket.close()

        # サーバソケットを閉じる
        if self.server_socket:
            self.server_socket.close()

        print("Server shut down.")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <src_host:src_port> <dst_host:dst_port>")
        sys.exit(1)

    src_host, src_port = sys.argv[1].split(":")
    dst_host, dst_port = sys.argv[2].split(":")
    
    relay_server = TCPRelayServer(src_host, int(src_port), dst_host, int(dst_port))
    relay_server.start()
