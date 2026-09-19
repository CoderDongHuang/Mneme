import io
import logging

from app.core.logging import JsonFormatter, configure_utf8_stream


class LegacyConsole(io.StringIO):
    encoding = "gbk"

    def __init__(self):
        super().__init__()
        self.configuration = None

    def reconfigure(self, **kwargs):
        self.configuration = kwargs


def test_windows_console_is_reconfigured_to_utf8():
    stream = LegacyConsole()
    assert configure_utf8_stream(stream) is stream
    assert stream.configuration == {"encoding": "utf-8", "errors": "backslashreplace"}


def test_utf8_stream_is_not_reconfigured():
    class Utf8Console(LegacyConsole):
        encoding = "utf-8"

    stream = Utf8Console()
    configure_utf8_stream(stream)
    assert stream.configuration is None


def test_json_formatter_preserves_chinese_text():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "解析完成：中文资料", (), None)
    output = JsonFormatter().format(record)
    assert "解析完成：中文资料" in output
    assert "\\u89e3" not in output
