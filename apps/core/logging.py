import contextvars
import json
import logging


request_id_var = contextvars.ContextVar("request_id", default="")
user_id_var = contextvars.ContextVar("user_id", default="")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or request_id_var.get()
        record.user_id = getattr(record, "user_id", None) or user_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    RESERVED_ATTRS = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and key not in payload:
                payload[key] = value

        return json.dumps(payload, default=str, separators=(",", ":"))
