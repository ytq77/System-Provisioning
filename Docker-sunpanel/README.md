# SyncTV + 服务器监控服务部署指南

## ⚠️ 重要提示

**本仓库里的 `docker-compose.yml` 主要作为 GitHub 展示和部署模板。**

真实部署前需要按自己的服务器环境替换占位内容，不建议把真实 IP、账号、密码直接提交到仓库。

- `docker-compose.yml` 已经通过 `.env` 读取 `TAILSCALE_IP`、端口和 WebDAV 账号密码
- 真实部署时先复制 `.env.example` 为 `.env`，再把 `.env` 里的示例值改成自己的真实配置
- 当前可使用的 Tailscale 完整域名：`****.mole-flops.ts.net`
- Uptime Kuma 里的监控地址建议写完整域名，不要只写短名，避免尾网名变化或 DNS search 配置差异导致解析失败
- Sun-Panel 当前保留 `80:3002` 全网卡监听，因为它需要作为入口面板并检测其他服务状态；公网访问范围交给防火墙、安全组或 Tailscale ACL 控制
- WebDAV 是软件同步数据用的服务，保留；如果暴露公网，必须使用强密码，并按需用防火墙限制来源
- `.env` 是可选的额外本地文件，放在 `docker-compose.yml` 同目录；Docker Compose 会自动读取它，但只有 compose 里写了 `${变量名}` 时才会生效

例如：
```yaml
# Tailscale 部署（当前 compose 使用这种变量写法）
ports:
  - "${TAILSCALE_IP}:26861:12345"

# 直接部署（需要修改为）
ports:
  - "26861:12345"
```

---

## 1. 安装 Docker

### 安装 Docker Engine

```bash
curl -fsSL https://get.docker.com | bash
```

### 安装 Docker Compose 插件

```bash
sudo apt update && sudo apt install docker-compose-plugin -y
```

### 设置 Docker 开机自启

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

验证安装：

```bash
docker --version
docker compose version
```

### 可选：让 Docker 等 Tailscale 就绪后再启动

如果 compose 里的端口绑定到了 Tailscale IP，服务器重启时可能出现 Docker 先启动、Tailscale 网卡还没准备好的情况，导致容器端口绑定失败。可以给 Docker 增加 systemd 启动前检查。

下面示例里的 `100.96.63.22` 是当前服务器的 Tailscale IP，如果换机器部署，需要改成那台机器自己的 Tailscale IP：

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d

sudo tee /etc/systemd/system/docker.service.d/10-wait-tailscale.conf >/dev/null <<'EOF'
[Unit]
Wants=tailscaled.service
After=tailscaled.service

[Service]
ExecStartPre=/bin/sh -c 'for i in $(seq 1 60); do ip addr show tailscale0 | grep -q "100.96.63.22/32" && exit 0; sleep 1; done; exit 1'
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

如果同一台机器上的 Mumble 也绑定 Tailscale IP，可以用同样方式让它等 Tailscale：

```bash
sudo mkdir -p /etc/systemd/system/mumble-server.service.d

sudo tee /etc/systemd/system/mumble-server.service.d/10-wait-tailscale.conf >/dev/null <<'EOF'
[Unit]
Wants=tailscaled.service
After=tailscaled.service

[Service]
ExecStartPre=/bin/sh -c 'for i in $(seq 1 60); do ip addr show tailscale0 | grep -q "100.96.63.22/32" && exit 0; sleep 1; done; exit 1'
EOF

sudo systemctl daemon-reload
sudo systemctl restart mumble-server
```

---

## 2. 准备部署环境

### 创建数据目录

`docker-compose.yml` 文件和 `data` 文件夹需要在同一目录下。

```bash
# 创建数据目录
mkdir -p data/uptime-kuma
mkdir -p data/filecodebox
mkdir -p data/sun-panel/conf
mkdir -p data/sun-panel/uploads
mkdir -p data/sun-panel/database
mkdir -p data/synctv
mkdir -p data/webdav
mkdir -p data/kula
chmod 755 -R data/
```

### 修改配置（如需要）

如果使用 Tailscale，请确保 `.env` 中的 `TAILSCALE_IP` 是这台服务器自己的 Tailscale IP。

查看 Tailscale IP：

```bash
tailscale ip
```

### 可选：使用 `.env` 管理本机私有配置

`.env` 是额外的本地文件。当前 compose 已经使用它读取真实 IP、服务端口、WebDAV 账号和密码。

先复制示例文件：

```bash
cp .env.example .env
```

再编辑 `.env`：

示例：

```env
TAILSCALE_IP=100.96.63.22
TAILSCALE_DOMAIN=**********.ts.net
WEBDAV_USERNAME=your_username
WEBDAV_PASSWORD=your_strong_password
```

`.env.example` 可以提交到 GitHub，真实 `.env` 不要提交。当前目录的 `.gitignore` 已经排除了 `.env`。

---

## 3. 启动服务

### 方式一：使用 Docker Compose（推荐）

```bash
docker compose config -q
docker compose up -d
```

### 方式二：手动拉取镜像后启动

如果需要预先拉取镜像：

```bash
# 拉取所有镜像
docker compose pull

# 启动服务
docker compose config -q
docker compose up -d
```

### 查看服务状态

```bash
# 查看运行中的容器
docker compose ps

# 查看日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f synctv
```

### 更新 images 镜像
```bash
# 根据dockercompose更新
docker compose pull

# 更新完重新启动
docker compose config -q
docker compose up -d

# 删除旧镜像
docker image prune -f
```

---

## 4. 服务说明

部署完成后，以下服务将可用：

| 服务 | 端口 | 说明 | 访问地址 |
|------|------|------|----------|
| **Uptime Kuma** | 12861 | 服务监控 | `http://[IP]:12861` |
| **FileCodeBox** | 26861 | 文件分享 | `http://[IP]:26861` |
| **Excalidraw** | 23971 | 在线绘图 | `http://[IP]:23971` |
| **Sun-Panel** | 80 | 管理面板 | `http://[IP]` |
| **Kula** | 61208 | 系统监控 | `http://[IP]:61208` |
| **SyncTV** | 23862 | 同步播放 | `http://[IP]:23862` |
| **WebDAV** | 22263 | WebDAV 文件服务（bytemark/webdav） | `http://[IP]:22263` |

> **注意**：
> - `[IP]` 为你的 Tailscale IP、服务器公网 IP，或完整 MagicDNS 域名 `**********mole-flops.ts.net`
> - Uptime Kuma 和 Kula 使用 host 网络模式，端口由程序决定
> - Sun-Panel 保留全网卡监听，用于入口面板和服务状态检测
> - WebDAV 用于软件同步数据，是否公网可访问按实际客户端需求决定
> - 建议通过防火墙限制端口访问，优先仅允许 Tailscale 网络访问

---

## 5. 配置监控项

服务启动后，在 **Uptime Kuma**（`http://[IP]:12861`）中配置其余监控项：

1. 访问 Uptime Kuma 管理界面
2. 添加需要监控的服务和端点
3. 设置告警通知（可选）

建议监控地址使用完整域名，例如：

```text
http://****.mole-flops.ts.net:26861
http://****.mole-flops.ts.net:23971
http://****.mole-flops.ts.net:23862
http://****.mole-flops.ts.net:22263
```

如果服务只绑定了 Tailscale IP，这些地址需要从尾网内访问才会通。

---

## 6. 本地 Alist 服务配置（通过 Tailscale 挂载到服务器）

### 安装本地 Alist（Windows）

如果需要把本地影音文件提供给服务器端 SyncTV 播放，可在本机安装 Alist，再通过 Tailscale 内网地址让服务器访问：

```bash
# 使用 nssm 安装 Alist 为 Windows 服务
.\nssm install alist
```

### 配置本地媒体文件夹

1. 访问本地 Alist 管理界面：`http://localhost:5244`
2. 登录管理后台（首次访问会显示初始密码）
3. 添加存储，选择本地路径
4. 配置媒体文件夹路径（例如：`D:\Movies`）

### 在服务器端 SyncTV 中挂载本地 Alist

1. **进入 SyncTV 房间**
   - 访问 `http://[服务器IP]:23862`
   - 创建或加入房间

2. **添加 WebDAV 资源**
   - 点击 "添加视频" → 选择 "WebDAV"
   - **服务器地址**: `http://[你的本机Tailscale地址]:5244`
   - **路径**: `/local`（或你在 Alist 中配置的路径）
   - 如果需要认证，输入 Alist 的用户名和密码

> 说明：
> - 本地 Alist 运行在你的个人设备上（例如 Windows）
> - 服务器通过 Tailscale 访问该 Alist，因此无需把本地服务暴露到公网
> - 该方式等价于把本地媒体库“挂载”给服务器端应用使用

---

## 7. 常用管理命令

### 服务管理

```bash
# 启动所有服务
docker compose up -d

# 停止所有服务
docker compose down

# 重启所有服务
docker compose restart

# 重启特定服务
docker compose restart synctv

# 查看服务状态
docker compose ps

# 查看服务日志
docker compose logs -f [服务名]
```

### 数据备份

```bash
# 备份数据目录
tar --ignore-failed-read -czf backup-$(date +%Y%m%d).tar.gz docker-compose.yml .env data/

# 恢复数据
tar -xzf backup-YYYYMMDD.tar.gz
```

如果配置了 systemd 等待 Tailscale 的 drop-in，也可以额外备份：

```bash
sudo tar --ignore-failed-read -czf systemd-tailscale-wait-$(date +%Y%m%d).tar.gz \
  /etc/systemd/system/docker.service.d/10-wait-tailscale.conf \
  /etc/systemd/system/mumble-server.service.d/10-wait-tailscale.conf
```

### 更新服务

```bash
# 拉取最新镜像
docker compose pull

# 重新创建并启动容器
docker compose config -q
docker compose up -d --force-recreate
```

---

## 8. 故障排查

### 端口冲突

如果遇到端口被占用：

```bash
# 查看端口占用
sudo netstat -tulpn | grep [端口号]

# 或使用 ss
sudo ss -tulpn | grep [端口号]
```

### 权限问题

如果遇到权限错误：

```bash
# 修复数据目录权限
sudo chown -R $USER:$USER data/
```

### 查看容器日志

```bash
# 查看所有服务日志
docker compose logs

# 查看特定服务日志
docker compose logs synctv
docker compose logs webdav

# 实时跟踪日志
docker compose logs -f synctv
```

### 无法访问服务

1. 检查防火墙规则
2. 确认 Tailscale 连接状态（如使用 Tailscale）
3. 检查容器是否正常运行：`docker compose ps`
4. 查看容器日志排查错误

---

## 9. 安全建议

1. **使用 Tailscale**：建议通过 Tailscale 内网访问，避免不必要的公网暴露
2. **防火墙配置**：限制端口访问，仅允许信任的 IP；Sun-Panel 全网卡监听时尤其要确认安全组和 UFW 规则
3. **WebDAV 密码**：WebDAV 用于同步数据时必须使用强密码，公网可访问时建议额外限制来源 IP
4. **不要提交密钥**：真实 IP、账号、密码放到服务器本地或 `.env`，不要提交到 GitHub
5. **定期更新**：定期更新 Docker 镜像以获取安全补丁
6. **数据备份**：定期备份 `data/` 目录和本机私有配置

---

## 相关链接

- [SyncTV 官方文档](https://synctv.net/)
- [Alist 官方文档](https://alist.nn.ci/)
- [Uptime Kuma 文档](https://github.com/louislam/uptime-kuma)
- [Tailscale 文档](https://tailscale.com/kb/)
