# relay_gui.py
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import time

from tcp_relay_server import TCPRelayServer  # ファイル名に合わせて import を調整


class RelayGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TCP Relay Server GUI")
        self.geometry("700x450")

        self.server = None
        self.server_thread = None
        self.event_queue = queue.Queue()

        self._create_widgets()
        self._update_status_labels()
        self.after(200, self._process_events)

    def _create_widgets(self):
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 接続設定
        row = 0
        ttk.Label(frm, text="上流 (src host:port)").grid(row=row, column=0, sticky="w")
        self.src_host_var = tk.StringVar(value="127.0.0.1")
        self.src_port_var = tk.StringVar(value="4001")
        ttk.Entry(frm, textvariable=self.src_host_var, width=20).grid(row=row, column=1, sticky="w")
        ttk.Entry(frm, textvariable=self.src_port_var, width=8).grid(row=row, column=2, sticky="w")

        row += 1
        ttk.Label(frm, text="下流 (dst host:port)").grid(row=row, column=0, sticky="w")
        self.dst_host_var = tk.StringVar(value="0.0.0.0")
        self.dst_port_var = tk.StringVar(value="5000")
        ttk.Entry(frm, textvariable=self.dst_host_var, width=20).grid(row=row, column=1, sticky="w")
        ttk.Entry(frm, textvariable=self.dst_port_var, width=8).grid(row=row, column=2, sticky="w")

        row += 1
        ttk.Label(frm, text="モード").grid(row=row, column=0, sticky="w")
        self.mode_var = tk.StringVar(value="connect-listen")
        self.mode_combo = ttk.Combobox(
            frm,
            textvariable=self.mode_var,
            values=["connect-listen", "listen-connect", "connect-connect", "listen-listen"],
            state="readonly",
            width=20,
        )
        self.mode_combo.grid(row=row, column=1, sticky="w")

        row += 1
        self.dump_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="dump to log", variable=self.dump_var).grid(row=row, column=0, sticky="w")

        ttk.Label(frm, text="再接続間隔[秒]").grid(row=row, column=1, sticky="w")
        self.retry_var = tk.StringVar(value="5")
        ttk.Entry(frm, textvariable=self.retry_var, width=6).grid(row=row, column=2, sticky="w")

        # ボタン
        row += 1
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=5, sticky="w")

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start_server)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_server, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # ステータス表示
        row += 1
        status_frame = ttk.LabelFrame(frm, text="接続ステータス")
        status_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=5)
        status_frame.columnconfigure(1, weight=1)

        self.up_status_label = ttk.Label(status_frame, text="上流: Disconnected")
        self.up_status_label.grid(row=0, column=0, sticky="w")

        self.down_status_label = ttk.Label(status_frame, text="下流: Disconnected")
        self.down_status_label.grid(row=0, column=1, sticky="w")

        self.client_status_label = ttk.Label(status_frame, text="クライアント: 0")
        self.client_status_label.grid(row=0, column=2, sticky="w")

        # ログ表示
        row += 1
        log_frame = ttk.LabelFrame(frm, text="ログ")
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=5)
        frm.rowconfigure(row, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ==========================
    # サーバ制御
    # ==========================
    def start_server(self):
        if self.server_thread and self.server_thread.is_alive():
            return

        src_host = self.src_host_var.get()
        dst_host = self.dst_host_var.get()
        try:
            src_port = int(self.src_port_var.get())
            dst_port = int(self.dst_port_var.get())
            retry = int(self.retry_var.get())
        except ValueError:
            self._append_log("ポート番号と再接続間隔は整数で入力してください。")
            return

        mode = self.mode_var.get()
        dump = self.dump_var.get()

        self.server = TCPRelayServer(
            src_host, src_port,
            dst_host, dst_port,
            mode,
            dump=dump,
            retry_interval=retry,
        )

        # コールバック設定
        self.server.on_upstream_status_change = self._on_upstream_status_change
        self.server.on_downstream_status_change = self._on_downstream_status_change
        self.server.on_client_count_change = self._on_client_count_change
        self.server.on_log = self._on_server_log

        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._append_log("サーバを起動しました。")

    def stop_server(self):
        if self.server:
            self.server.handle_exit()
            self.server = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._append_log("サーバを停止しました。")

    # ==========================
    # コールバック → イベントキュー
    # ==========================
    def _on_upstream_status_change(self, connected: bool):
        self.event_queue.put(("upstream", connected))

    def _on_downstream_status_change(self, connected: bool):
        self.event_queue.put(("downstream", connected))

    def _on_client_count_change(self, count: int):
        self.event_queue.put(("clients", count))

    def _on_server_log(self, message: str):
        self.event_queue.put(("log", message))

    # ==========================
    # GUI側でイベントを処理
    # ==========================
    def _process_events(self):
        try:
            while True:
                event, value = self.event_queue.get_nowait()
                if event == "upstream":
                    self._set_upstream_status(value)
                elif event == "downstream":
                    self._set_downstream_status(value)
                elif event == "clients":
                    self._set_client_count(value)
                elif event == "log":
                    self._append_log(value)
        except queue.Empty:
            pass

        self.after(200, self._process_events)

    # ==========================
    # ステータス表示更新
    # ==========================
    def _set_upstream_status(self, connected: bool):
        text = "上流: Connected" if connected else "上流: Disconnected"
        self.up_status_label.config(text=text)

    def _set_downstream_status(self, connected: bool):
        text = "下流: Connected" if connected else "下流: Disconnected"
        self.down_status_label.config(text=text)

    def _set_client_count(self, count: int):
        self.client_status_label.config(text=f"クライアント: {count}")

    def _append_log(self, message: str):
        now = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{now}] {message}\n")
        self.log_text.see(tk.END)

    def _update_status_labels(self):
        # 必要なら定期ステータス更新をここに書ける
        pass


if __name__ == "__main__":
    app = RelayGUI()
    app.mainloop()
