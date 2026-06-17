"""Huawei VRP Telnet client used by the eNSP adapter."""

import re
import telnetlib
import time
from dataclasses import dataclass
from typing import Optional


_PROMPT_RE = re.compile(r"(?:[<\[][\w\-./]+[>\]]|#)")
_BRACKET_PROMPT_RE = re.compile(r"[<\[][\w\-./]+[>\]]")
_VERSION_BANNER_RE = re.compile(r"\[V\d+R\d+C[\w.]+\]", re.IGNORECASE)
_MORE_PROMPT = "---- More ----"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[?[0-9;]*[hl]")
_SAVE_CONFIRM_RE = re.compile(
    r"(?:are you sure|overwrite.*file|continue|save.*configuration).*?"
    r"(?:\[y/n\]|\[Y/N\]|\(y/n\)\[n\]:?|\(Y/N\)\[N\]:?)",
    re.IGNORECASE | re.DOTALL,
)
_SAVE_FILENAME_RE = re.compile(
    r"please input the file name.*?\[[^\]]+\]:?",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class TelnetConfig:
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: float = 10.0
    prompt_wait: float = 2.0


class TelnetConnectionError(Exception):
    """Raised when the Telnet session cannot be established or maintained."""


class TelnetCommandError(Exception):
    """Raised when a device command cannot be completed."""


class TelnetClient:
    """Small VRP-aware Telnet client."""

    def __init__(self, config: TelnetConfig):
        self._config = config
        self._tn: Optional[telnetlib.Telnet] = None
        self._prompt: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._tn is not None

    def connect(self) -> None:
        try:
            self._tn = telnetlib.Telnet(
                self._config.host,
                self._config.port,
                timeout=self._config.timeout,
            )
        except (OSError, ConnectionRefusedError) as exc:
            raise TelnetConnectionError(
                f"Unable to connect to {self._config.host}:{self._config.port}: {exc}"
            ) from exc

        try:
            self._login()
        except Exception as exc:
            self.close()
            raise TelnetConnectionError(f"Login failed: {exc}") from exc

    def _login(self) -> None:
        """Handle Huawei VRP login and prompt discovery."""
        self._tn.write(b"\r\n")
        time.sleep(0.2)
        index, _, data = self._tn.expect(
            [
                b"Username:",
                b"<",
                b"\\[",
                b"Password:",
                b"#",
                b"Please Press ENTER",
                b"User interface",
            ],
            timeout=self._config.timeout,
        )

        if index == 0:
            username = self._config.username or ""
            self._tn.write(username.encode("ascii") + b"\r\n")
            time.sleep(0.5)
            index2, _, _ = self._tn.expect(
                [b"Password:", b"<"],
                timeout=self._config.timeout,
            )
            if index2 == 0:
                password = self._config.password or ""
                self._tn.write(password.encode("ascii") + b"\r\n")
        elif index == 3:
            password = self._config.password or ""
            self._tn.write(password.encode("ascii") + b"\r\n")
        elif index in (1, 2, 4):
            text = data.decode("ascii", errors="replace")
            prompt_text = self._extract_prompt(text)
            if prompt_text:
                self._prompt = prompt_text
                return
            self._tn.write(b"\r\n")
        elif index in (5, 6):
            self._tn.write(b"\r\n")
            time.sleep(0.5)

        if index == -1:
            self._tn.write(b"\r\n")

        self._wait_for_prompt()

    @staticmethod
    def _extract_prompt(text: str) -> Optional[str]:
        for match in _PROMPT_RE.finditer(text):
            prompt = match.group(0)
            if _VERSION_BANNER_RE.fullmatch(prompt):
                continue
            return prompt
        return None

    @staticmethod
    def _extract_prompt_line(
        text: str,
        expected_prompt: Optional[str] = None,
    ) -> Optional[str]:
        cleaned = _ANSI_RE.sub("", text)
        for line in cleaned.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if expected_prompt and candidate == expected_prompt.strip():
                return expected_prompt
            match = _BRACKET_PROMPT_RE.fullmatch(candidate)
            if match and not _VERSION_BANNER_RE.fullmatch(candidate):
                return candidate
            if expected_prompt == "#" and candidate == "#":
                return "#"
        return None

    @staticmethod
    def _extract_prompt_at_end(
        text: str,
        expected_prompt: Optional[str] = None,
    ) -> Optional[str]:
        cleaned = _ANSI_RE.sub("", text).rstrip()
        if not cleaned:
            return None
        last_line = cleaned.splitlines()[-1].strip()
        if expected_prompt and last_line == expected_prompt.strip():
            return expected_prompt
        match = _BRACKET_PROMPT_RE.fullmatch(last_line)
        if match:
            if _VERSION_BANNER_RE.fullmatch(last_line):
                return None
            return match.group(0)
        if expected_prompt == "#" and last_line == "#":
            return "#"
        return None

    def _wait_for_prompt(self, timeout: Optional[float] = None) -> str:
        timeout = timeout or self._config.timeout
        data = b""
        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                chunk = self._tn.read_very_eager()
            except EOFError as exc:
                raise TelnetConnectionError("Connection closed") from exc

            if chunk:
                data += chunk
                text = data.decode("ascii", errors="replace")

                if _MORE_PROMPT in text:
                    self._tn.write(b" ")
                    time.sleep(0.1)
                    data = data.replace(_MORE_PROMPT.encode("ascii"), b"")
                    continue

                if b">" in data or b"]" in data or b"#" in data:
                    prompt_text = self._extract_prompt(text)
                    if prompt_text:
                        self._prompt = prompt_text
                        return text

            time.sleep(0.05)

        raise TelnetConnectionError(
            "Timed out waiting for prompt "
            f"({timeout}s), got: {data.decode('ascii', errors='replace')[-200:]}"
        )

    def send_command(self, command: str, timeout: Optional[float] = None) -> str:
        if not self._tn:
            raise TelnetConnectionError("Not connected")

        timeout = timeout or self._config.timeout
        self._tn.read_very_eager()
        self._tn.write(command.encode("ascii") + b"\r\n")
        time.sleep(0.5)
        output = self._read_until_prompt(timeout)
        return clean_output(output, command, self._prompt)

    def _read_until_prompt(self, timeout: float) -> str:
        data = b""
        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                chunk = self._tn.read_very_eager()
            except EOFError as exc:
                raise TelnetConnectionError("Connection closed") from exc

            if chunk:
                data += chunk
                text = data.decode("ascii", errors="replace")

                if _MORE_PROMPT in text:
                    self._tn.write(b" ")
                    time.sleep(0.1)
                    data = data.replace(_MORE_PROMPT.encode("ascii"), b"")
                    continue

                if b">" in data or b"]" in data or b"#" in data:
                    normalized_data = data.lstrip(b"\r\n")
                    after_first_line = (
                        normalized_data.split(b"\n", 1)[1]
                        if b"\n" in normalized_data
                        else b""
                    )
                    after_first_text = after_first_line.decode("ascii", errors="replace")
                    if self._prompt and self._prompt.encode("ascii") in after_first_line:
                        return text
                    prompt_text = self._extract_prompt_line(
                        after_first_text,
                        expected_prompt=self._prompt,
                    )
                    if prompt_text:
                        self._prompt = prompt_text
                        return text
                    prompt_text = self._extract_prompt_at_end(
                        text,
                        expected_prompt=self._prompt,
                    )
                    if prompt_text:
                        self._prompt = prompt_text
                        return text

            time.sleep(0.05)

        raise TelnetCommandError(
            "Timed out reading command output "
            f"({timeout}s), got: {data.decode('ascii', errors='replace')[-300:]}"
        )

    def _read_eager(self) -> bytes:
        try:
            return self._tn.read_very_eager()
        except EOFError as exc:
            raise TelnetConnectionError("Connection closed") from exc

    def _read_save_until_confirm_or_prompt(
        self,
        save_command: str,
        timeout: float,
    ) -> tuple[str, bool]:
        data = b""
        end_time = time.time() + timeout

        while time.time() < end_time:
            chunk = self._read_eager()
            if chunk:
                data += chunk
                text = data.decode("ascii", errors="replace")

                if _MORE_PROMPT in text:
                    self._tn.write(b" ")
                    time.sleep(0.2)
                    data = data.replace(_MORE_PROMPT.encode("ascii"), b"")
                    continue

                if _SAVE_CONFIRM_RE.search(text):
                    return text, True

                prompt_text = self._extract_prompt_at_end(
                    text,
                    expected_prompt=self._prompt,
                )
                if prompt_text:
                    self._prompt = prompt_text
                    return text, False

            time.sleep(0.2)

        raise TelnetCommandError(
            f"{save_command} timed out ({timeout}s), "
            f"got: {data.decode('ascii', errors='replace')[-300:]}"
        )

    def _read_save_until_prompt(
        self,
        save_command: str,
        timeout: float,
        confirm_by_char: bool = True,
    ) -> str:
        data = b""
        end_time = time.time() + timeout
        confirm_cursor = 0
        filename_cursor = 0
        pending_prompt: Optional[str] = None
        pending_prompt_at: Optional[float] = None

        while time.time() < end_time:
            chunk = self._read_eager()
            if chunk:
                data += chunk
                text = data.decode("ascii", errors="replace")
                pending_prompt = None
                pending_prompt_at = None

                if _MORE_PROMPT in text:
                    self._tn.write(b" ")
                    time.sleep(0.2)
                    data = data.replace(_MORE_PROMPT.encode("ascii"), b"")
                    continue

                confirm_match = _SAVE_CONFIRM_RE.search(text, confirm_cursor)
                if confirm_match:
                    confirm_cursor = confirm_match.end()
                    if confirm_by_char:
                        self._tn.write(b"y")
                        time.sleep(0.2)
                        self._tn.write(b"\r")
                    else:
                        self._tn.write(b"Y")
                    time.sleep(0.8)
                    continue

                filename_match = _SAVE_FILENAME_RE.search(text, filename_cursor)
                if filename_match:
                    filename_cursor = filename_match.end()
                    self._tn.write(b"\r")
                    time.sleep(0.8)
                    continue

                prompt_text = self._extract_prompt_at_end(
                    text,
                    expected_prompt=self._prompt,
                )
                if prompt_text:
                    pending_prompt = prompt_text
                    pending_prompt_at = time.time()

            if pending_prompt and pending_prompt_at and time.time() - pending_prompt_at >= 1.5:
                self._prompt = pending_prompt
                return data.decode("ascii", errors="replace")

            time.sleep(0.2)

        raise TelnetCommandError(
            f"{save_command} timed out ({timeout}s), "
            f"got: {data.decode('ascii', errors='replace')[-300:]}"
        )

    def send_save_command(
        self,
        device_type: str,
        device_name: str,
        timeout: Optional[float] = None,
    ) -> str:
        """Execute the save flow for a router or switch session."""
        if not self._tn:
            raise TelnetConnectionError("Not connected")

        timeout = timeout or self._config.timeout
        save_command = "save"
        confirm_by_char = True

        self._tn.read_very_eager()
        # AR routers can treat the LF in CRLF as the answer to the save
        # confirmation prompt, selecting the default "n" before we send "y".
        line_end = b"\r" if confirm_by_char else b"\r\n"
        self._tn.write(save_command.encode("ascii") + line_end)
        time.sleep(0.8)

        head, needs_confirm = self._read_save_until_confirm_or_prompt(
            save_command,
            timeout,
        )
        if not needs_confirm:
            return clean_output(head, save_command, self._prompt)

        if confirm_by_char:
            self._tn.write(b"y")
            time.sleep(0.2)
            self._tn.write(b"\r")
        else:
            self._tn.write(b"Y")
        time.sleep(0.8)

        tail = self._read_save_until_prompt(
            save_command,
            max(1.0, timeout - 1.6),
            confirm_by_char=confirm_by_char,
        )
        return clean_output(head + tail, save_command, self._prompt)

    def close(self) -> None:
        if self._tn:
            try:
                self._tn.close()
            except Exception:
                pass
            self._tn = None
            self._prompt = None

    def __del__(self):
        self.close()


def clean_output(raw: str, command: str, prompt: Optional[str] = None) -> str:
    """Remove command echo, prompts and control codes from Telnet output."""
    text = _ANSI_RE.sub("", raw)
    text = text.replace(_MORE_PROMPT, "")

    lines = text.splitlines()
    cleaned_lines = []
    skip_echo = True

    for line in lines:
        stripped = line.strip()
        if skip_echo:
            if command.lower() in stripped.lower() or stripped == "":
                continue
            skip_echo = False

        if prompt and stripped == prompt.strip():
            continue
        if _PROMPT_RE.fullmatch(stripped):
            continue

        cleaned_lines.append(line)

    while cleaned_lines and cleaned_lines[0].strip() == "":
        cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1].strip() == "":
        cleaned_lines.pop()

    return "\n".join(cleaned_lines)
