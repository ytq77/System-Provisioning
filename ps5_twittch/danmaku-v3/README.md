# danmaku-v3：面板切换直接转推 / OBS 接管

此版本在 `danmaku-v2` 的基础上增加面板切换，独立放在 `danmaku-v3/`，保留 v2 的配置和固定转推流程。

## 两种模式

| 模式 | 视频链路 | 是否需要启动 OBS |
| --- | --- | --- |
| 直接转推 B 站 | PS5 → 本机 Nginx → FFmpeg 原样转发 → B 站 | 不需要 |
| OBS 接管（默认） | PS5 → 本机 Nginx → OBS 媒体源 → OBS 推流 | 需要 |

模式切换只启停本机转推进程，不重启 Nginx、不改 PS5 DNS，也不重启弹幕服务。
FFmpeg 使用 `-c copy`，不重新编码。OBS 输出画面时，由 OBS 自己编码。

OBS 接管不等于远程控制 OBS：“开始直播”“停止直播”仍在 OBS 中操作。
切回直接转推前，应先停止 OBS 向同一个直播间推流。
模式切换不保证直播平台端无缝衔接，平台可能有短暂断流或重新连接。

## 首次启动

1. 启动 Docker Desktop 的 Linux 引擎。
2. 进入 `ps5_twittch/danmaku-v3`，在 `data/config.json` 填自己的 B 站房间号与 Twitch 频道名，IRC_PORT 保持 17667。
3. 在 `data/dnsmasq.conf` 把所有 `192.168.x.x` 改成 Docker 电脑的局域网 IP，把上游 DNS 改成自己的网关/DNS。
4. 在当前目录运行：

   ```powershell
   docker compose up -d --build
   ```

5. 打开 `http://127.0.0.1:15500/`，找到“推流方式”。其他电脑访问时用 Docker 电脑的局域网 IP。
6. PS5 的网络/DNS 仍按项目根目录 README 配置。PS5 仍从 Twitch 入口发起直播。

Cookie 文件会在扫码登录后生成，首次启动无需创建空文件。

### 直接转推

选择“直接转推 B 站”，填入完整推流 URL，然后点击“保存并应用”。
完整 URL 是平台给出的服务器地址加推流码，保留推流码里的所有参数。例如：

```text
服务器：rtmp://example.com/live/
推流码：stream_name?key=example
完整地址：rtmp://example.com/live/stream_name?key=example
```

上面仅是格式示例，不能用于实际开播。也可使用其他平台的完整 RTMP/RTMPS 地址。

地址会保存在 `data/routing/settings.json`。以后切换模式不需要重复填；留空沿用原地址，输入新地址才替换。
首次启动默认 OBS 模式，尚未设置任何真实转推地址。

### OBS 接管

1. 在面板选择“OBS 接管”，点击“保存并应用”，等待状态变成“直接转推已停止”。
2. 在 PS5 开播；收到推流后，面板自动显示完整的“OBS 媒体源地址”。
3. 点击“复制地址”。OBS 添加“媒体源”，取消“本地文件”，把地址粘贴到输入框；输入格式留空。
4. 在 OBS 中配置 B 站/目标平台的服务器和推流码，手动开始直播。

OBS 与 Docker 同机时可用 `rtmp://127.0.0.1:1935/app/流名称`；不同电脑时必须用 Docker 电脑的局域网 IP。
面板根据浏览器访问地址生成主机地址。如果 OBS 在另一台电脑，请使用 Docker 电脑局域网 IP 打开面板再复制。
PS5 重开播后如果流名称改变，面板和直接转推会自动跟上，但已添加的 OBS 媒体源需要重新粘贴地址。

## 已有旧版部署如何升级

先在旧 `danmaku-v2` 目录执行 `docker compose down`（不加 `-v`），备份自己的配置。把自己的 `data/config.json`、`data/bili_cookies.json`（如果存在）、`data/dnsmasq.conf` 复制到 v3 对应目录。两版使用相同宿主机端口，不能同时运行。
在 v3 目录使用本版全部文件和 `data/nginx.conf`，不要把旧版 Nginx 配置直接覆盖过来。
如果自己改过 Nginx，至少移除旧的 `push` 指令，并把 `worker_processes` 改成 `1`。
原来的 B 站 URL 改为在面板中填写。不要同时保留 Nginx 的旧直推，否则 OBS 模式仍可能向 B 站推送。

运行 `docker compose up -d --build` 更新。首次升级会重建容器，建议先停止 PS5 直播；
升级完成后，日常切换模式不需要重启容器或 PS5。

## 状态与排查

- 等待 PS5 开播：已选择直推，但监控没有检测到正在发布的流。
- 正在连接转推目标：FFmpeg 已启动，尚未收到输出进度。
- 正在直接转推：已收到 FFmpeg 输出进度；是否真正开播请看平台直播间。
- 转推已断开：约 5 秒后自动重试；检查推流码有效性、直播间是否已开播和网络。
- 监控超过 12 秒没有更新：停止直推并隐藏 OBS 地址，防止使用过期状态；恢复后自动继续。
- 找不到 FFmpeg：Docker 用户重新构建镜像；本地 Python 运行用户需自行安装 FFmpeg 并加入 PATH。
  也可以通过 `FFMPEG_BINARY` 环境变量指定可执行文件。

```powershell
docker compose ps
docker compose logs --tail 100 ps5-bilibili-danmaku rtmp-monitor
docker compose exec ps5living nginx -t
```

管理面板沿用原项目的局域网用途，没有新增账号登录保护，不要把它直接暴露到公网。
`data/routing/settings.json` 包含直播推流码，不应公开提交或分享。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m py_compile danmaku_forward.py stream_routing.py monitor_rtmp.py
node --check static/stream_routing.js
docker compose config --quiet
```

已验证模式切换、真实子进程退出、流名称变化、断线重试、监控过期、配置保存、API 参数检查，
以及浏览器中的模式选择、保存、刷新后恢复和模拟流地址生成。
开发验证环境的 Docker 引擎未启动，尚未验证容器构建、真实 PS5 输入、OBS 播放或 B 站实际直播。
