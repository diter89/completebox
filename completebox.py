#!/usr/bin/env python3
from __future__ import annotations

import shlex
import subprocess
from typing import Callable, Iterable, Optional

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style


DEFAULT_CHOICES = [
    "com.google.android.apps.messaging",
    "com.whatsapp",
    "com.instagram.android",
    "com.spotify.music",
    "com.facebook.android",
    "com.twitter.android",
    "com.youtube",
    "com.tiktok",
]

DEFAULT_STYLE = Style.from_dict({
    "prompt": "ansicyan bold",
    "input": "ansicyan",
    "panel-border": "ansibrightblack",
    "panel-line": "",
    "panel-placeholder": "ansibrightblack",
    "selected-line": "reverse",
    "footer": "ansibrightblack",
    "no-results": "italic ansiyellow",
})


def _split_completion_query(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    if text.endswith(" "):
        return text, ""
    head, sep, tail = text.rpartition(" ")
    if sep:
        return head + sep, tail
    return "", text


def bash_completer(query: str) -> list[str]:
    lead, fragment = _split_completion_query(query)
    try:
        result = subprocess.run(
            ["bash", "-ic", f"compgen -cdfa -- {shlex.quote(fragment)}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    candidates = [line for line in result.stdout.splitlines() if line]
    seen: set[str] = set()
    completions: list[str] = []
    for candidate in candidates:
        full = lead + candidate
        if full not in seen:
            seen.add(full)
            completions.append(full)
    return completions


class _PanelPromptSession:
    def __init__(
        self,
        prompt_text: str,
        choices: Optional[Iterable[str]] = None,
        completer: Optional[Callable[[str], Iterable[str]]] = None,
        style: Optional[Style] = None,
        max_rows: int = 6,
    ) -> None:
        self.prompt_text = prompt_text
        self.choices = list(choices) if choices is not None else None
        self.completer = completer
        self.style = style or DEFAULT_STYLE
        self.max_rows = max_rows

        self.panel_width = 46
        self.panel_inner_width = self.panel_width - 4

        self.input_text = ""
        self.filtered_items: list[str] = []
        self.selected_index = 0

        self.filter_items()

    def filter_items(self) -> None:
        query = self.input_text
        if not query.strip():
            self.filtered_items = []
        elif self.completer is not None:
            try:
                completions = list(self.completer(query))
            except Exception:
                completions = []
            self.filtered_items = [c for c in completions if c]
        else:
            lowered = query.lower()
            source = self.choices or []
            self.filtered_items = [
                item for item in source if lowered in item.lower()
            ]
        self.selected_index = min(self.selected_index, max(len(self.filtered_items) - 1, 0))

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width == 1:
            return "…"
        return text[: width - 1] + "…"

    def _panel_header(self, title: str) -> FormattedText:
        inner = f" {title} "
        line_len = self.panel_width - 2
        header = inner.center(line_len, "─")
        return [("class:panel-border", f"┌{header}┐\n")]

    def _panel_footer(self) -> FormattedText:
        line_len = self.panel_width - 2
        return [("class:panel-border", f"└{'─' * line_len}┘\n")]

    def _panel_row(self, text: str, style: str) -> FormattedText:
        padded = text.ljust(self.panel_inner_width)
        return [
            ("class:panel-border", "│ "),
            (style, padded),
            ("class:panel-border", " │\n"),
        ]

    def render_panel(self) -> FormattedText:
        lines: FormattedText = []

        if not self.filtered_items:
            lines.extend(self._panel_header("No results"))
            message = self._truncate("Tidak ada hasil", self.panel_inner_width)
            lines.extend(self._panel_row(message, "class:no-results"))

            for _ in range(self.max_rows - 1):
                lines.extend(self._panel_row("", "class:panel-placeholder"))
        else:
            lines.extend(self._panel_header("Suggestions"))
            suggestions = self.filtered_items[: self.max_rows]
            for idx in range(self.max_rows):
                if idx < len(suggestions):
                    item = suggestions[idx]
                    prefix = "› " if idx == self.selected_index else "  "
                    content = prefix + self._truncate(
                        item, self.panel_inner_width - len(prefix)
                    )
                    style = "class:selected-line" if idx == self.selected_index else "class:panel-line"
                else:
                    content = ""
                    style = "class:panel-placeholder"

                lines.extend(self._panel_row(content, style))

        lines.extend(self._panel_footer())
        return lines

    def render_content(self) -> FormattedText:
        parts: FormattedText = []
        parts.append(("class:prompt", self.prompt_text))
        parts.append(("class:input", self.input_text))

        if self.input_text:
            parts.append(("", "\n\n"))
            parts.extend(self.render_panel())
            parts.append(("", "\n"))

        parts.append(("class:footer", "Tab: isi dari pilihan | Ctrl+C: batal"))
        return parts

    def _accept_selection(self) -> None:
        if self.filtered_items:
            self.input_text = self.filtered_items[self.selected_index]

    def run(self) -> str:
        kb = KeyBindings()

        @kb.add("up")
        def _(event) -> None:
            if self.filtered_items and self.selected_index > 0:
                self.selected_index -= 1

        @kb.add("down")
        def _(event) -> None:
            if self.filtered_items and self.selected_index < len(self.filtered_items) - 1:
                self.selected_index += 1

        @kb.add("tab")
        def _(event) -> None:
            if self.filtered_items:
                self._accept_selection()
                self.filter_items()

        @kb.add("enter")
        def _(event) -> None:
            text = self.input_text
            if not text and self.filtered_items:
                text = self.filtered_items[self.selected_index]
            event.app.exit(result=text)

        @kb.add("escape")
        def _(event) -> None:
            self.input_text = ""
            self.filter_items()

        @kb.add("backspace")
        def _(event) -> None:
            if self.input_text:
                self.input_text = self.input_text[:-1]
                self.filter_items()

        @kb.add("c-u")
        def _(event) -> None:
            self.input_text = ""
            self.filter_items()

        @kb.add("c-c")
        def _(event) -> None:
            event.app.exit(exception=KeyboardInterrupt)

        for char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ ":
            @kb.add(char)
            def _(event, c=char) -> None:
                self.input_text += c
                self.filter_items()

        layout = Layout(
            Window(
                content=FormattedTextControl(self.render_content),
                always_hide_cursor=True,
            )
        )

        app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
            style=self.style,
        )

        return app.run()


def complete_panel_prompt(
    prompt_text: str = "❯ ",
    choices: Optional[Iterable[str]] = None,
    *,
    completer: Optional[Callable[[str], Iterable[str]]] = None,
    style: Optional[Style] = None,
    max_rows: int = 6,
) -> str:
    prompt = _PanelPromptSession(
        prompt_text,
        choices or DEFAULT_CHOICES,
        completer,
        style,
        max_rows=max_rows,
    )
    return prompt.run()


class PanelInput:
    def __init__(
        self,
        *,
        choices: Optional[Iterable[str]] = None,
        completer: Optional[Callable[[str], Iterable[str]]] = None,
        style: Optional[Style] = None,
        max_rows: int = 6,
    ) -> None:
        self._choices = list(choices) if choices is not None else DEFAULT_CHOICES[:]
        self._completer = completer
        self._style = style or DEFAULT_STYLE
        self._max_rows = max_rows

    @property
    def choices(self) -> list[str]:
        return self._choices

    @choices.setter
    def choices(self, value: Iterable[str]) -> None:
        self._choices = list(value)

    @property
    def style(self) -> Style:
        return self._style

    @style.setter
    def style(self, value: Style) -> None:
        self._style = value

    def prompt(self, prompt_text: str = "❯ ") -> str:
        session = _PanelPromptSession(
            prompt_text,
            self._choices,
            self._completer,
            self._style,
            max_rows=self._max_rows,
        )
        return session.run()

    __call__ = prompt


if __name__ == "__main__":
    try:
        while True:
            value = complete_panel_prompt(completer=bash_completer)
            print(value)
    except (EOFError, KeyboardInterrupt):
        print()
