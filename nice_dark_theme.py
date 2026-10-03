import os

import sublime
import sublime_plugin

SETTINGS = "niceDarkTheme.sublime-settings"
PACKAGE_CONTROL_SETTINGS = "Package Control.sublime-settings"
FILE_ICONS_PACKAGE = "A File Icon"
PREFERENCES = "Preferences.sublime-settings"
TERMINUS_SETTINGS = "Terminus.sublime-settings"

THEME = "niceDarkTheme.sublime-theme"
COLOR_SCHEME = "niceDarkTheme.sublime-color-scheme"
TERMINUS = "Terminus"

# Delay before touching windows at startup, so Sublime can finish restoring
# the previous session first.
STARTUP_DELAY_MS = 1500


def _settings():
    return sublime.load_settings(SETTINGS)


def _theme_active():
    return sublime.load_settings(PREFERENCES).get("theme") == THEME


def _terminus_installed():
    return any(
        path.startswith("Packages/{}/".format(TERMINUS))
        for path in sublime.find_resources(TERMINUS_SETTINGS)
    )


def _terminal_ids(window):
    return {v.id() for v in window.views() if v.settings().get("terminus_view")}


def _split(terminal_size):
    return round(1.0 - min(max(float(terminal_size), 0.1), 0.9), 4)


SINGLE_LAYOUT = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}


def _position():
    """"right", "bottom" or "none" (no terminal: a single files group)."""
    return _settings().get("terminal_position", "right")


def _wants_terminal():
    return _settings().get("open_terminal", True) and _position() != "none"


def _terminal_layout(position=None):
    """Files (group 0) and terminal (group 1), with the terminal either in a
    column on the right or in a row along the bottom. For "none", a single
    group."""
    s = _settings()
    position = position or _position()
    if position == "none":
        return SINGLE_LAYOUT
    if position == "bottom":
        return {
            "cols": [0.0, 1.0],
            "rows": [0.0, _split(s.get("terminal_row_height", 0.3)), 1.0],
            "cells": [[0, 0, 1, 1], [0, 1, 1, 2]],
        }
    return {
        "cols": [0.0, _split(s.get("terminal_column_width", 0.3)), 1.0],
        "rows": [0.0, 1.0],
        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
    }


def _is_settings_window(window):
    """True for the window Sublime's edit_settings command opens (defaults on
    the left, user file on the right, side bar hidden). It marks both files
    with the edit_settings_view view setting."""
    return any(v.settings().get("edit_settings_view") for v in window.views())


def _apply_layout(window):
    """Side bar | files | terminal. Windows that already have a terminal
    (e.g. restored from the last session) are left alone, and so are the
    settings windows opened by Preferences > Settings, which have a layout of
    their own. Without a terminal (position "none", open_terminal false, or no
    Terminus) the files keep a single group, so no empty pane is left where
    the terminal would be."""
    if _terminal_ids(window) or _is_settings_window(window):
        return
    s = _settings()
    window.set_sidebar_visible(s.get("show_side_bar", True))
    window.set_minimap_visible(s.get("show_minimap", False))
    if _wants_terminal() and _terminus_installed():
        window.run_command("nice_open_terminal", {
            "focus_files": s.get("focus_files_after_terminal", True),
        })


def _apply_layout_everywhere():
    for window in sublime.windows():
        _apply_layout(window)


class NiceOpenTerminalCommand(sublime_plugin.WindowCommand):
    """Open a Terminus shell in the terminal group (right or bottom).

    terminus_open may create its view asynchronously (it does at startup), so
    wait for the new view to appear and then move it to the terminal group.
    """

    def is_enabled(self, **kwargs):
        return _terminus_installed() and not _is_settings_window(self.window)

    def run(self, focus_files=False, **kwargs):
        window = self.window
        if window.num_groups() == 1:
            # With position "none" this still opens one, on the right, for
            # this window only; the setting stays "none".
            window.set_layout(_terminal_layout(
                "right" if _position() == "none" else None))
        target = window.num_groups() - 1
        window.focus_group(target)
        args = dict(_settings().get("terminal_args", {}))
        args.update(kwargs)
        before = _terminal_ids(window)
        window.run_command("terminus_open", args)
        self._place(before, target, focus_files, tries=50)

    def _place(self, before, target, focus_files, tries):
        window = self.window
        new = [v for v in window.views()
               if v.id() not in before and v.settings().get("terminus_view")]
        if not new:
            if tries > 0:
                sublime.set_timeout(
                    lambda: self._place(before, target, focus_files, tries - 1),
                    100)
            return
        view = new[0]
        if window.get_view_index(view)[0] != target:
            window.set_view_index(view, target, len(window.views_in_group(target)))
        window.focus_view(view)
        if focus_files:
            window.focus_group(0)


class NiceSetTerminalPositionCommand(sublime_plugin.WindowCommand):
    """Put the terminal on the "right" or at the "bottom", or go back to the
    single files view with "none", and remember the choice.

    The right and bottom layouts have the same two groups, so re-applying the
    layout moves an open terminal along with its group.
    """

    def is_enabled(self, position=None):
        # Settings windows (Preferences > Settings) have no terminal.
        return not _is_settings_window(self.window)

    def is_checked(self, position):
        return _position() == position

    def run(self, position):
        window = self.window
        if position == "none":
            self._remove_terminals(window)
            return
        _settings().set("terminal_position", position)
        sublime.save_settings(SETTINGS)
        if not _terminal_ids(window) and _terminus_installed():
            # Coming from the single view (or a window without a terminal).
            window.run_command("nice_open_terminal", {
                "focus_files": _settings().get("focus_files_after_terminal", True),
            })
        elif window.num_groups() == 2:
            window.set_layout(_terminal_layout())

    def _remove_terminals(self, window):
        terminals = [v for v in window.views() if v.settings().get("terminus_view")]
        if terminals and not sublime.ok_cancel_dialog(
                "Closing the terminal ends whatever is running in it "
                "(for example a Claude Code session).\n\n"
                "Go back to the single view?", "Close Terminal"):
            return
        _settings().set("terminal_position", "none")
        sublime.save_settings(SETTINGS)
        for view in terminals:
            view.close()
        # Other tabs in the terminal group move into the files group.
        window.set_layout(SINGLE_LAYOUT)


FILE_ICONS_MESSAGE = (
    "niceDarkTheme shows file-specific icons (MATLAB, Markdown, images, ...) "
    "in the side bar through the A File Icon package. Without it, files get a "
    "generic icon.\n\n"
    "Install A File Icon now? Restart Sublime Text afterwards.")


def _package_name():
    # The folder name, or the name of the .sublime-package when zipped.
    return os.path.splitext(os.path.basename(os.path.dirname(__file__)))[0]


def _file_icons_installed():
    installed = sublime.load_settings(PACKAGE_CONTROL_SETTINGS).get(
        "installed_packages", [])
    return (FILE_ICONS_PACKAGE in installed
            # A File Icon creates this folder the first time it runs.
            or os.path.isdir(os.path.join(sublime.packages_path(),
                                          "zzz " + FILE_ICONS_PACKAGE)))


def _ask_to_install_file_icons(window):
    if sublime.ok_cancel_dialog(FILE_ICONS_MESSAGE, "Install"):
        window.run_command(
            "advanced_install_package", {"packages": FILE_ICONS_PACKAGE})


def _offer_file_icons():
    """On the first install through Package Control, offer A File Icon if it
    is missing. Package Control can't install another package as a
    dependency, and without it the theme only has folder icons."""
    try:
        from package_control import events
    except ImportError:  # manual install, or Package Control not loaded yet
        return
    if events.install(_package_name()) and not _file_icons_installed():
        window = sublime.active_window()
        if window:
            sublime.set_timeout(lambda: _ask_to_install_file_icons(window), 1500)


class NiceInstallFileIconsCommand(sublime_plugin.WindowCommand):
    """Install the A File Icon package, which draws the file-specific icons."""

    def is_enabled(self):
        return not _file_icons_installed()

    def run(self):
        _ask_to_install_file_icons(self.window)


class NiceNoopCommand(sublime_plugin.WindowCommand):
    """Does nothing. A window command the layout listener can rewrite another
    window command into, to cancel it (the built-in noop is a text command)."""

    def run(self):
        pass


class NiceApplyLayoutCommand(sublime_plugin.WindowCommand):
    """Apply the niceDarkTheme layout to the current window."""

    def is_enabled(self):
        return not _is_settings_window(self.window)

    def run(self):
        _apply_layout(self.window)


class NiceActivateCommand(sublime_plugin.WindowCommand):
    """Switch to the niceDarkTheme theme and color scheme, then apply the layout."""

    def run(self):
        prefs = sublime.load_settings(PREFERENCES)
        prefs.set("theme", THEME)
        prefs.set("color_scheme", COLOR_SCHEME)
        sublime.save_settings(PREFERENCES)
        if _wants_terminal() and not _terminus_installed():
            if sublime.ok_cancel_dialog(
                    "niceDarkTheme opens a Terminus terminal next to your files.\n\n"
                    "Terminus is not installed. Install it now?", "Install"):
                self.window.run_command(
                    "advanced_install_package", {"packages": TERMINUS})
                return
        _apply_layout(self.window)


class NiceApplyRecommendedSettingsCommand(sublime_plugin.WindowCommand):
    """Write niceDarkTheme's recommended editor settings to user preferences."""

    def run(self):
        s = _settings()
        recommended = s.get("recommended_preferences", {})
        terminus_view = s.get("recommended_terminus_view_settings", {})
        terminus = s.get("recommended_terminus_settings", {})
        shell = s.get("recommended_terminus_shell")
        if sublime.platform() != "windows" or not _terminus_installed():
            shell = None
        if not _terminus_installed():
            terminus_view = terminus = {}

        def fmt(items):
            return ["  {}: {}".format(k, sublime.encode_value(v))
                    for k, v in items.items()]

        message = ("niceDarkTheme will write these to your Preferences:\n\n"
                   + "\n".join(fmt(recommended)))
        terminus_lines = fmt(terminus) + [
            "  view_settings.{}: {}".format(k, sublime.encode_value(v))
            for k, v in terminus_view.items()]
        if shell:
            terminus_lines.append("  default shell (Windows): " + shell)
        if terminus_lines:
            message += "\n\nand to your Terminus settings:\n\n" + "\n".join(terminus_lines)
        message += "\n\nExisting values for these keys are replaced."
        if not sublime.ok_cancel_dialog(message, "Apply"):
            return

        prefs = sublime.load_settings(PREFERENCES)
        for key, value in recommended.items():
            prefs.set(key, value)
        sublime.save_settings(PREFERENCES)

        if not terminus_lines:
            return
        term = sublime.load_settings(TERMINUS_SETTINGS)
        for key, value in terminus.items():
            term.set(key, value)
        if terminus_view:
            view_settings = term.get("view_settings", {}) or {}
            view_settings.update(terminus_view)
            term.set("view_settings", view_settings)
        if shell:
            _set_terminus_default_shell(term, shell)
        sublime.save_settings(TERMINUS_SETTINGS)


def _set_terminus_default_shell(term, shell):
    """Make `shell` the Windows default. A user-defined "shell_configs" list
    replaces Terminus' built-in one, so add a config for the shell if the
    effective list lacks it."""
    configs = term.get("shell_configs", []) or []
    if not any(c.get("name", "").lower() == shell.lower() for c in configs):
        if shell.lower() != "powershell":
            print("niceDarkTheme: no Terminus shell config named", shell)
            return
        configs.append({
            "name": "PowerShell",
            "cmd": "powershell.exe",
            "env": {},
            "enable": True,
            "platforms": ["windows"],
        })
        term.set("shell_configs", configs)
    default_config = term.get("default_config", {})
    if not isinstance(default_config, dict):
        default_config = {}
    default_config["windows"] = shell
    term.set("default_config", default_config)


FILES_GROUP = 0
TERMINAL_GROUP = 1


def _has_terminal_group(window):
    return window.num_groups() == 2 and any(
        v.settings().get("terminus_view")
        for v in window.views_in_group(TERMINAL_GROUP))


def _move_to_files_group(window, view):
    if not view.is_valid() or window.get_view_index(view)[0] != TERMINAL_GROUP:
        return
    if window.transient_view_in_group(TERMINAL_GROUP) == view:
        # A side bar preview can't be moved, so reopen it in the files group.
        path = view.file_name()
        view.close()
        window.focus_group(FILES_GROUP)
        if path:
            window.open_file(path, sublime.TRANSIENT)
        return
    window.set_view_index(
        view, FILES_GROUP, len(window.views_in_group(FILES_GROUP)))
    window.focus_view(view)


_closing_terminals = set()
_checked_terminals = set()


def _close_if_stray_terminal(view, delay=0):
    """Close a Terminus terminal that ended up in a settings window. Uses
    terminus_close, which stops the shell before closing the tab."""
    window = view.window()
    if window is None or view.id() in _closing_terminals:
        return
    if not _is_settings_window(window):
        return
    _closing_terminals.add(view.id())

    def close():
        _closing_terminals.discard(view.id())
        if view.is_valid() and view.settings().get("terminus_view"):
            view.run_command("terminus_close")
            sublime.status_message(
                "niceDarkTheme: no terminal in settings windows")

    sublime.set_timeout(close, delay)


class NiceLayoutListener(sublime_plugin.EventListener):

    def on_new_window(self, window):
        if _theme_active() and _settings().get("layout_on_startup", True):
            sublime.set_timeout(lambda: _apply_layout(window), 300)

    def on_window_command(self, window, command_name, args):
        """No terminals in settings windows. Every Terminus terminal (palette,
        side bar menu, key binding or another package) is created by the
        terminus_open command, so cancel it there."""
        if command_name == "terminus_open" and _is_settings_window(window):
            print("niceDarkTheme: cancelled terminus_open in a settings window")
            sublime.status_message(
                "niceDarkTheme: no terminal in settings windows")
            return ("nice_noop", None)

    def on_modified_async(self, view):
        # A terminal shows output as soon as its shell has started, so this
        # is the moment a stray one can be closed safely. Each terminal is
        # checked once (its window never changes), so busy output costs one
        # settings lookup per chunk and nothing more.
        if view.settings().get("terminus_view") and view.id() not in _checked_terminals:
            _checked_terminals.add(view.id())
            _close_if_stray_terminal(view)

    def on_activated(self, view):
        """Files opened while the terminal has focus land in the terminal
        group; move them to the files group. Scratch views (output and tool
        panels other packages place there) are left alone."""
        window = view.window()
        if view.settings().get("terminus_view"):
            _close_if_stray_terminal(view, delay=700)
            return
        if (not window or view.is_scratch()
                or view.settings().get("is_widget")
                or _is_settings_window(window)):
            return
        if not (_theme_active()
                and _settings().get("keep_files_out_of_terminal", True)
                and _has_terminal_group(window)
                and window.get_view_index(view)[0] == TERMINAL_GROUP):
            return
        sublime.set_timeout(lambda: _move_to_files_group(window, view), 0)


LAYOUT_KEYS = ("terminal_position", "terminal_column_width", "terminal_row_height")
_layout_values = None


def _current_layout_values():
    s = _settings()
    return tuple(s.get(key) for key in LAYOUT_KEYS)


def _on_settings_change():
    """Re-lay-out open windows when the position or size settings change, so
    editing them takes effect without re-running a command. Restored windows
    keep their saved layout otherwise."""
    global _layout_values
    values = _current_layout_values()
    if values == _layout_values:
        return
    _layout_values = values
    if not _theme_active() or _position() == "none":
        # "none" is applied by the "Without Terminal" command, which asks
        # before closing a running terminal; editing the setting by hand
        # must not pull the terminal into the files pane.
        return
    for window in sublime.windows():
        if _has_terminal_group(window):
            window.set_layout(_terminal_layout())


def plugin_loaded():
    # Runs at startup and when the package is installed or updated.
    global _layout_values
    _layout_values = _current_layout_values()
    _settings().add_on_change("niceDarkTheme.layout", _on_settings_change)
    _offer_file_icons()
    if _theme_active() and _settings().get("layout_on_startup", True):
        sublime.set_timeout(_apply_layout_everywhere, STARTUP_DELAY_MS)


def plugin_unloaded():
    _settings().clear_on_change("niceDarkTheme.layout")
