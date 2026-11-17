"""Panel-controlled, stream-copy forwarding. Nginx always remains the PS5 receiver."""
import atexit
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit


def validate_destination(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("推流地址格式不正确")
    value = value.strip()
    if any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("推流地址不能包含空格或换行")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("rtmp", "rtmps") or not parsed.hostname
                or not parsed.path.strip("/") or parsed.fragment
                or parsed.username or parsed.password):
            raise ValueError
        parsed.port
    except ValueError:
        raise ValueError("请填写完整的 rtmp:// 或 rtmps:// 推流地址（包含推流码）") from None
    return value


def live_stream(status, now=None):
    now = time.time() if now is None else now
    try:
        fresh = 0 <= now - float(status.get("last_update", 0)) < 12
    except (TypeError, ValueError):
        fresh = False
    key = status.get("stream_key", "")
    return key if status.get("active") and fresh and isinstance(key, str) else ""


class StreamRouter:
    def __init__(self, config_path, get_status, source_base, popen=subprocess.Popen):
        self.path = Path(config_path)
        self.get_status = get_status
        self.source_base = source_base.rstrip("/")
        self.popen = popen
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closing = threading.Event()
        self.config = {"mode": "obs", "direct_url": ""}
        self.state = "obs"
        self.message = "OBS 模式：已关闭直接转推"
        self.proc = None
        self.target = None
        self.last_desired = None
        self.retry_at = 0
        self.progress_at = 0
        self.started_at = 0
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if saved.get("mode") not in ("obs", "direct"):
                    raise ValueError
                if saved.get("direct_url"):
                    saved["direct_url"] = validate_destination(saved["direct_url"])
                if saved["mode"] == "direct" and not saved.get("direct_url"):
                    raise ValueError
                self.config = {"mode": saved["mode"], "direct_url": saved.get("direct_url", "")}
                self.state = "pending"
                self.message = "正在恢复已保存的模式"
            except (OSError, ValueError, AttributeError):
                self.state = "error"
                self.message = "模式配置无法读取，已停止直推；请重新保存设置"

    def snapshot(self):
        with self.lock:
            return {"mode": self.config["mode"],
                    "direct_url_configured": bool(self.config["direct_url"]),
                    "state": self.state, "message": self.message,
                    "stream_key": live_stream(self.get_status())}

    def save(self, mode, direct_url=""):
        if mode not in ("obs", "direct"):
            raise ValueError("请选择直接转推或 OBS 模式")
        if not isinstance(direct_url, str):
            raise ValueError("推流地址必须是文本")
        with self.lock:
            destination = (validate_destination(direct_url)
                           if mode == "direct" and direct_url.strip() else self.config["direct_url"])
            if mode == "direct" and not destination:
                raise ValueError("首次使用直接转推时，请填写完整的推流地址")
            config = {"mode": mode, "direct_url": destination}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as file:
                    json.dump(config, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.config = config
            self.state = "pending"
            self.message = "设置已保存，正在应用"
            self.retry_at = 0
        self.wake.set()

    def _stop(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=3)
            self.proc = None
        self.target = None
        self.progress_at = 0

    def _read_progress(self, process):
        # Never expose FFmpeg stderr: it can contain the platform's stream key.
        try:
            for line in process.stdout:
                if line.strip() == "progress=continue":
                    with self.lock:
                        if self.proc is process:
                            self.progress_at = time.monotonic()
        finally:
            process.stdout.close()

    def tick(self):
        with self.lock:
            if self.closing.is_set():
                return
            key = live_stream(self.get_status())
            desired = (key, self.config["direct_url"]) if self.config["mode"] == "direct" and key else None
            if self.proc is not None and self.target != desired:
                self._stop()
            if self.last_desired != desired:
                self.retry_at = 0
                self.last_desired = desired
            if self.config["mode"] == "obs":
                self.state, self.message = "obs", "OBS 模式：直接转推已停止，可在 OBS 中读取下方地址"
                return
            if not key:
                self.state, self.message = "waiting", "直接转推已启用，等待 PS5 开播或监控恢复"
                return
            now = time.monotonic()
            if self.proc is not None and self.proc.poll() is not None:
                self._stop()
                self.retry_at = now + 5
                self.state, self.message = "error", "转推已断开，5 秒后重试；请检查推流地址、直播间状态和网络"
            if self.proc is None:
                if now < self.retry_at:
                    return
                command = [os.getenv("FFMPEG_BINARY", "ffmpeg"), "-nostdin", "-hide_banner",
                           "-loglevel", "error", "-rw_timeout", "10000000", "-i",
                           self.source_base + "/" + key,
                           "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
                           "-rw_timeout", "10000000", "-f", "flv", "-progress", "pipe:1",
                           "-nostats", self.config["direct_url"]]
                try:
                    self.proc = self.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, text=True, shell=False)
                except OSError:
                    self.retry_at = now + 5
                    self.state, self.message = "error", "无法启动 FFmpeg；请重新构建镜像或检查本机 FFmpeg 安装"
                    return
                self.target = desired
                self.started_at = now
                threading.Thread(target=self._read_progress, args=(self.proc,), daemon=True).start()
            if now - (self.progress_at or self.started_at) > 30:
                self._stop()
                self.retry_at = now + 5
                self.state, self.message = "error", "转推长时间没有输出，正在准备重连"
            elif self.progress_at:
                self.state, self.message = "forwarding", "正在直接转推；直播间是否开播请以平台页面为准"
            else:
                self.state, self.message = "connecting", "正在连接转推目标"

    def start(self):
        def run():
            while not self.closing.is_set():
                try:
                    self.tick()
                except Exception:
                    with self.lock:
                        self.state, self.message = "error", "转推控制异常，请检查服务配置"
                self.wake.wait(1)
                self.wake.clear()
        threading.Thread(target=run, daemon=True, name="StreamRouter").start()
        atexit.register(self.close)

    def close(self):
        self.closing.set()
        self.wake.set()
        with self.lock:
            self._stop()


def register_routing_api(app, router):
    from flask import jsonify, request

    @app.route("/api/stream-routing", methods=["GET", "POST"])
    def stream_routing():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                return jsonify({"error": "请从本机管理面板提交设置"}), 403
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "请提交 JSON 设置"}), 400
            try:
                router.save(data.get("mode"), data.get("direct_url", ""))
            except ValueError as error:
                return jsonify({"error": str(error)}), 400
            except OSError:
                return jsonify({"error": "配置写入失败，请检查 routing 目录权限"}), 500
        response = jsonify(router.snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response, 202 if request.method == "POST" else 200
