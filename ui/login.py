import tkinter as tk
from ui import style
from ui.widgets import w98_button, w98_entry, w98_label, w98_frame, title_bar
from db.connection import get_connection


class LoginWindow(tk.Toplevel):
    def __init__(self, master, on_success, on_primary):
        super().__init__(master)
        self.on_success = on_success
        self.on_primary = on_primary
        self.title("DealerDesk 98 - Login")
        self.resizable(False, False)
        self.configure(bg=style.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self.grab_set()
        self.focus_force()

    def _build(self):
        title_bar(self, "  DealerDesk 98  ").pack(fill=tk.X)

        outer = w98_frame(self)
        outer.pack(padx=20, pady=16, fill=tk.BOTH, expand=True)

        hdr = w98_label(outer, text="DealerDesk 98", bold=True,
                        font=("MS Sans Serif", 14, "bold"), fg=style.TITLE_BG)
        hdr.pack(pady=(0, 4))
        sub = w98_label(outer, text="Dealership Management System v3.2", fg=style.DISABLED_FG)
        sub.pack(pady=(0, 12))

        tk.Frame(outer, bg=style.BG_DARK, height=1).pack(fill=tk.X, pady=(0, 12))

        form = w98_frame(outer)
        form.pack()

        w98_label(form, text="Username:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self._user_var = tk.StringVar()
        self._user_entry = w98_entry(form, textvariable=self._user_var, name="username", width=22)
        self._user_entry.grid(row=0, column=1, padx=4, pady=4)

        w98_label(form, text="Password:").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        self._pass_var = tk.StringVar()
        self._pass_entry = w98_entry(form, textvariable=self._pass_var, name="password",
                                     show="*", width=22)
        self._pass_entry.grid(row=1, column=1, padx=4, pady=4)

        self._err_label = w98_label(outer, text="", fg=style.ERROR_FG)
        self._err_label.pack(pady=2)

        btn_row = w98_frame(outer)
        btn_row.pack(pady=8)
        w98_button(btn_row, "OK", command=self._do_login, name="btn_login", width=10).pack(side=tk.LEFT, padx=6)
        w98_button(btn_row, "Cancel", command=self._on_close, name="btn_cancel", width=10).pack(side=tk.LEFT, padx=6)

        self._user_entry.focus_set()
        self.bind("<Return>", lambda e: self._do_login())

    def _do_login(self):
        username = self._user_var.get().strip()
        password = self._pass_var.get().strip()
        if not username or not password:
            self._err_label.config(text="Please enter username and password.")
            return
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?", (username, password)
        ).fetchone()
        conn.close()
        if row:
            self._err_label.config(text="")
            user = dict(row)
            self.destroy()
            import tfa
            if getattr(tfa, "TFA_ENABLED", False):
                self.on_primary(TfaWindow(self.master, user, self.on_success))
            else:
                self.on_success(user)
        else:
            self._err_label.config(text="Invalid username or password.")
            self._pass_var.set("")
            self._pass_entry.focus_set()

    def _on_close(self):
        self.master.destroy()


class TfaWindow(tk.Toplevel):
    """Second login factor: 6-digit TOTP code, shown after username/password."""

    def __init__(self, master, user, on_success):
        super().__init__(master)
        self.user = user
        self.on_success = on_success
        self.title("DealerDesk 98 - Two-Factor Authentication")
        self.resizable(False, False)
        self.configure(bg=style.BG)
        self.protocol("WM_DELETE_WINDOW", lambda: self.master.destroy())
        self._build()
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")
        self.grab_set()
        self.focus_force()

    def _build(self):
        title_bar(self, "  DealerDesk 98 - Security Verification  ").pack(fill=tk.X)
        outer = w98_frame(self)
        outer.pack(padx=20, pady=16, fill=tk.BOTH, expand=True)

        w98_label(outer, text="Two-Factor Authentication", bold=True,
                  font=("MS Sans Serif", 12, "bold"), fg=style.TITLE_BG).pack(pady=(0, 4))
        w98_label(outer, text="Enter the 6-digit code from your authenticator app.",
                  fg=style.DISABLED_FG).pack(pady=(0, 12))

        tk.Frame(outer, bg=style.BG_DARK, height=1).pack(fill=tk.X, pady=(0, 12))

        form = w98_frame(outer)
        form.pack()
        w98_label(form, text="Auth Code:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self._code_var = tk.StringVar()
        self._code_entry = w98_entry(form, textvariable=self._code_var, name="tfa_code", width=16)
        self._code_entry.grid(row=0, column=1, padx=4, pady=4)

        self._err_label = w98_label(outer, text="", fg=style.ERROR_FG)
        self._err_label.pack(pady=2)

        btn_row = w98_frame(outer)
        btn_row.pack(pady=8)
        w98_button(btn_row, "Verify", command=self._verify, name="btn_tfa_verify", width=10).pack(side=tk.LEFT, padx=6)
        w98_button(btn_row, "Cancel", command=lambda: self.master.destroy(),
                   name="btn_tfa_cancel", width=10).pack(side=tk.LEFT, padx=6)

        self._code_entry.focus_set()
        self.bind("<Return>", lambda e: self._verify())

    def _verify(self):
        import tfa
        if tfa.verify(self._code_var.get()):
            self._err_label.config(text="")
            self.destroy()
            self.on_success(self.user)
        else:
            self._err_label.config(text="Invalid authentication code. Try again.")
            self._code_var.set("")
            self._code_entry.focus_set()
