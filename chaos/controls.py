class Controls:
    def __init__(self, root):
        self.root = root
        self.primary = None
        self.click = "disarmed"
        self.tag = "DealerDeskChaosClick"
        root.bind_class(self.tag, "<ButtonPress-1>", self._press)
        root.bind_class(self.tag, "<ButtonRelease-1>", self._release)
        root.bind_class(self.tag, "<B1-Motion>", self._motion)
        root.bind_all("<Map>", lambda event: self._tag(event.widget), add="+")

    def set_primary(self, window):
        self.primary = window

    def _eligible(self):
        window = self.primary
        if window is None or not window.winfo_exists() or window.state() == "withdrawn":
            return None
        grab = self.root.grab_current()
        if grab is not None and grab.winfo_toplevel() != window:
            return None
        return window

    def _tag(self, widget):
        tags = widget.bindtags()
        if self.tag not in tags:
            widget.bindtags((self.tag,) + tags)
        for child in widget.winfo_children():
            self._tag(child)

    def _press(self, event):
        if self.click == "consuming":
            self.click = "disarmed"
        elif (
            self.click == "armed" and self._eligible() == event.widget.winfo_toplevel()
        ):
            self.click = "consuming"
            return "break"

    def _release(self, event):
        if self.click == "consuming":
            self.click = "disarmed"
            return "break"

    def _motion(self, event):
        if self.click == "consuming":
            return "break"

    def ignore_next_click(self, parameters):
        if not self._eligible():
            return 409, "rejected", "no_eligible_window"
        if self.click != "disarmed":
            return 409, "rejected", "already_armed"
        self._tag(self.root)
        self.click = "armed"
        return 200, "completed", None

    def move(self, parameters):
        return self._window_action(parameters)

    def minimize(self, parameters):
        return self._window_action(parameters, minimize=True)

    def _window_action(self, parameters, minimize=False):
        import win32con
        import win32gui

        window = self._eligible()
        if not window:
            return 409, "rejected", "no_eligible_window"
        hwnd = win32gui.GetAncestor(window.winfo_id(), win32con.GA_ROOT)
        if minimize:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            confirmed = win32gui.IsIconic(hwnd)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(
                hwnd,
                0,
                parameters["x"],
                parameters["y"],
                0,
                0,
                win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )
            confirmed = win32gui.GetWindowRect(hwnd)[:2] == (
                parameters["x"],
                parameters["y"],
            )
        if confirmed:
            return 200, "completed", None
        return 500, "unknown", "effect_unconfirmed"
