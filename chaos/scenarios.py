"""All chaos scenario implementations (DealerDesk 98 flavor)."""
import random
import string
import threading
import tkinter as tk
from tkinter import messagebox


def _root():
    """Return the tk root window."""
    try:
        return tk._default_root
    except Exception:
        return None


# ── Phase 1 ───────────────────────────────────────────────────────────────

def scenario_random_dialog(root=None):
    """Pops a 'Connection lost' dialog. Loops until user clicks Retry."""
    r = root or _root()
    if not r:
        return

    def _show():
        while True:
            result = messagebox.askretrycancel(
                "Network Error",
                "Connection to DMS server lost.\nRetry connection?",
                parent=r,
            )
            if result:
                break

    threading.Thread(target=_show, daemon=True).start()


def scenario_fake_freeze(root=None, duration=None):
    """Disables all widgets for 3-10 seconds then re-enables."""
    r = root or _root()
    if not r:
        return
    dur = duration if duration is not None else random.randint(3, 10)

    def _collect_widgets(widget):
        widgets = []
        try:
            state = str(widget.cget("state"))
            if state != "disabled":
                widgets.append((widget, state))
        except Exception:
            pass
        for child in widget.winfo_children():
            widgets.extend(_collect_widgets(child))
        return widgets

    def _freeze():
        r.after(0, _do_freeze)

    def _do_freeze():
        alive_widgets = _collect_widgets(r)
        r.configure(cursor="wait")
        for widget, _ in alive_widgets:
            try:
                widget.configure(state="disabled")
            except Exception:
                pass

        def _thaw():
            r.configure(cursor="")
            for widget, orig_state in alive_widgets:
                try:
                    widget.configure(state=orig_state)
                except Exception:
                    pass

        r.after(dur * 1000, _thaw)

    threading.Thread(target=_freeze, daemon=True).start()


def scenario_session_timeout(root=None, on_logout=None):
    """Shows session expired message. Optionally kicks back to login."""
    r = root or _root()
    if not r:
        return

    def _show():
        def _do():
            messagebox.showwarning(
                "Session Expired",
                "Your session has expired due to inactivity.\n\nPlease log in again.",
                parent=r,
            )
            if on_logout:
                on_logout()
        r.after(0, _do)

    threading.Thread(target=_show, daemon=True).start()


def scenario_unexpected_save(root=None):
    """Shows a spurious 'Record saved' popup."""
    r = root or _root()
    if not r:
        return

    def _show():
        r.after(0, lambda: messagebox.showinfo(
            "Save Successful",
            "Record saved successfully.\n\nTransaction ID: " + _rand_txid(),
            parent=r,
        ))

    threading.Thread(target=_show, daemon=True).start()


def _rand_txid():
    return "TX-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


# ── Phase 2 ───────────────────────────────────────────────────────────────

def scenario_save_failure(root=None):
    """Shows a save error dialog."""
    r = root or _root()
    if not r:
        return

    def _show():
        r.after(0, lambda: messagebox.showerror(
            "Save Error",
            "ERROR: Unable to write record to database.\n"
            "Error code: DB_WRITE_0x" + "".join(random.choices("0123456789ABCDEF", k=6)) +
            "\n\nPlease contact your system administrator.",
            parent=r,
        ))

    threading.Thread(target=_show, daemon=True).start()


def scenario_wrong_patient(root=None):
    """Shows a wrong customer warning dialog. (Key name kept for engine reuse.)"""
    r = root or _root()
    if not r:
        return

    def _show():
        r.after(0, lambda: messagebox.showwarning(
            "Customer Record Warning",
            "WARNING: You may be viewing the wrong customer record.\n\n"
            "The currently loaded customer does not match the active\n"
            "deal or repair order for this session.\n\n"
            "Please verify customer identity before proceeding.",
            parent=r,
        ))

    threading.Thread(target=_show, daemon=True).start()


def scenario_bsod(root=None):
    """Full-screen blue overlay with fake BSOD stop error."""
    r = root or _root()
    if not r:
        return

    def _show():
        bsod = tk.Toplevel(r)
        bsod.configure(bg="#0000AA")
        bsod.attributes("-fullscreen", True)
        bsod.attributes("-topmost", True)
        bsod.grab_set()

        stop_text = (
            "A problem has been detected and DealerDesk has been shut down\n"
            "to prevent damage to your computer.\n\n"
            "DEALERDESK_PRO_UNEXPECTED_KERNEL_MODE_TRAP\n\n"
            "If this is the first time you've seen this Stop error screen,\n"
            "restart your computer. If this screen appears again, follow\n"
            "these steps:\n\n"
            "Check to make sure any new hardware or software is properly installed.\n"
            "If this is a new installation, ask your hardware or software\n"
            "manufacturer for any Windows updates you might need.\n\n"
            "If problems continue, disable or remove any newly installed hardware\n"
            "or software. Disable BIOS memory options such as caching or\n"
            "shadowing. If you need to use Safe Mode to remove or disable\n"
            "components, restart your computer, press F8 to select Advanced\n"
            "Startup Options, and then select Safe Mode.\n\n"
            "Technical information:\n\n"
            "*** STOP: 0x0000007E (0xC0000005, 0xF748E0BF, 0xF78DA208, 0xF78D9F08)\n\n"
            "   dealerdesk_core.exe - Address F748E0BF base at F7490000, DateStamp 3d6dd67c\n\n"
            "Beginning dump of physical memory\n"
            "Physical memory dump complete.\n\n"
            "Contact your system administrator or technical support group for\n"
            "further assistance.\n\n"
            "\n[Click anywhere to dismiss]"
        )

        lbl = tk.Label(
            bsod, text=stop_text,
            bg="#0000AA", fg="white",
            font=("Courier New", 10),
            justify="left", anchor="nw",
            padx=60, pady=40,
        )
        lbl.pack(fill=tk.BOTH, expand=True)
        bsod.bind("<Button-1>", lambda e: bsod.destroy())
        bsod.bind("<Key>", lambda e: bsod.destroy())
        bsod.focus_force()

    r.after(0, _show)


def scenario_slow_progress(root=None):
    """Shows a modal fake loading bar that crawls for ~30 seconds."""
    r = root or _root()
    if not r:
        return

    def _show():
        win = tk.Toplevel(r)
        win.title("Loading")
        win.resizable(False, False)
        win.configure(bg="#C0C0C0")
        win.grab_set()
        win.attributes("-topmost", True)

        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"380x120+{(sw-380)//2}+{(sh-120)//2}")

        tk.Label(win, text="Loading customer records...", font=("MS Sans Serif", 8),
                 bg="#C0C0C0").pack(padx=16, pady=(14, 4))

        from tkinter import ttk
        pvar = tk.IntVar(value=0)
        ttk.Progressbar(win, variable=pvar, maximum=100, length=340).pack(padx=16, pady=4)
        pct_label = tk.Label(win, text="0%", font=("MS Sans Serif", 8), bg="#C0C0C0")
        pct_label.pack()

        total_ms = 30000
        steps = 100
        step_ms = total_ms // steps

        def _tick(step=0):
            if not win.winfo_exists():
                return
            if step >= steps:
                win.destroy()
                return
            pvar.set(step)
            pct_label.config(text=f"{step}%")
            delay = step_ms + random.randint(-100, 400)
            win.after(max(50, delay), lambda: _tick(step + 1))

        win.after(200, lambda: _tick(0))

    r.after(0, _show)


def scenario_critical_error(root=None, immediate=False):
    """Massive red CRITICAL ERROR modal with fake stack trace and useless buttons."""
    r = root or _root()
    if not r:
        return

    ERROR_CODES = [
        ("DEALERDESK_CORE_EXCEPTION_0xC000021A", "0xF7482BC1", "dms_core.dll"),
        ("CUSTOMER_DB_ACCESS_VIOLATION_0x0000007E", "0xF748E0BF", "custdb32.dll"),
        ("DMV_BRIDGE_PARSE_FATAL_0x00000050", "0xC0034F12", "dmvbridge.dll"),
        ("DEAL_ENGINE_DEADLOCK_0x000000EF", "0xF00D1234", "deal_engine.exe"),
        ("FI_MODULE_STACK_OVERFLOW_0x000000ED", "0xDEADBEEF", "fimodule98.dll"),
        ("CREDIT_GATEWAY_TIMEOUT_0x00000073", "0xBADF00D1", "creditpull.dll"),
    ]
    code, addr, module = random.choice(ERROR_CODES)

    STACK_LINES = [
        f"  at DealerDesk.Core.CustomerRecord.Load(Int32 customerId) +0x{random.randint(0x100,0xFFF):03X}",
        f"  at DealerDesk.UI.DealForm.OpenRecord(Object sender, EventArgs e) +0x{random.randint(0x10,0xFF):02X}",
        f"  at DealerDesk.DB.ConnectionPool.Acquire() +0x{random.randint(0x10,0xFF):02X}",
        f"  at DealerDesk.Core.SessionManager.ValidateToken(String token) +0x{random.randint(0x10,0xFF):02X}",
        f"  at System.Windows.Forms.Application.Run(Form mainForm) +0x{random.randint(0x10,0xFF):02X}",
        f"  at MSCORLIB.DLL!System.Threading.ThreadHelper.ThreadStart_Context +0x{random.randint(0x10,0xFF):02X}",
        f"  at KERNEL32.DLL!BaseThreadInitThunk +0x{random.randint(0x10,0xFF):02X}",
        f"  at ntdll.dll!RtlUserThreadStart +0x{random.randint(0x10,0xFF):02X}",
    ]
    stack_trace = "\n".join(STACK_LINES)

    error_text = (
        f"Unhandled exception in DealerDesk 98\n"
        f"Error Code: {code}\n"
        f"Faulting address: {addr}\n"
        f"Faulting module: {module}\n\n"
        f"Exception details:\n"
        f"  Type:    System.AccessViolationException\n"
        f"  Message: Attempted to read or write protected memory.\n"
        f"           This is often an indication that other memory is corrupt.\n\n"
        f"Stack trace:\n"
        f"{stack_trace}\n\n"
        f"Additional information:\n"
        f"  Process: DEALERDESK.EXE (PID: {random.randint(1000,9999)})\n"
        f"  Thread:  {random.randint(1,32)} ({random.randint(0x1000,0xFFFF):#06x})\n"
        f"  Time:    {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  Build:   DealerDesk 98 v3.2.0 (Build 9812)\n\n"
        f"Please save your work and restart the application.\n"
        f"If this problem persists, contact your system administrator\n"
        f"or call technical support at 1-800-555-0199 (hold time ~45 min)."
    )

    def _show():
        win = tk.Toplevel(r)
        win.title("DealerDesk 98 - Critical Application Error")
        win.configure(bg="#C0C0C0")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.grab_set()

        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = 580, 460
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        title_f = tk.Frame(win, bg="#8B0000", pady=6)
        title_f.pack(fill=tk.X)
        tk.Label(title_f, text="X  CRITICAL APPLICATION ERROR",
                 font=("MS Sans Serif", 11, "bold"),
                 bg="#8B0000", fg="#FFFFFF", padx=10).pack(side=tk.LEFT)

        top_row = tk.Frame(win, bg="#C0C0C0", pady=6)
        top_row.pack(fill=tk.X, padx=10)
        tk.Label(top_row, text="ERROR", font=("MS Sans Serif", 28, "bold"),
                 bg="#8B0000", fg="#FFFFFF", padx=12, pady=4,
                 relief="raised", bd=3).pack(side=tk.LEFT)
        tk.Label(top_row, text=f"  {code}",
                 font=("Courier New", 8, "bold"),
                 bg="#C0C0C0", fg="#8B0000",
                 wraplength=420, justify="left").pack(side=tk.LEFT, padx=10)

        tk.Frame(win, bg="#808080", height=2).pack(fill=tk.X, padx=6, pady=2)

        txt_frame = tk.Frame(win, bg="#C0C0C0")
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        txt = tk.Text(txt_frame, font=("Courier New", 8), bg="#000000", fg="#FF4444",
                      relief="sunken", bd=2, wrap="word", height=14)
        vsb = tk.Scrollbar(txt_frame, command=txt.yview, bg="#C0C0C0")
        txt.configure(yscrollcommand=vsb.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.insert("1.0", error_text)
        txt.configure(state="disabled")

        tk.Frame(win, bg="#808080", height=2).pack(fill=tk.X, padx=6, pady=2)

        btn_row = tk.Frame(win, bg="#C0C0C0", pady=8)
        btn_row.pack(fill=tk.X)

        def _ignore():
            from tkinter import messagebox as mb
            mb.askyesno(
                "Ignore Error?",
                "WARNING: Ignoring this error may result in data corruption,\n"
                "loss of customer records, or system instability.\n\n"
                "Are you absolutely sure you want to ignore this error?",
                parent=win,
            )

        def _retry():
            for btn in btn_row.winfo_children():
                try:
                    btn.configure(state="disabled")
                except Exception:
                    pass
            win.title("DealerDesk 98 - Retrying...")
            win.after(500, lambda: win.title("DealerDesk 98 - Critical Application Error"))
            win.after(600, lambda: [btn.configure(state="normal")
                                     for btn in btn_row.winfo_children()
                                     if isinstance(btn, tk.Button)])
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", "Retrying operation...\n\n" + error_text)
            txt.configure(state="disabled")

        def _report():
            from tkinter import messagebox as mb
            mb.showinfo(
                "Report Error",
                "Sending error report to: helpdesk@dealerdesk.local\n\n"
                "Please do not turn off your computer.\n"
                "This may take several minutes.\n\n"
                "[Report sent successfully]\n"
                "Ticket ID: INC-" + str(random.randint(100000, 999999)) +
                "\nExpected response time: 3-5 business days.",
                parent=win,
            )
            win.destroy()

        for text, cmd, w_val in [
            ("Ignore", _ignore, 10),
            ("Retry", _retry, 10),
            ("Report to IT", _report, 13),
            ("OK", win.destroy, 10),
        ]:
            tk.Button(
                btn_row, text=text, command=cmd,
                font=("MS Sans Serif", 8),
                bg="#C0C0C0", relief="raised", bd=2,
                width=w_val,
            ).pack(side=tk.LEFT, padx=8)

    if immediate:
        _show()
    else:
        r.after(0, _show)


def scenario_field_corruption(root=None):
    """Appends garbage characters to a focused text entry."""
    r = root or _root()
    if not r:
        return

    garbage = "".join(random.choices("@#$%^&*!~`{}[]\\|<>", k=random.randint(3, 8)))

    def _corrupt():
        focused = r.focus_get()
        if focused is None:
            return
        try:
            widget_type = type(focused).__name__
            if widget_type == "Entry":
                current = focused.get()
                focused.delete(0, "end")
                focused.insert(0, current + garbage)
            elif widget_type == "Text":
                focused.insert("end", garbage)
        except Exception:
            pass

    r.after(0, _corrupt)
