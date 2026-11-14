import os
import subprocess
import tempfile
import unittest

from tests.helpers import OLD, REAL_SYSTEM_PREFERS_DARK, app, make_tree
from tests.test_gui import GuiCase


def runner(answers):
    """A fake tool runner: answers maps the last word of a command to (code, output)."""
    calls = []

    def run(cmd, env=None):
        calls.append((cmd, env))
        code, out, *err = answers.get(cmd[-1], (-1, ""))
        return subprocess.CompletedProcess(cmd, code, out.encode(),
                                           (err[0] if err else "").encode())
    run.calls = calls
    return run


class Choice(unittest.TestCase):
    def test_known_choices_in_any_case(self):
        self.assertEqual(app.theme_choice("dark"), "Dark")
        self.assertEqual(app.theme_choice(" LIGHT "), "Light")
        self.assertEqual(app.theme_choice("System"), "System")

    def test_unknown_or_missing_means_system(self):
        for v in (None, "", "purple", 3):
            self.assertEqual(app.theme_choice(v), "System")

    def test_resolve(self):
        self.assertEqual(app.resolve_theme("Dark", False), "dark")
        self.assertEqual(app.resolve_theme("Light", True), "light")
        self.assertEqual(app.resolve_theme("System", True), "dark")
        self.assertEqual(app.resolve_theme("System", False), "light")
        self.assertEqual(app.resolve_theme("System", None), "light")

    def test_palettes_have_the_same_keys_and_every_color(self):
        light, dark = app.PALETTES["light"], app.PALETTES["dark"]
        self.assertEqual(set(light), set(dark))
        for p in (light, dark):
            self.assertEqual(set(p["tint"]), {app.GREEN, app.RED, app.GRAY})
        self.assertEqual(light["tint"], app.BG)


class SystemSetting(unittest.TestCase):
    def test_macos_dark_and_light(self):
        dark = runner({"AppleInterfaceStyle": (0, "Dark\n")})
        light = runner({"AppleInterfaceStyle": (1, "")})     # the key is missing in light mode
        self.assertTrue(REAL_SYSTEM_PREFERS_DARK("darwin", dark))
        self.assertFalse(REAL_SYSTEM_PREFERS_DARK("darwin", light))

    def test_macos_without_the_tool_is_unknown(self):
        self.assertIsNone(REAL_SYSTEM_PREFERS_DARK("darwin", runner({})))

    def linux(self, answers, env=None):
        with tempfile.TemporaryDirectory() as d:
            env = dict(env or {}, XDG_CONFIG_HOME=d)
            if "kde" in env:
                with open(os.path.join(d, "kdeglobals"), "w", encoding="utf-8") as f:
                    f.write(env.pop("kde"))
            return REAL_SYSTEM_PREFERS_DARK("linux", runner(answers), env)

    def test_gnome_color_scheme(self):
        self.assertTrue(self.linux({"color-scheme": (0, "'prefer-dark'")}))
        self.assertFalse(self.linux({"color-scheme": (0, "'prefer-light'")}))

    def test_dark_gtk_theme_name(self):
        self.assertTrue(self.linux({"color-scheme": (0, "'default'"),
                                    "gtk-theme": (0, "'Adwaita-dark'")}))
        self.assertFalse(self.linux({"color-scheme": (0, "'default'"),
                                     "gtk-theme": (0, "'Adwaita'")}))

    def test_gtk_theme_variable_wins(self):
        self.assertTrue(self.linux({"color-scheme": (0, "'prefer-light'")},
                                   {"GTK_THEME": "Adwaita:dark"}))

    def test_kde_color_scheme(self):
        kde = "[Colors:View]\nColorScheme=Nope\n[General]\nColorScheme=BreezeDark\n"
        self.assertTrue(self.linux({}, {"kde": kde}))
        self.assertFalse(self.linux({}, {"kde": "[General]\nColorScheme=BreezeLight\n"}))

    def test_nothing_to_ask_is_unknown(self):
        self.assertIsNone(self.linux({}))


class Window(GuiCase):
    def test_switching_recolors_and_is_saved(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"a/f.txt": OLD})

            def check(w):
                w._set_theme("Dark")
                dark = app.PALETTES["dark"]
                self.assertEqual(w.theme_mode, "dark")
                red = str(w.tree.tag_configure(app.RED, "background"))
                self.assertEqual(red, dark["tint"][app.RED])
                self.assertEqual(str(w.sum_boxes[app.GREEN].cget("bg")), dark["tint"][app.GREEN])
                if w._native_theme != "aqua":        # macOS draws this list itself
                    self.assertEqual(str(w.ex_list.cget("bg")), dark["field"])
                self.assertEqual(app.load_settings()["theme"], "Dark")
                w._set_theme("Light")
                light = app.PALETTES["light"]
                self.assertEqual(w.theme_mode, "light")
                red = str(w.tree.tag_configure(app.RED, "background"))
                self.assertEqual(red, light["tint"][app.RED])
                self.assertEqual(app.load_settings()["theme"], "Light")
            self.drive(d, check)

    def test_system_follows_a_change_only_when_chosen(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})

            def check(w):
                w._set_theme("System")
                w._handle_msg(("system_theme", True))
                self.assertEqual(w.theme_mode, "dark")
                w._handle_msg(("system_theme", False))
                self.assertEqual(w.theme_mode, "light")
                w._set_theme("Dark")
                w._handle_msg(("system_theme", False))
                self.assertEqual(w.theme_mode, "dark")
                w._set_theme("System")
            self.drive(d, check)

    def test_new_dialogs_and_tooltip_get_the_colors(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, {"f.txt": OLD})

            def check(w):
                w._set_theme("Dark")
                w._about()
                about = [c for c in w.winfo_children() if c.winfo_class() == "Toplevel"]
                self.assertTrue(about)
                self.assertEqual(str(about[-1].cget("bg")), app.PALETTES["dark"]["bg"])
                about[-1].destroy()
                w._set_theme("System")
            self.drive(d, check)


class DesktopPortal(unittest.TestCase):
    """The desktop's own answer (freedesktop portal) comes first on Linux."""

    def ask(self, answers, env=None):
        run = runner(answers)
        with tempfile.TemporaryDirectory() as d:
            got = REAL_SYSTEM_PREFERS_DARK("linux", run, dict(env or {}, XDG_CONFIG_HOME=d))
        return got, run.calls

    def test_portal_dark_light_and_no_preference(self):
        self.assertTrue(self.ask({"color-scheme": (0, "(<uint32 1>,)")})[0])
        self.assertFalse(self.ask({"color-scheme": (0, "(<uint32 2>,)")})[0])
        # 0 = no preference: the next sources decide
        got, calls = self.ask({"color-scheme": (0, "(<uint32 0>,)"),
                               "gtk-theme": (0, "'Yaru-dark'")})
        self.assertTrue(got)

    def test_older_portal_is_asked_with_read(self):
        def run(cmd, env=None):
            ok = "org.freedesktop.portal.Settings.Read" in cmd
            return subprocess.CompletedProcess(cmd, 0 if ok else 1,
                                               b"(<<uint32 1>>,)" if ok else b"", b"")
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(REAL_SYSTEM_PREFERS_DARK("linux", run, {"XDG_CONFIG_HOME": d}))

    def test_settings_read_from_the_memory_fallback_are_ignored(self):
        got, _ = self.ask({"color-scheme": (0, "'default'", "Using the 'memory' GSettings backend"),
                           "gtk-theme": (0, "'Adwaita'", "Using the 'memory' GSettings backend")})
        self.assertIsNone(got)

    def test_tools_run_without_what_a_snap_or_bundle_put_in(self):
        env = {"GIO_MODULE_DIR": "/snap/x", "GSETTINGS_SCHEMA_DIR": "/snap/y",
               "LD_LIBRARY_PATH": "/tmp/_MEI1", "LD_LIBRARY_PATH_ORIG": "/usr/lib/x",
               "HOME": "/h"}
        _, calls = self.ask({}, env)
        for cmd, tool_env in calls:
            self.assertNotIn("GIO_MODULE_DIR", tool_env)
            self.assertNotIn("GSETTINGS_SCHEMA_DIR", tool_env)
            self.assertEqual(tool_env["LD_LIBRARY_PATH"], "/usr/lib/x")
            self.assertEqual(tool_env["HOME"], "/h")
