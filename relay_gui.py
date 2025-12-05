import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import time
import json
import os
from tcp_relay_server import TCPRelayServer


CONFIG_FILE = "relay_gui_config.json"


class RelayTab(ttk.Frame):
    """
    1つのタブ = 1インスタンスのTCPRelayServer + GUI一式
    """
    def __init__(self, master, close_callback=None, initial_config=None,
                 status_callback=None):
        super().__init__(master)

        self.server = None
        self.server_thread = None
        self.event_queue = queue.Queue()
        self.close_callback = close_callback

        # タブ状態通知用（RelayGUI側に渡す）
        self.status_callback = status_callback

        # 接続ステータス保持
        self._up_connected = False
        self._down_connected = False
        self._server_running = False  # 起動中かどうか

        self._create_widgets()

        # dump チェックボックス変更時に、動作中サーバへも即反映する
        self.dump_var.trace_add("write", self._on_dump_changed)

        if initial_config is not None:
            self.apply_config(initial_config)

        self._update_status_labels()
        self.after(200, self._process_events)

    def _create_widgets(self):
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # フレーム内グリッドの伸縮設定（ログを大きく広がるように）
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)

        # --- 接続設定 ---
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

        # --- ボタンエリア ---
        row += 1
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=5, sticky="w")

        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.start_server)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.stop_server, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # タブ内にも閉じるボタン
        self.close_tab_btn = ttk.Button(btn_frame, text="タブを閉じる", command=self._request_close)
        self.close_tab_btn.pack(side=tk.LEFT, padx=20)

        # --- ステータス表示 ---
        row += 1
        status_frame = ttk.LabelFrame(frm, text="接続ステータス")
        status_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=5)
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(2, weight=1)

        self.up_status_label = ttk.Label(status_frame, text="上流: Disconnected", foreground="red")
        self.up_status_label.grid(row=0, column=0, sticky="w")
        self.down_status_label = ttk.Label(status_frame, text="下流: Disconnected", foreground="red")
        self.down_status_label.grid(row=0, column=1, sticky="w")
        self.client_status_label = ttk.Label(status_frame, text="クライアント: 0")
        self.client_status_label.grid(row=0, column=2, sticky="w")

        # クライアント一覧表示
        ttk.Label(status_frame, text="クライアント一覧").grid(row=1, column=0, sticky="nw")
        self.client_listbox = tk.Listbox(status_frame, height=3)
        self.client_listbox.grid(row=1, column=1, columnspan=2, sticky="nsew", padx=(5, 0), pady=(2, 2))

        # --- ログ表示 ---
        row += 1
        log_frame = ttk.LabelFrame(frm, text="ログ")
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=5)

        # この行が縦方向に広がるように
        frm.rowconfigure(row, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _request_close(self):
        """閉じるボタンが押されたら親に通知"""
        if self.close_callback:
            self.close_callback(self)

    def _on_dump_changed(self, *args):
        """dumpチェック変更時：動いているサーバにも即反映"""
        if self.server is not None:
            self.server.dump = self.dump_var.get()
            self._append_log(f"dump mode changed: {self.server.dump}")

    def start_server(self):
        if self.server_thread and self.server_thread.is_alive():
            self._append_log("すでにサーバスレッドが起動しています。")
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
            src_host, src_port, dst_host, dst_port,
            mode, dump=dump, retry_interval=retry,
        )
        self.server.on_upstream_status_change = self._on_upstream_status_change
        self.server.on_downstream_status_change = self._on_downstream_status_change
        self.server.on_client_count_change = self._on_client_count_change
        self.server.on_log = self._on_server_log
        self.server.on_client_list_change = self._on_client_list_change

        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()

        self._server_running = True

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._append_log("サーバを起動しました。")

        # 起動直後（まだ両側Disconnected）の状態をタブに反映 → 赤
        if self.status_callback:
            try:
                self.status_callback(self, self._up_connected, self._down_connected, running=self._server_running)
            except Exception:
                pass

    def stop_server(self):
        # すでにサーバがあれば、まずコールバックを切る
        if self.server:
            try:
                # 古いサーバからの late イベントが GUI を上書きしないようにする
                self.server.on_upstream_status_change = None
                self.server.on_downstream_status_change = None
                self.server.on_client_count_change = None
                self.server.on_log = None
                if hasattr(self.server, "on_client_list_change"):
                    self.server.on_client_list_change = None
            except Exception:
                pass

            # 停止指示
            try:
                self.server.handle_exit()
            except Exception as e:
                self._append_log(f"サーバ停止中にエラー: {e}")

        # サーバースレッドの終了をできるだけ待つ
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=3.0)

        # 参照をクリア
        self.server = None
        self.server_thread = None
        self._server_running = False

        # ボタン状態とステータス表示をリセット
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_upstream_status(False)
        self._set_downstream_status(False)
        self._set_client_count(0)
        self._append_log("サーバを停止しました。")

        # タブ色を「未起動状態（グレー）」に明示的に反映
        if self.status_callback:
            try:
                self.status_callback(self, False, False, running=False)
            except Exception:
                pass

    # --- TCPRelayServer からのコールバック → イベントキューに積む ---

    def _on_upstream_status_change(self, connected: bool):
        self.event_queue.put(("upstream", connected))

    def _on_downstream_status_change(self, connected: bool):
        self.event_queue.put(("downstream", connected))

    def _on_client_count_change(self, count: int):
        self.event_queue.put(("clients", count))

    def _on_client_list_change(self, clients):
        """
        TCPRelayServer から渡されるクライアント一覧用のコールバック。
        clients は ["127.0.0.1:50000", ...] のようなリストを想定。
        """
        self.event_queue.put(("client_list", clients))

    def _on_server_log(self, message: str):
        self.event_queue.put(("log", message))

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
                elif event == "client_list":
                    self._update_client_list(value)
                elif event == "log":
                    self._append_log(value)
        except queue.Empty:
            pass
        self.after(200, self._process_events)

    def _set_upstream_status(self, connected: bool):
        self._up_connected = connected
        text = "上流: Connected" if connected else "上流: Disconnected"
        color = "blue" if connected else "red"
        self.up_status_label.config(text=text, foreground=color)

        if self.status_callback:
            try:
                self.status_callback(self, self._up_connected, self._down_connected, running=self._server_running)
            except Exception:
                pass

    def _set_downstream_status(self, connected: bool):
        self._down_connected = connected
        text = "下流: Connected" if connected else "下流: Disconnected"
        color = "blue" if connected else "red"
        self.down_status_label.config(text=text, foreground=color)

        if self.status_callback:
            try:
                self.status_callback(self, self._up_connected, self._down_connected, running=self._server_running)
            except Exception:
                pass

    def _set_client_count(self, count: int):
        self.client_status_label.config(text=f"クライアント: {count}")

    def _update_client_list(self, clients):
        """
        クライアント一覧リストボックスの内容を更新
        """
        self.client_listbox.delete(0, tk.END)
        for c in clients:
            self.client_listbox.insert(tk.END, c)

    def _append_log(self, message: str):
        now = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{now}] {message}\n")
        self.log_text.see(tk.END)

    def _update_status_labels(self):
        # 初期状態は切断扱い（ラベルは赤、タブはグレー）
        self._set_upstream_status(False)
        self._set_downstream_status(False)
        if self.status_callback:
            try:
                self.status_callback(self, False, False, running=False)
            except Exception:
                pass

    def get_config(self) -> dict:
        return {
            "src_host": self.src_host_var.get(),
            "src_port": self.src_port_var.get(),
            "dst_host": self.dst_host_var.get(),
            "dst_port": self.dst_port_var.get(),
            "mode": self.mode_var.get(),
            "dump": self.dump_var.get(),
            "retry": self.retry_var.get(),
        }

    def apply_config(self, conf: dict):
        if "src_host" in conf:
            self.src_host_var.set(conf["src_host"])
        if "src_port" in conf:
            self.src_port_var.set(str(conf["src_port"]))
        if "dst_host" in conf:
            self.dst_host_var.set(conf["dst_host"])
        if "dst_port" in conf:
            self.dst_port_var.set(str(conf["dst_port"]))
        if "mode" in conf:
            self.mode_var.set(conf["mode"])
        if "dump" in conf:
            self.dump_var.set(bool(conf["dump"]))
        if "retry" in conf:
            self.retry_var.set(str(conf["retry"]))


class RelayGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TCP Relay Server GUI (Custom Tabs)")
        self.geometry("700x450")

        # タブボタンを配置するフレーム（上部）
        self.tab_frame = ttk.Frame(self)
        self.tab_frame.pack(fill="x", side="top", padx=5, pady=(5, 0))

        # タブの内容（RelayTab）を保持するコンテナ（下部）
        self.content_container = ttk.Frame(self)
        self.content_container.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self.tabs = []          # RelayTab インスタンスのリスト
        self.tab_map = {}       # {RelayTabインスタンス: タブボタンWidget} のマップ
        self.current_tab = None # 現在表示中の RelayTab インスタンス
        self._right_clicked_tab = None

        # 「＋」ボタンをタブバーの最後に配置
        self.add_button = ttk.Button(
            self.tab_frame,
            text=" ＋ ",
            command=self._add_relay_tab,
            width=3,
        )
        self.add_button.pack(side="left", padx=(5, 0))

        # 右クリックメニューの定義
        self.tab_menu = tk.Menu(self, tearoff=0)
        self.tab_menu.add_command(label="このタブを閉じる", command=self._close_right_clicked_tab)

        # 設定読み込みと初期タブの作成
        config = self._load_config()
        tab_confs = config.get("tabs", [])
        if tab_confs:
            for conf in tab_confs:
                self._add_relay_tab(initial_config=conf, select=False)
        else:
            self._add_relay_tab(select=False)

        # 最初のタブを選択して表示
        if self.tabs:
            self._switch_tab(self.tabs[0])

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------
    # タブ状態の色更新
    # ------------------------
    def _update_tab_visual_state(self, tab_instance, up_connected, down_connected, running=True):
        """
        タブタイトル色のルール:
        - running == False      → グレー（未起動）
        - running == True かつ 両方接続 → 青（正常）
        - running == True かつ どちらか未接続 → 赤（片側/両側切断）
        """
        btn = self.tab_map.get(tab_instance)
        if not btn:
            return

        if not running:
            btn.config(foreground="gray")
        else:
            if up_connected and down_connected:
                btn.config(foreground="blue")
            else:
                btn.config(foreground="red")

    # ------------------------
    # タブ管理
    # ------------------------
    def _add_relay_tab(self, initial_config=None, select=True):
        """新しいタブとそのボタンを作成し、タブマネージャに追加する"""

        # initial_config が指定されていない & 既にタブがある場合は
        # 「左隣のタブ（= self.tabs[-1]）を見て自動設定」する
        if initial_config is None and self.tabs:
            prev_tab = self.tabs[-1]
            prev_conf = prev_tab.get_config()

            dst_host = prev_conf.get("dst_host", "127.0.0.1")
            dst_port_str = str(prev_conf.get("dst_port", "4001"))

            try:
                base_dst_port = int(dst_port_str)
            except ValueError:
                base_dst_port = None

            chain_conf = {}

            # 新タブの上流 = 左隣タブの下流
            chain_conf["src_host"] = dst_host
            chain_conf["src_port"] = dst_port_str

            # 新タブの下流 = 左隣タブの下流と同じアドレス＋ポート+1
            chain_conf["dst_host"] = dst_host
            if base_dst_port is not None:
                chain_conf["dst_port"] = str(base_dst_port + 1)
            else:
                chain_conf["dst_port"] = ""

            # 左隣タブの「二次側」が Listen か Connect かで mode を決める
            prev_mode = prev_conf.get("mode", "connect-listen")

            # 二次側が Listen のモード
            downstream_listen_modes = {"connect-listen", "listen-listen"}
            # 二次側が Connect のモード
            downstream_connect_modes = {"listen-connect", "connect-connect"}

            if prev_mode in downstream_listen_modes:
                # 左隣の二次側が Listen → 新タブは connect-listen
                chain_conf["mode"] = "connect-listen"
            elif prev_mode in downstream_connect_modes:
                # 左隣の二次側が Connect → 新タブは listen-listen
                chain_conf["mode"] = "listen-listen"
            else:
                # 想定外の文字列が来たときのフォールバック
                chain_conf["mode"] = "connect-listen"

            # dump / retry はとりあえず引き継ぎ
            chain_conf["dump"] = prev_conf.get("dump", False)
            chain_conf["retry"] = prev_conf.get("retry", "5")

            initial_config = chain_conf

        new_tab_content = RelayTab(
            self.content_container,
            close_callback=self.close_tab,
            initial_config=initial_config,
            status_callback=self._update_tab_visual_state,
        )
        self.tabs.append(new_tab_content)

        tab_button = ttk.Label(
            self.tab_frame,
            text="Relay",
            padding="12 6",
            cursor="hand2",
            relief="flat",
            background="#F0F0F0",
        )

        tab_button.bind("<Button-1>", lambda e, t=new_tab_content: self._switch_tab(t))
        tab_button.bind("<Button-3>", lambda e, t=new_tab_content: self._on_tab_right_click(e, t))

        # ＋ボタンの直前に挿入
        tab_button.pack(before=self.add_button, side="left", padx=(2, 0))

        self.tab_map[new_tab_content] = tab_button

        # 初期状態は未起動 → グレーにしておく
        self._update_tab_visual_state(new_tab_content, False, False, running=False)

        if select:
            self._switch_tab(new_tab_content)

        return new_tab_content

    def _switch_tab(self, target_tab):
        """タブを切り替えて表示する"""
        if self.current_tab and self.current_tab in self.tab_map:
            self.current_tab.pack_forget()
            self.tab_map[self.current_tab].config(relief="flat", background="#F0F0F0")

        target_tab.pack(fill="both", expand=True)
        self.current_tab = target_tab

        self.tab_map[self.current_tab].config(relief="raised", background="white")

    def _on_tab_right_click(self, event, tab_instance):
        """右クリックイベント。どのタブを閉じるか特定し、メニューを表示する"""
        self._right_clicked_tab = tab_instance
        self.tab_menu.tk_popup(event.x_root, event.y_root)

    def _close_right_clicked_tab(self):
        """右クリックメニューから「閉じる」が選択されたときの処理"""
        if self._right_clicked_tab:
            self.close_tab(self._right_clicked_tab)
            self._right_clicked_tab = None

    def close_tab(self, tab_instance):
        """タブインスタンスを受け取り、ボタンとコンテンツを削除する共通処理"""
        if tab_instance not in self.tabs:
            return

        tab_instance.stop_server()

        button = self.tab_map[tab_instance]
        button.destroy()
        tab_instance.destroy()

        self.tabs.remove(tab_instance)
        del self.tab_map[tab_instance]

        if tab_instance is self.current_tab:
            if self.tabs:
                self._switch_tab(self.tabs[0])
            else:
                self.current_tab = None
                self._add_relay_tab()

    # ------------------------
    # 設定保存・読み込み
    # ------------------------
    def _load_config(self) -> dict:
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self):
        data = {
            "tabs": [tab.get_config() for tab in self.tabs],
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_close(self):
        self._save_config()
        for tab in self.tabs:
            tab.stop_server()
        self.destroy()


if __name__ == "__main__":
    app = RelayGUI()
    app.mainloop()
