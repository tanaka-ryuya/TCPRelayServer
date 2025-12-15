import socket
import threading
import sys
import signal
import argparse
import time
import errno


class TCPRelayServer:
    """
    One-way relay from upstream -> downstream.
    - mode:
        connect-listen : connect to upstream / listen for downstream clients
        listen-connect : listen for upstream / connect to downstream (1:1)
        connect-connect: connect to upstream and downstream (1:1)
        listen-listen  : listen for upstream and downstream (multi-clients)
    """

    def __init__(self, src_host, src_port, dst_host, dst_port, mode, dump=False, retry_interval=5):
        self.src_host = src_host
        self.src_port = src_port
        self.dst_host = dst_host
        self.dst_port = dst_port
        self.mode = mode
        self.dump = dump
        self.retry_interval = retry_interval

        # Sockets for connections
        self.upstream_socket = None       # 1:1 with upstream
        self.downstream_socket = None     # 1:1 with downstream for connect-* modes
        self.client_sockets = []          # multiple downstream clients for *-listen modes

        # Listen sockets
        self.upstream_server_socket = None
        self.client_server_socket = None

        self.running = True
        self.client_lock = threading.Lock()

        # Callbacks for GUI / CLI
        self.on_upstream_status_change = None    # func(bool)
        self.on_downstream_status_change = None  # func(bool)
        self.on_client_count_change = None       # func(int)
        self.on_log = None                       # func(str)
        self.on_client_list_change = None        # func(list[str])

        self._cleaned = False

    # ---------------------------------------
    # Logging
    # ---------------------------------------
    def _log(self, msg: str):
        """Normal log; also forwards to GUI if on_log is set."""
        print(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _log_dump(self, text: str):
        """
        Dump log:
        - GUI (on_log present): log only to GUI
        - CLI (no on_log): print to stdout
        """
        if self.on_log:
            try:
                self.on_log(text)
            except Exception:
                pass
        else:
            print(text)

    # ---------------------------------------
    # Downstream listen mode: notify client count/list/status
    # ---------------------------------------
    def _notify_downstream_listen_state(self, reason: str = ""):
        """Notify client count and list based on client_sockets."""
        with self.client_lock:
            count = len(self.client_sockets)
            info_list = []
            for s in self.client_sockets:
                try:
                    addr, port = s.getpeername()
                    info_list.append(f"{addr}:{port}")
                except OSError:
                    # Ignore closed sockets here; handled during send
                    pass

        dbg = f"listen-side state ({reason}) clients={count} [{', '.join(info_list)}]"
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
    # Downstream connect mode: notify as single-client equivalent
    # ---------------------------------------
    def _notify_downstream_connect_state(self, connected: bool, reason: str = ""):
        """Notify client count/list/status for connect-* modes."""
        count = 1 if connected else 0
        info_list = []

        if connected and self.downstream_socket:
            try:
                addr, port = self.downstream_socket.getpeername()
                info_list.append(f"{addr}:{port}")
            except OSError:
                pass

        dbg = f"connect-side state ({reason}) connected={connected} count={count} [{', '.join(info_list)}]"
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
    # Main
    # ---------------------------------------
    def start(self):
        # Reset for restart
        self.running = True
        self._cleaned = False

        self._log(f"Starting relay server in mode: {self.mode}")

        # Upstream setup
        try:
            if self.mode in ["connect-listen", "connect-connect"]:
                threading.Thread(target=self.connect_upstream, daemon=True).start()

            if self.mode in ["listen-connect", "listen-listen"]:
                self._listen_upstream_or_die()
        except OSError as e:
            self._log(
                f"ERROR: failed to set up upstream on {self.src_host}:{self.src_port}: {e}. "
                f"Server will not start."
            )
            self.running = False

        # Downstream setup
        if self.running:
            try:
                if self.mode in ["connect-listen", "listen-listen"]:
                    self._listen_clients_or_die()

                if self.mode in ["listen-connect", "connect-connect"]:
                    threading.Thread(target=self.connect_downstream, daemon=True).start()
            except OSError as e:
                self._log(
                    f"ERROR: failed to set up downstream on {self.dst_host}:{self.dst_port}: {e}. "
                    f"Server will not start."
                )
                self.running = False

        # Main loop
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    # ---------------------------------------
    # Upstream connect
    # ---------------------------------------
    def connect_upstream(self):
        while self.running:
            s = None
            try:
                self._log(f"connect_upstream: trying {self.src_host}:{self.src_port}")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Set timeout to avoid blocking forever on connect attempt
                s.settimeout(self.retry_interval)
                s.connect((self.src_host, self.src_port))
                s.settimeout(None)  # back to blocking after connect
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
                self._log("connect_upstream: disconnected, loop end or retry")

    # ---------------------------------------
    # Upstream listen
    # ---------------------------------------
    def _listen_upstream_or_die(self):
        """Listen for upstream. Raise on failure so start() can stop."""
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
            sock = None
            try:
                self._log("waiting for upstream accept...")
                sock, addr = self.upstream_server_socket.accept()
                self._log(f"Upstream connected: {addr}")

                # Close existing upstream connection (listen-* modes are 1:1 upstream)
                if self.upstream_socket:
                    self._log("closing previous upstream connection")
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
                if sock is not None and self.upstream_socket is sock:
                    self.upstream_socket = None

                if self.on_upstream_status_change:
                    try:
                        self.on_upstream_status_change(False)
                    except Exception:
                        pass
                self._log("upstream accept loop: upstream disconnected")

    # ---------------------------------------
    # Downstream listen (multi-client)
    # ---------------------------------------
    def _listen_clients_or_die(self):
        """Listen for downstream clients. Raise on failure so start() can stop."""
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
                self._log("waiting for downstream client accept...")
                client_socket, addr = self.client_server_socket.accept()
                self._log(f"Client connected: {addr}")

                with self.client_lock:
                    self.client_sockets.append(client_socket)

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
    # Downstream connect (1:1)
    # ---------------------------------------
    def connect_downstream(self):
        while self.running:
            s = None
            try:
                self._log(f"connect_downstream: trying {self.dst_host}:{self.dst_port}")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Set timeout to avoid blocking forever on connect attempt
                s.settimeout(self.retry_interval)
                s.connect((self.dst_host, self.dst_port))
                s.settimeout(None)  # back to blocking after connect
                self.downstream_socket = s

                self._log(f"Connected to downstream {self.dst_host}:{self.dst_port}")
                self._notify_downstream_connect_state(True, reason="connect_downstream_connected")

                # Keep-alive loop until disconnected
                while self.running and self.downstream_socket is s:
                    try:
                        # Peek to verify connection still alive
                        s.settimeout(0.5)
                        data = s.recv(1, socket.MSG_PEEK)
                        s.settimeout(None)

                        if data == b'':
                            # Empty read means connection closed
                            self._log("Downstream socket detected closed (recv(1) peek returned empty).")
                            break

                        # Ignore payload here (one-way relay)
                        time.sleep(0.1)

                    except socket.timeout:
                        continue
                    except OSError as e:
                        self._log(f"Downstream socket detected error: {e}")
                        break
                    except Exception as e:
                        self._log(f"Downstream socket check failed (unexpected): {e}")
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
                    self._log("connect_downstream: disconnected, loop end or retry")

    # ---------------------------------------
    # Relay (upstream -> downstream)
    # ---------------------------------------
    def relay_from_upstream(self):
        try:
            while self.running and self.upstream_socket:
                try:
                    data = self.upstream_socket.recv(4096)
                except OSError as e:
                    if not self.running:
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

                # Dump payload if enabled (content only, not size)
                if self.dump:
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        text = repr(data)
                    self._log_dump(text)

                # Downstream is listen side (multi-clients)
                if self.mode in ["connect-listen", "listen-listen"]:
                    with self.client_lock:
                        targets = list(self.client_sockets)

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
                                except ValueError:
                                    pass
                                try:
                                    s.close()
                                except Exception:
                                    pass
                        self._notify_downstream_listen_state(reason="send_error")

                # Downstream is connect side (1:1)
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
                            self._notify_downstream_connect_state(False, reason="send_error")

        except Exception as e:
            if self.running:
                self._log(f"Error receiving data from upstream: {e}")

    # ---------------------------------------
    # Shutdown
    # ---------------------------------------
    def handle_exit(self, signum=None, frame=None):
        """Called from GUI or signal; just set running=False."""
        self._log("Shutting down relay server (handle_exit)...")
        self.running = False

    def cleanup(self):
        """Called once from start() finally."""
        if self._cleaned:
            return
        self._cleaned = True

        self._log("Closing connections...")

        # Client sockets
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

        # Listen / connect sockets
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

        # Notify reset status
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
    # SIGTERM not available on Windows; best-effort on Linux/macOS
    try:
        signal.signal(signal.SIGTERM, relay_server.handle_exit)
    except ValueError:
        pass  # ignore on platforms without SIGTERM

    relay_server.start()


if __name__ == "__main__":
    main()
