# PS5 免采集卡转推 B 站 + 弹幕回显到 PS5

这个项目用于让 PS5 在不使用采集卡的情况下开播到 B 站，并把 B 站直播间弹幕转发回 PS5 的直播聊天界面。

核心思路是：PS5 仍按 Twitch 直播流程工作，但本机 `dnsmasq` 会把 Twitch 的 RTMP 和 IRC 相关域名解析到 Docker 所在电脑。随后 `ps5living` 接收 PS5 的 RTMP 推流并转推到 B 站，弹幕服务抓取 B 站弹幕，再通过本地 IRC 服务发回给 PS5。

## 项目来源声明

本项目为个人学习与实践用途，基于以下两个开源项目的思路与实现进行适配和整合：

- [ProgramRipper/BLiveWeb](https://github.com/ProgramRipper/BLiveWeb)
- [IceNoproblem/PS5BiliDanmaku](https://github.com/IceNoproblem/PS5BiliDanmaku)

如本项目中涉及对上述项目代码或思路的引用，版权与许可归原项目及其许可证所有。感谢原项目作者和社区贡献者的开源分享。

## 目录怎么选

需要在面板中切换“直接转推 B 站 / OBS 接管”时，使用新增的 [`danmaku-v3/`](danmaku-v3/README.md)。v3 默认 OBS 模式，自动显示 OBS 媒体源地址；直接转推的地址在面板保存，无需编辑 Nginx 或重启容器切换。

`danmaku-v2/` 保留原来的固定转推方案，包含弹幕转发、DNS 劫持、RTMP 中继、Web 配置页和 RTMP 推流状态监控。旧代码注释中的 V3.0 是内部版本说明，不代表目录版本。

下面的部署步骤继续针对 v2。v3 的安装、模式切换和从 v2 迁移步骤见 [v3 使用说明](danmaku-v3/README.md)。两版使用相同宿主机端口，请勿同时启动。

`danmaku-v1/` 是旧版备份，功能更简单，没有独立的 RTMP 监控容器。`without_danmaku/` 只做 PS5 到 B 站的 RTMP 转推，不包含 B 站弹幕抓取和 PS5 IRC 回显。

历史目录名是 `ps5_twittch`，虽然拼写不是 Twitch，但这里不改目录名，避免已有路径失效。

## danmaku-v2 服务架构

在 `danmaku-v2/` 中启动后，会运行以下服务：

- `ps5-bilibili-danmaku`：Web 管理页、B 站弹幕抓取、PS5 IRC 服务。宿主机端口为 `15500` 和 `6667`。
- `ps5living`：基于 `bao3/playstation` 的 RTMP 服务，接收 PS5 推流并转推到 B 站。宿主机端口为 `80`、`17890` 和 `1935`。
- `rtmp-monitor`：轮询 `ps5living` 的 RTMP 统计页，并把推流码、码率、分辨率、帧率等状态写入 Web 面板。
- `dnsmasq`：把 PS5 需要访问的 Twitch RTMP 和 IRC 域名解析到 Docker 电脑。宿主机端口为 `53/udp` 和 `18081`。

## 前置准备

- PS5 和运行 Docker 的电脑必须在同一局域网。
- 电脑已安装 Docker Desktop(性能不理想可用Rancher Desktop)，并确保 Docker 正在运行。
- 你有 B 站直播间，并拿到了可用的 B 站推流地址。
- 建议给 Docker 电脑设置固定局域网 IP，或在路由器里做 DHCP 保留。
- 先记下 Docker 电脑的局域网 IP，Windows 可用 `ipconfig` 查看，通常类似 `192.168.x.x`。
- Clone 本项目到本地后，后续命令都在 `ps5_twittch/danmaku-v2` 目录执行。

如果粉丝数不够、无法在 B 站后台直接获取推流码，可以参考 [BLiveWeb](https://github.com/ProgramRipper/BLiveWeb) 获取推流地址。

## 快速开始

进入推荐方案目录：

```bash
cd ps5_twittch/danmaku-v2
```

修改 `data/config.json`：

- `BILIBILI_ROOM_ID`：改成你的 B 站直播间 ID。
- `TWITCH_CHANNEL`：改成给 PS5 使用的频道名，建议只用英文、数字、下划线。
- `IRC_PORT`：Docker 方案保持 `17667`，对应宿主机端口映射 `6667:17667`。
- B 站登录态保存在 `data/bili_cookies.json`，也可以启动后在 Web 面板扫码登录生成。

修改 `data/dnsmasq.conf`：

- `server=192.168.7.1` 改成你的上游 DNS 或路由器网关 IP。
- 把以下规则里的 `192.168.x.x` 都改成 Docker 电脑的局域网 IP：

```conf
address=/contribute.live-video.net/192.168.x.x
address=/global-contribute.live-video.net/192.168.x.x
address=/apn20.contribute.live-video.net/192.168.x.x
address=/irc.twitch.tv/192.168.x.x
address=/tmi.twitch.tv/192.168.x.x
```

修改 `data/nginx.conf`：

- 找到 `push <推流地址>;`。
- 改成你自己的 B 站推流地址，整串都要保留正确，包括 `streamname`、`key` 或其他参数。

启动容器：

```bash
docker compose up -d --build
```

常用命令：

```bash
docker compose ps
docker compose logs -f ps5-bilibili-danmaku
docker compose logs -f rtmp-monitor
docker compose restart ps5-bilibili-danmaku
docker compose down
```

Web 保存配置后，如果页面提示需要重启弹幕服务，执行：

```bash
docker compose restart ps5-bilibili-danmaku
```

## 电脑侧自检

先不要急着去 PS5，建议在 Docker 电脑上检查服务是否正常。

打开 Web 面板：

```text
http://<Docker电脑局域网IP>:15500/
```

检查状态接口：

```bash
curl http://127.0.0.1:15500/status
curl http://127.0.0.1:15500/api/rtmp/status
curl http://127.0.0.1:17890/
```

检查 DNS 是否解析到 Docker 电脑：

```bash
nslookup irc.twitch.tv 127.0.0.1
nslookup global-contribute.live-video.net 127.0.0.1
```

期望结果：

- `docker compose ps` 中四个服务处于 `Up` 或 healthy 状态。
- `status` 中能看到 `irc_running=true`、`danmaku_running=true`。
- `nslookup` 返回 Docker 电脑的局域网 IP。
- `http://127.0.0.1:17890/` 能打开 RTMP 统计页。

## 配置 PS5 网络

两种网络方案都需要满足同一个基础条件：PS5 必须能连到 Docker 电脑，并且 PS5 使用的 DNS 要指向 Docker 电脑的局域网 IP。这样 PS5 访问 Twitch RTMP 和 IRC 域名时，才会被本机 `dnsmasq` 劫持到容器。

在 PS5「设置 -> 网络 -> 设定互联网连接」中，建议给 PS5 配置固定 IP，或确保路由器已为 PS5 做 DHCP 保留。

### 方案 A：ImmortalWrt 路由器

适合家里路由器已刷 ImmortalWrt，并由路由器侧处理 OpenClash 或类似网络配置的环境。

- 在路由器侧把 PS5 使用的 DNS 指向 Docker 电脑的局域网 IP，或在 PS5 网络设置里手动把主 DNS 和备用 DNS 都填成 Docker 电脑 IP。
- PS5 上通常不需要再开启代理服务器，由路由器侧处理外网访问。
- 改完 DNS 后，建议 PS5 断网重连一次，确保新的 DNS 生效。

### 方案 B：Clash Verge + PS5 系统代理

适合没有 ImmortalWrt，只在运行 Docker 的 Windows 电脑上使用 Clash Verge 出境的环境。

在 Clash Verge 中建议这样设置：

- 系统代理：关闭。
- 虚拟网卡或 TUN：关闭。
- 局域网连接或 Allow LAN：开启。
- 代理模式：全局。
- 节点：选择一个可用节点。

在 Clash Verge 设置里记下混合端口或 HTTP 代理端口，不同版本名称略有差异，常见为 `7897`，以你本机界面显示为准。同时确认 Windows 防火墙允许该端口的局域网入站。

PS5 网络里需要同时设置：

1. DNS：主 DNS 和必要时备用 DNS 填 Docker 电脑的局域网 IP。
2. 代理服务器：开启「使用代理服务器」。
3. 代理地址：Clash 所在电脑的局域网 IP。
4. 代理端口：Clash Verge 中看到的混合端口或 HTTP 代理端口。

方案 B 下，PS5 的外网流量经 Clash 所选节点；Twitch 推流和 IRC 相关域名仍由本机 `dnsmasq` 劫持到 Docker，两者需要同时配置。

## 在 PS5 开播并验证

配置完成后，在 PS5 上停止当前直播并重新开始直播，不要只保持原会话。重开播会触发 PS5 重新解析域名，并连接本地 RTMP 和 IRC 服务。

然后在 B 站直播间发送一条测试弹幕，查看弹幕服务日志：

```bash
docker compose logs -f ps5-bilibili-danmaku
```

看到以下日志中的几类，就说明链路在逐步打通：

- `检测到PS5连接`
- `已加入频道`
- `抓取到N条新弹幕`
- `转发弹幕 [...]`

RTMP 推流状态可以在 Web 面板查看，也可以打开：

```text
http://<Docker电脑局域网IP>:17890/
```

`rtmp-monitor` 会把 RTMP 状态同步到 Web 面板。需要单独看监控日志时执行：

```bash
docker compose logs -f rtmp-monitor
```

## RTMP 监控调试

如果 Web 面板不显示 RTMP 推流状态，按这个顺序排查：

```bash
docker compose logs -f rtmp-monitor
curl http://127.0.0.1:17890/
curl http://127.0.0.1:15500/api/rtmp/status
```

如果需要更详细的 RTMP 页面解析日志，可以临时启用调试版监控：

1. 打开 `danmaku-v2/docker-compose.yml`。
2. 将 `rtmp-monitor` 的 `command` 从 `["python", "monitor_rtmp.py"]` 改为 `["python", "monitor_rtmp_debug.py"]`。
3. 将 `DEBUG_MODE=false` 改为 `DEBUG_MODE=true`。
4. 重启监控容器：

```bash
docker compose up -d --build rtmp-monitor
docker compose logs -f rtmp-monitor
```

调试输出会写入 `danmaku-v2/debug_output/`，日志会帮助判断监控脚本是否拿到了 RTMP 统计页。

## 本地运行弹幕服务

一般推荐 Docker 方式。若只想本地调试 Python 脚本，可以在 `danmaku-v2/` 中运行：

```bash
pip install -r requirements.txt
python danmaku_forward.py
```

另开一个终端运行 RTMP 监控，前提是本机已有可访问的 RTMP 服务和统计页：

```bash
python monitor_rtmp.py
```

可用环境变量示例：

```powershell
$env:RTMP_MONITOR_URL = "http://127.0.0.1:17890"
$env:DANMAKU_API_URL = "http://127.0.0.1:5000/api/rtmp/status/update"
```

## 排障清单

如果 `status` 正常但弹幕没有转发，优先看日志里是否出现“无活跃PS5客户端”。这通常表示 DNS 没生效、PS5 没完整重开播，或 Windows 防火墙拦了 `6667/TCP`。

如果看到“抓取到N条新弹幕”，说明 B 站弹幕抓取正常。下一步重点检查 PS5 IRC 是否连上：`active_clients` 是否大于 0、`irc.twitch.tv` 是否解析到 Docker 电脑 IP、PS5 是否重开播。

如果看到“检测到PS5连接”“设置昵称”“已加入频道”，说明 IRC 通道已建立，后续应该能看到“转发弹幕 [...]”。

如果 RTMP 统计页显示 `Accepted: 0`，说明 PS5 没连上本地推流入口。优先检查：

- `1935/TCP` 是否映射并监听。
- `contribute.live-video.net` 或 `global-contribute.live-video.net` 是否解析到 Docker 电脑 IP。
- PS5 到 Docker 电脑的局域网连通性。
- Windows 防火墙是否放行 `1935/TCP`。

常用恢复步骤：

1. 在 `ps5_twittch/danmaku-v2` 中执行 `docker compose up -d --build`。
2. 在 PS5 上停止直播并重新开始直播。
3. 在 B 站直播间发送一条测试弹幕。
4. 观察 `ps5-bilibili-danmaku` 日志是否出现“转发弹幕”。

## 注意事项

- `data/dnsmasq.conf` 里的局域网 IP 一旦变化，PS5 就可能连不到本机容器。更换 Wi-Fi、有线网络、路由器或 DHCP 地址后要重新检查。
- Windows 防火墙至少需要放行 `6667/TCP`、`1935/TCP`、`53/UDP`。如果使用 Clash Verge 方案，还要放行 Clash 的局域网代理端口。
- `data/nginx.conf` 包含 B 站推流地址，`data/bili_cookies.json` 包含 B 站登录态，`docker-compose.yml` 里有 dnsmasq Web 默认账号密码，公开仓库前请确认没有泄露敏感信息。
- `data/`、`logs/`、`debug_output/` 都可能用于排障，首次跑通前不要随意删除。
- `without_danmaku/` 不提供弹幕 IRC 服务。如果 PS5 开启聊天相关连接，可能不会有弹幕回显，这是该变体的预期限制。
