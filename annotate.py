from __future__ import annotations

import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import ImageGrab

from annotations import (
    add_screenshot_record,
    copy_and_register_screenshot,
    delete_screenshot,
    get_accounts,
    get_distinct_values,
    get_recent_trades,
    get_trade,
    list_screenshots,
    resolve_stored_path,
    save_annotation,
    screenshot_folder,
    set_primary_screenshot,
)
from config import (
    DB_PATH,
    DEFAULT_SETUPS,
    DEFAULT_STRATEGIES,
    EMOTION_OPTIONS,
    GRADE_OPTIONS,
    RECENT_TRADE_LIMIT,
)
from database import connect, init_db


class AnnotationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MT5 Trade Journal — Stage D Annotation")
        self.geometry("1320x820")
        self.minsize(1100, 700)

        self.conn = connect(DB_PATH)
        init_db(self.conn)
        self.selected_account = None
        self.selected_position = None
        self.screenshot_rows = {}

        self._build_ui()
        self._load_accounts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Account:").pack(side="left")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(top, textvariable=self.account_var, state="readonly", width=16)
        self.account_combo.pack(side="left", padx=(5, 15))
        self.account_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_trades())

        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar(value="ALL")
        filter_combo = ttk.Combobox(top, textvariable=self.filter_var, state="readonly", width=14,
                                    values=["ALL", "OPEN", "CLOSED", "UNANNOTATED"])
        filter_combo.pack(side="left", padx=(5, 15))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_trades())

        ttk.Button(top, text="Refresh Trades", command=self.refresh_trades).pack(side="left")
        ttk.Label(top, text=f"Database: {DB_PATH}").pack(side="right")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        # Trade list ------------------------------------------------------
        cols = ("position", "symbol", "dir", "status", "entry", "pnl", "r", "strategy", "grade")
        self.trade_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        headings = {
            "position":"Position ID", "symbol":"Symbol", "dir":"Side", "status":"Status",
            "entry":"Entry Time", "pnl":"Net P&L", "r":"R", "strategy":"Strategy", "grade":"Grade"
        }
        widths = {"position":115,"symbol":85,"dir":60,"status":70,"entry":155,"pnl":90,"r":65,"strategy":130,"grade":55}
        for c in cols:
            self.trade_tree.heading(c, text=headings[c])
            self.trade_tree.column(c, width=widths[c], anchor="center" if c not in {"entry","strategy"} else "w")
        self.trade_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.trade_tree.yview)
        scroll.pack(side="right", fill="y")
        self.trade_tree.configure(yscrollcommand=scroll.set)
        self.trade_tree.bind("<<TreeviewSelect>>", self._trade_selected)

        # Right side ------------------------------------------------------
        summary = ttk.LabelFrame(right, text="Selected Trade", padding=8)
        summary.pack(fill="x")
        self.summary_var = tk.StringVar(value="Select a trade on the left.")
        ttk.Label(summary, textvariable=self.summary_var, justify="left").pack(anchor="w")

        form = ttk.LabelFrame(right, text="Your Annotation", padding=10)
        form.pack(fill="both", expand=True, pady=(8,0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self.strategy_var = tk.StringVar()
        self.setup_var = tk.StringVar()
        self.grade_var = tk.StringVar()
        self.emotion_var = tk.StringVar()
        self.violation_var = tk.BooleanVar(value=False)
        self.violation_type_var = tk.StringVar()

        ttk.Label(form, text="Strategy").grid(row=0, column=0, sticky="w", pady=4)
        self.strategy_combo = ttk.Combobox(form, textvariable=self.strategy_var, state="normal")
        self.strategy_combo.grid(row=0, column=1, sticky="ew", padx=(8,18), pady=4)

        ttk.Label(form, text="Setup").grid(row=0, column=2, sticky="w", pady=4)
        self.setup_combo = ttk.Combobox(form, textvariable=self.setup_var, state="normal")
        self.setup_combo.grid(row=0, column=3, sticky="ew", padx=(8,0), pady=4)

        ttk.Label(form, text="Grade").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.grade_var, values=GRADE_OPTIONS, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(8,18), pady=4)

        ttk.Label(form, text="Emotion").grid(row=1, column=2, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.emotion_var, values=EMOTION_OPTIONS, state="normal").grid(
            row=1, column=3, sticky="ew", padx=(8,0), pady=4)

        ttk.Checkbutton(form, text="Rule violation", variable=self.violation_var,
                        command=self._toggle_violation).grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(form, text="Violation type").grid(row=2, column=2, sticky="w", pady=4)
        self.violation_entry = ttk.Entry(form, textvariable=self.violation_type_var)
        self.violation_entry.grid(row=2, column=3, sticky="ew", padx=(8,0), pady=4)

        ttk.Label(form, text="Entry thesis / reason for trade").grid(row=3, column=0, columnspan=4, sticky="w", pady=(10,4))
        self.thesis_text = ScrolledText(form, height=5, wrap="word")
        self.thesis_text.grid(row=4, column=0, columnspan=4, sticky="nsew")

        ttk.Label(form, text="Notes / review").grid(row=5, column=0, columnspan=4, sticky="w", pady=(10,4))
        self.notes_text = ScrolledText(form, height=6, wrap="word")
        self.notes_text.grid(row=6, column=0, columnspan=4, sticky="nsew")
        form.rowconfigure(4, weight=1)
        form.rowconfigure(6, weight=1)

        btns = ttk.Frame(form)
        btns.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(10, 4))
        ttk.Button(btns, text="Save Annotation", command=self.save_current).pack(side="left")
        ttk.Button(btns, text="Capture Full Screen", command=self.capture_screen).pack(side="left", padx=6)
        ttk.Button(btns, text="Attach Image", command=self.attach_image).pack(side="left")
        ttk.Button(btns, text="Open Screenshot Folder", command=self.open_screenshot_folder).pack(side="left", padx=6)

        shots = ttk.LabelFrame(right, text="Screenshots", padding=8)
        shots.pack(fill="x", pady=(8,0))
        shot_cols = ("id","primary","time","source","file")
        self.shot_tree = ttk.Treeview(shots, columns=shot_cols, show="headings", height=5, selectmode="browse")
        for c, title, width in [
            ("id","ID",50),("primary","Primary",60),("time","Captured",140),("source","Source",80),("file","File",430)
        ]:
            self.shot_tree.heading(c, text=title)
            self.shot_tree.column(c, width=width, anchor="w")
        self.shot_tree.pack(fill="x")
        shot_btns = ttk.Frame(shots)
        shot_btns.pack(fill="x", pady=(6,0))
        ttk.Button(shot_btns, text="Open Selected", command=self.open_selected_screenshot).pack(side="left")
        ttk.Button(shot_btns, text="Make Primary", command=self.make_primary).pack(side="left", padx=6)
        ttk.Button(shot_btns, text="Remove Record", command=self.remove_screenshot).pack(side="left")

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        self._toggle_violation()

    def _load_accounts(self):
        accounts = get_accounts(self.conn)
        self.account_combo["values"] = [str(a) for a in accounts]
        if accounts:
            self.account_var.set(str(accounts[0]))
            self.refresh_trades()
        else:
            self.status_var.set("No trades found yet. Run main.py and capture at least one MT5 trade.")

    def refresh_trades(self):
        if not self.account_var.get():
            return
        account = int(self.account_var.get())
        rows = get_recent_trades(self.conn, account, RECENT_TRADE_LIMIT, self.filter_var.get())
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for r in rows:
            pnl = "" if r["net_pnl"] is None else f'{float(r["net_pnl"]):.2f}'
            rmult = "" if r["r_multiple"] is None else f'{float(r["r_multiple"]):.2f}'
            self.trade_tree.insert("", "end", iid=str(r["position_id"]), values=(
                r["position_id"], r["symbol"], r["direction"], r["status"],
                r["entry_datetime_local"] or "", pnl, rmult,
                r["strategy"] or "", r["grade"] or ""
            ))
        self.status_var.set(f"Loaded {len(rows)} trade(s).")

    def _trade_selected(self, _event=None):
        selected = self.trade_tree.selection()
        if not selected:
            return
        self.selected_account = int(self.account_var.get())
        self.selected_position = int(selected[0])
        trade = get_trade(self.conn, self.selected_account, self.selected_position)
        if not trade:
            return

        pnl = "" if trade["net_pnl"] is None else f'{float(trade["net_pnl"]):.2f}'
        rmult = "" if trade["r_multiple"] is None else f'{float(trade["r_multiple"]):.2f}R'
        self.summary_var.set(
            f'{trade["symbol"]}  {trade["direction"]}  |  {trade["status"]}  |  '
            f'Position {trade["position_id"]}\n'
            f'Entry: {trade["entry_price"]}  |  SL: {trade["initial_sl"]}  |  TP: {trade["initial_tp"]}  |  '
            f'Net P&L: {pnl}  |  R: {rmult}'
        )

        self.strategy_combo["values"] = get_distinct_values(self.conn, "strategy", DEFAULT_STRATEGIES)
        self.setup_combo["values"] = get_distinct_values(self.conn, "setup", DEFAULT_SETUPS)
        self.strategy_var.set(trade["strategy"] or "")
        self.setup_var.set(trade["setup"] or "")
        self.grade_var.set(trade["grade"] or "")
        self.emotion_var.set(trade["emotion"] or "")
        self.violation_var.set((trade["rule_violation"] or "NO").upper() == "YES")
        self.violation_type_var.set(trade["rule_violation_type"] or "")
        self.thesis_text.delete("1.0", "end")
        self.thesis_text.insert("1.0", trade["entry_thesis"] or "")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", trade["notes"] or "")
        self._toggle_violation()
        self._load_screenshots()

    def _toggle_violation(self):
        state = "normal" if self.violation_var.get() else "disabled"
        self.violation_entry.configure(state=state)
        if not self.violation_var.get():
            self.violation_type_var.set("")

    def _require_trade(self):
        if self.selected_account is None or self.selected_position is None:
            messagebox.showinfo("Select trade", "Select a trade first.")
            return False
        return True

    def save_current(self):
        if not self._require_trade():
            return
        try:
            save_annotation(
                self.conn,
                self.selected_account,
                self.selected_position,
                strategy=self.strategy_var.get(),
                setup=self.setup_var.get(),
                grade=self.grade_var.get(),
                rule_violation="YES" if self.violation_var.get() else "NO",
                rule_violation_type=self.violation_type_var.get(),
                entry_thesis=self.thesis_text.get("1.0", "end-1c"),
                emotion=self.emotion_var.get(),
                notes=self.notes_text.get("1.0", "end-1c"),
            )
            self.status_var.set(f"Saved annotation for position {self.selected_position}.")
            self.refresh_trades()
            if self.trade_tree.exists(str(self.selected_position)):
                self.trade_tree.selection_set(str(self.selected_position))
                self.trade_tree.focus(str(self.selected_position))
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def capture_screen(self):
        if not self._require_trade():
            return
        try:
            self.iconify()
            self.update()
            time.sleep(0.7)
            try:
                image = ImageGrab.grab(all_screens=True)
            except TypeError:
                image = ImageGrab.grab()
            folder = screenshot_folder(self.selected_account, self.selected_position)
            target = folder / f"{time.strftime('%Y%m%d_%H%M%S')}_capture.png"
            image.save(target)
            add_screenshot_record(
                self.conn, self.selected_account, self.selected_position,
                target, "CAPTURED", "Full-screen capture", True
            )
            self.deiconify()
            self.lift()
            self._load_screenshots()
            self.status_var.set(f"Screenshot saved: {target.name}")
        except Exception as exc:
            self.deiconify()
            messagebox.showerror("Screenshot failed", str(exc))

    def attach_image(self):
        if not self._require_trade():
            return
        source = filedialog.askopenfilename(
            title="Attach trade screenshot",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not source:
            return
        try:
            stored = copy_and_register_screenshot(
                self.conn, self.selected_account, self.selected_position, Path(source), ""
            )
            self._load_screenshots()
            self.status_var.set(f"Attached screenshot: {stored}")
        except Exception as exc:
            messagebox.showerror("Attach failed", str(exc))

    def _load_screenshots(self):
        for item in self.shot_tree.get_children():
            self.shot_tree.delete(item)
        self.screenshot_rows = {}
        if not self._require_trade_silent():
            return
        for r in list_screenshots(self.conn, self.selected_account, self.selected_position):
            sid = int(r["screenshot_id"])
            self.screenshot_rows[sid] = r
            dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(r["captured_at_msc"]) / 1000))
            self.shot_tree.insert("", "end", iid=str(sid), values=(
                sid, "YES" if int(r["is_primary"] or 0) else "", dt,
                r["source"] or "", r["file_path"]
            ))

    def _require_trade_silent(self):
        return self.selected_account is not None and self.selected_position is not None

    def _selected_screenshot_id(self):
        selected = self.shot_tree.selection()
        return int(selected[0]) if selected else None

    def open_selected_screenshot(self):
        sid = self._selected_screenshot_id()
        if sid is None:
            messagebox.showinfo("Select screenshot", "Select a screenshot first.")
            return
        row = self.screenshot_rows.get(sid)
        path = resolve_stored_path(row["file_path"])
        if not path.exists():
            messagebox.showerror("Missing file", str(path))
            return
        try:
            os.startfile(path)  # Windows
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    def make_primary(self):
        sid = self._selected_screenshot_id()
        if sid is None or not self._require_trade():
            return
        try:
            set_primary_screenshot(self.conn, self.selected_account, self.selected_position, sid)
            self._load_screenshots()
            self.status_var.set("Primary screenshot updated.")
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc))

    def remove_screenshot(self):
        sid = self._selected_screenshot_id()
        if sid is None or not self._require_trade():
            return
        if not messagebox.askyesno("Remove screenshot", "Remove this screenshot from the journal? The image file will be kept on disk."):
            return
        delete_screenshot(self.conn, self.selected_account, self.selected_position, sid, delete_file=False)
        self._load_screenshots()
        self.status_var.set("Screenshot record removed; image file kept on disk.")

    def open_screenshot_folder(self):
        if not self._require_trade():
            return
        folder = screenshot_folder(self.selected_account, self.selected_position)
        try:
            os.startfile(folder)
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", str(folder)])

    def _on_close(self):
        try:
            self.conn.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = AnnotationApp()
    app.mainloop()
