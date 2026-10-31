"""DBL Data Converter: the Windows application window."""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .batch import list_folder, run

PRODUCT = "DBL Data Converter"
REPORT = "CONVERSION REPORT.txt"
GUIDE = "DBL Data Converter User Guide.pdf"


def resource(*parts):
    base = getattr(sys, "_MEIPASS", None)
    here = os.path.join(base, "dblconv") if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, *parts)


def open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showerror(PRODUCT, f"Could not open {path}:\n{e}")


class App:
    def __init__(self, root):
        self.root = root
        root.title(PRODUCT)
        root.geometry("760x540")
        root.minsize(640, 460)
        try:
            root.iconbitmap(resource("data", "app.ico"))
        except tk.TclError:
            pass
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Sub.TLabel", foreground="#444444")

        self.msgs = queue.Queue()
        self.data = tk.StringVar()
        self.out = tk.StringVar()
        self.status = tk.StringVar(value="Ready.")
        self.busy = False
        self.last_out = None

        self._menu()
        outer = ttk.Frame(root, padding=(14, 12, 14, 6))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=PRODUCT, style="Header.TLabel").pack(anchor="w")
        sub = ttk.Label(outer, style="Sub.TLabel", justify="left",
                        text="Converts DBL data files to Excel-compatible spreadsheets and an SQLite "
                             "database. Source files are opened read-only.")
        sub.pack(anchor="w", fill="x", pady=(2, 10))
        sub.bind("<Configure>", lambda e: sub.configure(wraplength=max(200, e.width - 4)))

        box = ttk.LabelFrame(outer, text="Folders", padding=10)
        box.pack(fill="x")
        ttk.Label(box, text="Source data folder").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.data_entry = ttk.Entry(box, textvariable=self.data)
        self.data_entry.grid(row=0, column=1, sticky="we")
        self.data_btn = ttk.Button(box, text="Browse…", command=self.pick_data)
        self.data_btn.grid(row=0, column=2, padx=(8, 0))
        self.found = ttk.Label(box, text="", style="Sub.TLabel")
        self.found.grid(row=1, column=1, sticky="w", pady=(2, 8))
        ttk.Label(box, text="Output folder").grid(row=2, column=0, sticky="w", padx=(0, 10))
        self.out_entry = ttk.Entry(box, textvariable=self.out)
        self.out_entry.grid(row=2, column=1, sticky="we")
        self.out_btn = ttk.Button(box, text="Browse…", command=self.pick_out)
        self.out_btn.grid(row=2, column=2, padx=(8, 0))
        box.columnconfigure(1, weight=1)

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=10)
        self.go = ttk.Button(bar, text="Convert", command=self.start)
        self.go.pack(side="left")
        self.report_btn = ttk.Button(bar, text="View Report", command=self.view_report, state="disabled")
        self.report_btn.pack(side="left", padx=(8, 0))
        self.folder_btn = ttk.Button(bar, text="Open Output Folder", command=self.open_out, state="disabled")
        self.folder_btn.pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        logbox = ttk.LabelFrame(outer, text="Activity", padding=6)
        logbox.pack(fill="both", expand=True)
        self.log = ScrolledText(logbox, height=12, state="disabled", wrap="word",
                                font=("Consolas", 9), relief="flat", borderwidth=0)
        self.log.pack(fill="both", expand=True)

        ttk.Separator(root).pack(fill="x")
        ttk.Label(root, textvariable=self.status, padding=(14, 3)).pack(fill="x")
        self.data.trace_add("write", lambda *_: self.scan())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def _menu(self):
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=False)
        f.add_command(label="Select Source Folder…", command=self.pick_data)
        f.add_command(label="Select Output Folder…", command=self.pick_out)
        f.add_separator()
        f.add_command(label="Exit", command=self.close)
        m.add_cascade(label="File", menu=f)
        h = tk.Menu(m, tearoff=False)
        h.add_command(label="User Guide", command=self.guide)
        h.add_separator()
        h.add_command(label=f"About {PRODUCT}", command=self.about)
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)

    # ----- folder selection -----
    def pick_data(self):
        d = filedialog.askdirectory(title="Select the source data folder", mustexist=True)
        if d:
            d = os.path.normpath(d)
            self.data.set(d)
            if not self.out.get():
                self.out.set(os.path.join(os.path.dirname(d), os.path.basename(d) + " - Converted"))

    def pick_out(self):
        d = filedialog.askdirectory(title="Select the output folder")
        if d:
            self.out.set(os.path.normpath(d))

    def scan(self):
        d = self.data.get().strip()
        if not os.path.isdir(d):
            self.found.configure(text="")
            return
        data_files, isam_files = list_folder(d)
        text = f"{len(data_files)} data file{'s' * (len(data_files) != 1)} found"
        if isam_files:
            text += f"; {len(isam_files)} ISAM file{'s' * (len(isam_files) != 1)} (require unloading first)"
        self.found.configure(text=text)

    # ----- conversion -----
    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for w in (self.go, self.data_btn, self.out_btn, self.data_entry, self.out_entry):
            w.configure(state=state)
        self.root.configure(cursor="watch" if busy else "")

    def start(self):
        data, out = self.data.get().strip(), self.out.get().strip()
        if not os.path.isdir(data):
            messagebox.showwarning(PRODUCT, "Select the folder that contains the data files.")
            return
        if not out:
            messagebox.showwarning(PRODUCT, "Select an output folder.")
            return
        a, b = os.path.normcase(os.path.abspath(data)), os.path.normcase(os.path.abspath(out))
        if a == b or b.startswith(a + os.sep):
            messagebox.showwarning(PRODUCT, "The output folder must be outside the source data folder.")
            return
        if os.path.isdir(out) and os.listdir(out):
            if not messagebox.askyesno(PRODUCT, "The output folder already contains files. Results from "
                                       "a previous conversion in this folder will be replaced.\n\nContinue?"):
                return
        data_files, _ = list_folder(data)
        if not data_files:
            messagebox.showwarning(PRODUCT, "No data files (.DDF or .SEQ) were found in the source folder.")
            return
        self.progress.configure(maximum=len(data_files), value=0)
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        self.report_btn.configure(state="disabled"); self.folder_btn.configure(state="disabled")
        self.set_busy(True)
        self.status.set("Converting…")
        threading.Thread(target=self.work, args=(data, out), daemon=True).start()

    def work(self, data, out):
        def log(text):
            self.msgs.put(("log", text))
            if text.startswith("  "):
                self.msgs.put(("step", None))
        try:
            results = run(data, out, log=log)
            ok = sum(1 for r in results if r[3])
            records = sum(r[3]["records"] for r in results if r[3])
            self.msgs.put(("done", (out, ok, len(results), records)))
        except Exception as e:  # report any failure in the window rather than closing
            self.msgs.put(("error", f"{type(e).__name__}: {e}"))

    def poll(self):
        while not self.msgs.empty():
            kind, payload = self.msgs.get()
            if kind == "log":
                self.write(payload)
            elif kind == "step":
                self.progress.step(1)
            elif kind == "done":
                out, ok, total, records = payload
                self.last_out = out
                self.set_busy(False)
                self.progress.configure(value=self.progress["maximum"])
                self.report_btn.configure(state="normal"); self.folder_btn.configure(state="normal")
                summary = f"Conversion complete: {ok} of {total} files, {records:,} records."
                self.status.set(summary)
                more = "" if ok == total else ("\n\nSome files were not converted. The report "
                                               "explains why and what to do.")
                if messagebox.askyesno(PRODUCT, summary + more + "\n\nOpen the conversion report now?"):
                    self.view_report()
            elif kind == "error":
                self.set_busy(False)
                self.status.set("Conversion stopped because of an error.")
                self.write("ERROR: " + payload)
                messagebox.showerror(PRODUCT, "The conversion stopped because of an error:\n\n" + payload)
        self.root.after(100, self.poll)

    # ----- other commands -----
    def view_report(self):
        if self.last_out:
            open_path(os.path.join(self.last_out, REPORT))

    def open_out(self):
        if self.last_out:
            open_path(self.last_out)

    def guide(self):
        path = resource("data", GUIDE)
        if os.path.exists(path):
            open_path(path)
        else:
            messagebox.showinfo(PRODUCT, "The user guide is supplied with the program as a separate document.")

    def about(self):
        messagebox.showinfo(f"About {PRODUCT}",
                            f"{PRODUCT}\nVersion {__version__}\n\n"
                            "Converts DBL fixed-record data files to SQLite and CSV using the "
                            "record layouts of the accounting system.\n\n"
                            f"Python {sys.version.split()[0]}, Tk {tk.TkVersion}")

    def close(self):
        if self.busy and not messagebox.askyesno(
                PRODUCT, "A conversion is in progress. Closing now leaves the output incomplete.\n\nClose anyway?"):
            return
        self.root.destroy()


def main():
    try:  # sharp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
