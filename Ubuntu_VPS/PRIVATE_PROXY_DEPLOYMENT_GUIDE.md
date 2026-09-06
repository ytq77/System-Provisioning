# sing-box 三协议私有节点长期稳定部署说明书

本文说明如何在一台 Ubuntu VPS 上部署以下私有网络服务：

- AnyTLS + TLS 1.3 + ECH
- VLESS + XTLS Vision + REALITY
- Hysteria2 + TLS 1.3 + Salamander
- 由 Caddy 提供 HTTPS 私有订阅
- Sparkle 与 OpenClash/Mihomo 使用不同凭据

文中不包含任何真实 IP、域名、UUID、密码、密钥、订阅路径或证书指纹。所有以 `__...__` 表示的内容都必须替换为自己的值。

本文对应的已验证基线为 Ubuntu 24.04、sing-box 1.14.0、Caddy 2.11.4。未来升级后应重新阅读变更说明并完成全文末尾的验收，不能假定跨版本配置一定兼容。

## 1. 最终架构与端口

| 用途 | 协议 | 端口 | 进程 |
|---|---:|---:|---|
| SSH 管理 | TCP | 22 | OpenSSH |
| HTTP 跳转及 ACME 校验 | TCP | 80 | Caddy |
| HTTPS 私有订阅 | TCP | 443 | Caddy |
| AnyTLS + ECH | TCP | 8443 | sing-box |
| VLESS REALITY | TCP | 20963 | sing-box |
| Hysteria2 | UDP | 20963 | sing-box |

TCP 与 UDP 是两套独立端口空间，因此 VLESS/TCP 20963 和 Hysteria2/UDP 20963 可以同时使用，不会发生端口冲突。

期望结果：

```text
客户端 A ─┬─ AnyTLS/TCP 8443 ───────────┐
         ├─ VLESS REALITY/TCP 20963 ────┼─> sing-box ─> Internet
         └─ Hysteria2/UDP 20963 ────────┘

客户端 B 使用另一套密码和 UUID

客户端 ── HTTPS/TCP 443 ──> Caddy ──> 私有 YAML 订阅
```

## 2. 部署变量

开始前准备下列值，不要直接把密钥粘贴进公开仓库：

```bash
SERVER_IP='__SERVER_IP__'
PUBLIC_DOMAIN='__PUBLIC_DOMAIN__'
INNER_SNI='__INNER_SNI__'
REALITY_TARGET='__REALITY_TARGET__'
ADMIN_USER='__ADMIN_USER__'
```

- `SERVER_IP`：VPS 公网 IPv4。
- `PUBLIC_DOMAIN`：用于 Caddy HTTPS、AnyTLS/Hy2 证书和公开连接名称。
- `INNER_SNI`：AnyTLS 在 ECH 内使用的真实 SNI；可以不配置公开 DNS 记录。
- `REALITY_TARGET`：稳定、支持 TLS 1.3、从 VPS 可直接访问的 REALITY 握手目标。
- `ADMIN_USER`：具备公钥登录和 sudo 权限的普通用户。

建议使用独立子域名。DNS 中只需要为 `PUBLIC_DOMAIN` 创建指向 `SERVER_IP` 的 A 记录，并保持为“仅 DNS”。普通 CDN HTTP 代理不能直接转发这些 AnyTLS、REALITY 和 Hysteria2 入站。

## 3. 云安全组

云厂商安全组和 VPS 本机防火墙必须同时放行。建议入站规则：

```text
TCP 22       来源尽量限制为管理网络；地址不固定时可暂时开放
TCP 80       0.0.0.0/0
TCP 443      0.0.0.0/0
TCP 8443     0.0.0.0/0
TCP 20963    0.0.0.0/0
UDP 20963    0.0.0.0/0
```

不要因为云安全组已放行就跳过本机防火墙；也不要开放未使用的连续端口段。

## 4. 系统准备与 SSH

先使用云厂商注入的公钥登录普通用户，再进入 root 环境：

```bash
ssh "${ADMIN_USER}@${SERVER_IP}"
sudo -i
```

安装基础依赖：

```bash
apt-get update
apt-get install -y \
  ca-certificates curl gnupg jq openssl \
  iptables iptables-persistent netfilter-persistent
```

确认时间同步。REALITY 对系统时间偏差敏感：

```bash
timedatectl status
timedatectl show -p NTPSynchronized
```

必须得到：

```text
NTPSynchronized=yes
```

### 4.1 只允许普通用户加 sudo

在确认普通用户公钥登录和无交互 sudo 均正常后，创建最优先的 SSH 配置片段：

```text
# /etc/ssh/sshd_config.d/00-local-hardening.conf
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
X11Forwarding no
```

校验并平滑重载：

```bash
sshd -t
systemctl reload ssh
```

保持当前会话不要退出，另开终端验证：

```bash
ssh "${ADMIN_USER}@${SERVER_IP}"
sudo -n id -un
```

输出必须为 `root`。只有新连接验证成功后，才移除 root 的活动授权公钥：

```bash
rm -f -- /root/.ssh/authorized_keys
```

最终检查：

```bash
sshd -T | grep -E '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|x11forwarding) '
systemctl is-enabled ssh.socket
systemctl is-active ssh.socket
```

Ubuntu 24.04 可能由 `ssh.socket` 启动 SSH；此时 `ssh.service` 显示 disabled 不代表开机后无法登录，只要 `ssh.socket` 为 enabled/active 即可。

## 5. 安装 sing-box

优先使用 sing-box 官方 APT 仓库：

```bash
mkdir -p /etc/apt/keyrings
curl -fsSL https://sing-box.app/gpg.key -o /etc/apt/keyrings/sagernet.asc
chmod a+r /etc/apt/keyrings/sagernet.asc

cat >/etc/apt/sources.list.d/sagernet.sources <<'EOF'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
EOF

apt-get update
apt-get install -y sing-box
sing-box version
```

官方安装说明：<https://sing-box.sagernet.org/installation/package-manager/>

生产环境不要在未读变更说明的情况下自动跨大版本升级。升级前先生成稳定备份，并在升级后执行完整验收。

## 6. 生成 TLS 证书

AnyTLS 和 Hysteria2 共用一张本地证书。使用证书指纹固定时，可以采用自签 ECDSA P-256 证书：

```bash
install -d -o root -g sing-box -m 0750 /etc/sing-box/certs

openssl ecparam -genkey -name prime256v1 -noout \
  -out /etc/sing-box/certs/server-key.pem

openssl req -new -x509 -sha256 \
  -key /etc/sing-box/certs/server-key.pem \
  -out /etc/sing-box/certs/server-cert.pem \
  -days 397 \
  -subj "/CN=${PUBLIC_DOMAIN}" \
  -addext "subjectAltName=DNS:${PUBLIC_DOMAIN}"

chown root:sing-box \
  /etc/sing-box/certs/server-key.pem \
  /etc/sing-box/certs/server-cert.pem
chmod 0640 \
  /etc/sing-box/certs/server-key.pem \
  /etc/sing-box/certs/server-cert.pem
```

生成客户端需要固定的 SHA-256 指纹：

```bash
openssl x509 -in /etc/sing-box/certs/server-cert.pem \
  -noout -fingerprint -sha256
```

不要只设置 `skip-cert-verify: true` 而不校验证书指纹。证书私钥和订阅凭据必须仅 root 或 sing-box 服务组可读。

## 7. 生成 ECH 材料

sing-box 官方提供 ECH 密钥生成命令：

```bash
umask 077
work_dir=$(mktemp -d)
sing-box generate ech-keypair "${PUBLIC_DOMAIN}" >"${work_dir}/ech-all.pem"

awk '
  /^-----BEGIN ECH CONFIGS-----$/ {copy=1}
  copy {print}
  /^-----END ECH CONFIGS-----$/ {copy=0}
' "${work_dir}/ech-all.pem" >"${work_dir}/ech-config.pem"

awk '
  /^-----BEGIN ECH KEYS-----$/ {copy=1}
  copy {print}
  /^-----END ECH KEYS-----$/ {copy=0}
' "${work_dir}/ech-all.pem" >"${work_dir}/ech-key.pem"

install -d -o root -g sing-box -m 0750 /etc/sing-box/ech
install -o root -g sing-box -m 0640 \
  "${work_dir}/ech-key.pem" /etc/sing-box/ech/ech-key.pem
install -o root -g sing-box -m 0640 \
  "${work_dir}/ech-config.pem" /etc/sing-box/ech/ech-config.pem
```

`ech-key.pem` 只放服务器；`ech-config.pem` 中的 ECH CONFIGS 块提供给客户端。完成配置后安全清理临时目录。

ECH 字段说明：<https://sing-box.sagernet.org/configuration/shared/tls/#ech-fields>

## 8. 生成客户端凭据

每个客户端分别生成凭据，不要让 Sparkle 和 OpenClash 共用密码或 UUID：

```bash
openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\r\n'  # AnyTLS client A password
openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\r\n'  # AnyTLS client B password

sing-box generate uuid     # VLESS client A UUID
sing-box generate uuid     # VLESS client B UUID

openssl rand -hex 24       # Hy2 client A password
openssl rand -hex 24       # Hy2 client B password
openssl rand -hex 24       # Hy2 Salamander shared obfs password

sing-box generate reality-keypair
openssl rand -hex 8        # REALITY short ID
```

REALITY 私钥只进入服务端配置；公钥和 Short ID 进入客户端配置。UUID、AnyTLS/Hy2 密码、Salamander 密码、私有订阅 URL 都应按密码管理。

从 ECH CONFIGS PEM 块提取 Mihomo 节点使用的单行 Base64：

```bash
sed \
  -e '/^-----BEGIN ECH CONFIGS-----$/d' \
  -e '/^-----END ECH CONFIGS-----$/d' \
  /etc/sing-box/ech/ech-config.pem | tr -d '\r\n'
```

## 9. sing-box 服务端配置

下面是去标识化模板。替换全部占位符后保存为 `/etc/sing-box/config.json`：

```json
{
  "log": {
    "level": "warn",
    "timestamp": true
  },
  "inbounds": [
    {
      "type": "anytls",
      "tag": "anytls-ech-in",
      "listen": "0.0.0.0",
      "listen_port": 8443,
      "users": [
        {
          "name": "client-a",
          "password": "__ANYTLS_CLIENT_A_PASSWORD__"
        },
        {
          "name": "client-b",
          "password": "__ANYTLS_CLIENT_B_PASSWORD__"
        }
      ],
      "tls": {
        "enabled": true,
        "min_version": "1.3",
        "certificate_path": "/etc/sing-box/certs/server-cert.pem",
        "key_path": "/etc/sing-box/certs/server-key.pem",
        "ech": {
          "enabled": true,
          "key_path": "/etc/sing-box/ech/ech-key.pem"
        }
      }
    },
    {
      "type": "vless",
      "tag": "vless-reality-in",
      "listen": "0.0.0.0",
      "listen_port": 20963,
      "users": [
        {
          "name": "client-a",
          "uuid": "__VLESS_CLIENT_A_UUID__",
          "flow": "xtls-rprx-vision"
        },
        {
          "name": "client-b",
          "uuid": "__VLESS_CLIENT_B_UUID__",
          "flow": "xtls-rprx-vision"
        }
      ],
      "tls": {
        "enabled": true,
        "server_name": "__REALITY_TARGET__",
        "min_version": "1.3",
        "reality": {
          "enabled": true,
          "handshake": {
            "server": "__REALITY_TARGET__",
            "server_port": 443
          },
          "private_key": "__REALITY_PRIVATE_KEY__",
          "short_id": [
            "__REALITY_SHORT_ID__"
          ],
          "max_time_difference": "1m"
        }
      }
    },
    {
      "type": "hysteria2",
      "tag": "hy2-in",
      "listen": "0.0.0.0",
      "listen_port": 20963,
      "obfs": {
        "type": "salamander",
        "password": "__HY2_OBFS_PASSWORD__"
      },
      "users": [
        {
          "name": "client-a",
          "password": "__HY2_CLIENT_A_PASSWORD__"
        },
        {
          "name": "client-b",
          "password": "__HY2_CLIENT_B_PASSWORD__"
        }
      ],
      "ignore_client_bandwidth": true,
      "tls": {
        "enabled": true,
        "min_version": "1.3",
        "alpn": [
          "h3"
        ],
        "certificate_path": "/etc/sing-box/certs/server-cert.pem",
        "key_path": "/etc/sing-box/certs/server-key.pem"
      }
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
```

设置权限并验证：

```bash
chown root:sing-box /etc/sing-box/config.json
chmod 0640 /etc/sing-box/config.json
sing-box check -c /etc/sing-box/config.json
```

协议字段参考：

- AnyTLS：<https://sing-box.sagernet.org/configuration/inbound/anytls/>
- VLESS：<https://sing-box.sagernet.org/configuration/inbound/vless/>
- Hysteria2：<https://sing-box.sagernet.org/configuration/inbound/hysteria2/>
- TLS、ECH、REALITY：<https://sing-box.sagernet.org/configuration/shared/tls/>

## 10. sing-box systemd 加固

因为所有代理端口都高于 1024，sing-box 不需要保留额外 Linux capabilities。创建：

```ini
# /etc/systemd/system/sing-box.service.d/hardening.conf
[Service]
CapabilityBoundingSet=
AmbientCapabilities=
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
SystemCallArchitectures=native
ReadWritePaths=/var/lib/sing-box
UMask=0077
```

加载并启动：

```bash
systemctl daemon-reload
systemctl enable sing-box
systemctl restart sing-box
systemctl is-active sing-box
systemd-analyze security sing-box.service --no-pager
```

## 11. Hysteria2 UDP 缓冲区

创建 `/etc/sysctl.d/90-hysteria2.conf`：

```text
# QUIC receive/send buffer ceilings for the Hysteria2 inbound.
net.core.rmem_max=16777216
net.core.wmem_max=16777216
```

应用并核对：

```bash
sysctl --system
sysctl net.core.rmem_max net.core.wmem_max
```

不要因为“网上教程推荐”就盲目切换 BBR、修改 MTU 或增加大量 TCP 参数。先用实际运营商网络做 A/B 测试；如果当前线路已经达到接入带宽，保持内核默认拥塞控制通常更稳定。

## 12. VPS 本机防火墙

### 12.1 IPv4

不要清空 Oracle、AWS 等云镜像预置的 InstanceServices/元数据规则。先查看现有规则：

```bash
iptables -S
iptables -L INPUT -n -v --line-numbers
```

在最终 REJECT/DROP 之前确保存在以下允许规则。以下函数不会清空已有云镜像规则；如果链中已有最终拒绝规则，就插入到它之前，否则追加：

```bash
allow_new_port() {
  protocol=$1
  port=$2

  if iptables -C INPUT -p "$protocol" --dport "$port" \
      -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
    return
  fi

  reject_line=$(iptables -L INPUT --line-numbers -n \
    | awk '$2 == "REJECT" || $2 == "DROP" {print $1; exit}')

  if test -n "$reject_line"; then
    iptables -I INPUT "$reject_line" -p "$protocol" --dport "$port" \
      -m conntrack --ctstate NEW -j ACCEPT
  else
    iptables -A INPUT -p "$protocol" --dport "$port" \
      -m conntrack --ctstate NEW -j ACCEPT
  fi
}

allow_new_port tcp 22
allow_new_port tcp 80
allow_new_port tcp 443
allow_new_port tcp 8443
allow_new_port tcp 20963
allow_new_port udp 20963
```

部署完成后应检查顺序，并整理成“已建立连接、ICMP、回环、明确端口、最终拒绝”的可读顺序。

持久化前先做语法测试：

```bash
iptables-save >/etc/iptables/rules.v4
iptables-restore --test /etc/iptables/rules.v4
systemctl enable netfilter-persistent
```

### 12.2 IPv6 默认拒绝

如果不提供公网 IPv6 服务，也建议保留安全的默认拒绝，同时允许必要的 ICMPv6、回环和 DHCPv6：

```bash
ip6tables -F INPUT
ip6tables -A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
ip6tables -A INPUT -i lo -j ACCEPT
ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
ip6tables -A INPUT -p udp --sport 547 --dport 546 -j ACCEPT
ip6tables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -A INPUT -p tcp --dport 80 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -A INPUT -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -A INPUT -p tcp --dport 8443 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -A INPUT -p tcp --dport 20963 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -A INPUT -p udp --dport 20963 -m conntrack --ctstate NEW -j ACCEPT
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP
ip6tables -P OUTPUT ACCEPT
ip6tables-save >/etc/iptables/rules.v6
ip6tables-restore --test /etc/iptables/rules.v6
```

如果当前 SSH 是通过 IPv6 建立的，必须先确认 TCP 22 允许规则有效，再设置默认 DROP。

## 13. 安装 Caddy

使用 Caddy 官方稳定仓库：

```bash
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  > /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
chmod o+r /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy
```

官方安装说明：<https://caddyserver.com/docs/install>

Caddy 在站点地址使用有效域名时会自动申请并续期 HTTPS 证书；公网 DNS 必须正确，TCP 80/443 必须可达。参考：<https://caddyserver.com/docs/automatic-https>

## 14. 私有订阅

### 14.1 文件权限

```bash
install -d -o root -g caddy -m 0750 /var/lib/caddy/private-subscriptions
install -o root -g caddy -m 0640 client-a.yaml \
  /var/lib/caddy/private-subscriptions/client-a.yaml
install -o root -g caddy -m 0640 client-b.yaml \
  /var/lib/caddy/private-subscriptions/client-b.yaml
```

每个客户端生成独立的高熵 URL 路径：

```bash
openssl rand -hex 32
openssl rand -hex 32
```

不要把真实路径提交到 Git、聊天记录或公开订阅转换服务。对不能自定义 HTTP Authorization 请求头的客户端，高熵路径本身就是访问凭据。

### 14.2 Caddyfile 模板

```caddyfile
{
	servers {
		protocols h1 h2
	}
}

__PUBLIC_DOMAIN__ {
	@client_a {
		method GET HEAD
		path /__CLIENT_A_RANDOM_PATH__/client-a.yaml
	}
	handle @client_a {
		rewrite * /client-a.yaml
		root * /var/lib/caddy/private-subscriptions
		header Cache-Control "no-store"
		header Content-Type "application/yaml; charset=utf-8"
		header Referrer-Policy "no-referrer"
		header X-Content-Type-Options "nosniff"
		file_server
	}

	@client_b {
		method GET HEAD
		path /__CLIENT_B_RANDOM_PATH__/client-b.yaml
	}
	handle @client_b {
		rewrite * /client-b.yaml
		root * /var/lib/caddy/private-subscriptions
		header Cache-Control "no-store"
		header Content-Type "application/yaml; charset=utf-8"
		header Referrer-Policy "no-referrer"
		header X-Content-Type-Options "nosniff"
		file_server
	}

	handle {
		respond "Not Found" 404
	}
}
```

不启用 Caddy 访问日志；根路径和所有未知路径统一返回 404。`Cache-Control: no-store` 避免中间缓存订阅。Caddy `file_server` 官方说明：<https://caddyserver.com/docs/caddyfile/directives/file_server>

设置权限、格式化并校验：

```bash
chown root:caddy /etc/caddy/Caddyfile
chmod 0640 /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy
```

### 14.3 Caddy systemd 加固

```ini
# /etc/systemd/system/caddy.service.d/hardening.conf
[Service]
AmbientCapabilities=
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
SystemCallArchitectures=native
UMask=0077
```

应用：

```bash
systemctl daemon-reload
systemctl restart caddy
systemd-analyze security caddy.service --no-pager
```

## 15. Mihomo 客户端节点模板

建议节点的 `server` 直接填写 `SERVER_IP`，避免首次连接依赖域名解析；TLS SNI、ECH 和 REALITY 仍使用域名。以下字段适用于支持这些协议的 Mihomo 内核，升级客户端内核后应重新进行配置测试。

```yaml
proxies:
  - name: REGION-AnyTLS
    type: anytls
    server: __SERVER_IP__
    port: 8443
    password: __ANYTLS_CLIENT_PASSWORD__
    udp: true
    sni: __INNER_SNI__
    fingerprint: "__CERTIFICATE_SHA256_FINGERPRINT__"
    client-fingerprint: chrome
    ech-opts:
      enable: true
      config: "__ECH_CONFIG_BASE64__"

  - name: REGION-VLESS
    type: vless
    server: __SERVER_IP__
    port: 20963
    udp: true
    uuid: __VLESS_CLIENT_UUID__
    flow: xtls-rprx-vision
    packet-encoding: xudp
    tls: true
    servername: __REALITY_TARGET__
    client-fingerprint: chrome
    reality-opts:
      public-key: __REALITY_PUBLIC_KEY__
      short-id: __REALITY_SHORT_ID__
    network: tcp

  - name: REGION-Hy2
    type: hysteria2
    server: __SERVER_IP__
    port: 20963
    password: __HY2_CLIENT_PASSWORD__
    obfs: salamander
    obfs-password: __HY2_OBFS_PASSWORD__
    sni: __PUBLIC_DOMAIN__
    skip-cert-verify: false
    fingerprint: "__CERTIFICATE_SHA256_FINGERPRINT__"
    alpn:
      - h3
```

两个客户端分别生成两份 YAML，仅替换各自的 AnyTLS 密码、VLESS UUID 和 Hy2 密码。REALITY 公钥、Short ID、Hy2 混淆密码、证书指纹和 ECH 配置可以共享。

完整分流配置应在本地把这三个节点合并进已有 `proxies`、`proxy-groups` 和 `rules`。这样不依赖第三方订阅转换服务，也不会把私有订阅地址或节点凭据发送给第三方。

私用节点通常没有套餐流量额度，因此不必返回 `Subscription-Userinfo`。没有这个响应头只会导致客户端不显示“剩余流量”，不影响节点连接、限速或安全性。

## 16. 停用无用服务

如果没有使用 NFS，不需要 rpcbind/NFS RPC 端口：

```bash
systemctl disable --now rpcbind.socket rpcbind.service
systemctl reset-failed rpcbind.socket rpcbind.service || true
ss -lntup | grep ':111 ' && echo 'Unexpected rpcbind listener'
```

保留 AppArmor 和 unattended-upgrades：

```bash
systemctl enable --now apparmor
systemctl enable --now unattended-upgrades
```

公钥登录且完全关闭密码认证时，fail2ban 不是必需项；它主要减少扫描日志噪声，不能替代密钥认证和防火墙。

## 17. 自签证书到期检查

Caddy 管理的公网 HTTPS 证书会自行续期，但 AnyTLS/Hy2 使用的指纹固定证书需要协调轮换。建议每周检查，在剩余 60 天时产生错误日志。

检查脚本示例：

```bash
#!/usr/bin/env bash
set -euo pipefail

CERT_FILE=/etc/sing-box/certs/server-cert.pem
WARN_SECONDS=$((60 * 86400))

test -r "$CERT_FILE"
end_date=$(openssl x509 -in "$CERT_FILE" -noout -enddate | cut -d= -f2-)

if ! openssl x509 -in "$CERT_FILE" -noout -checkend "$WARN_SECONDS"; then
  logger -p daemon.err -t proxy-cert-check \
    "certificate expires within 60 days: $end_date"
  exit 1
fi

logger -p daemon.info -t proxy-cert-check "certificate healthy: $end_date"
```

对应 systemd service：

```ini
[Unit]
Description=Check private proxy certificate expiry
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/proxy-cert-check
User=root
Group=root
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX
LockPersonality=yes
MemoryDenyWriteExecute=yes
```

对应 timer：

```ini
[Unit]
Description=Weekly private proxy certificate check

[Timer]
OnCalendar=weekly
RandomizedDelaySec=2h
Persistent=true

[Install]
WantedBy=timers.target
```

校验与启用：

```bash
systemd-analyze verify \
  /etc/systemd/system/proxy-cert-check.service \
  /etc/systemd/system/proxy-cert-check.timer
systemctl daemon-reload
systemctl start proxy-cert-check.service
systemctl enable --now proxy-cert-check.timer
systemctl list-timers --all | grep proxy-cert-check
```

这只是到期检查，不是自动换证。轮换时必须同步完成：

1. 生成新证书并记录新指纹。
2. 更新两份客户端节点配置和完整订阅。
3. 校验 YAML 和 sing-box 临时配置。
4. 短暂维护窗口内替换服务端证书并重启 sing-box。
5. 两个客户端刷新订阅并验证。
6. 确认全部客户端迁移后再删除旧证书材料。

## 18. 稳定版备份

备份至少应包括：

```text
/etc/sing-box/config.json
/etc/sing-box/certs/
/etc/sing-box/ech/
/etc/sing-box/client-materials/
/etc/sing-box/full-config-sources/
/etc/caddy/Caddyfile
/var/lib/caddy/private-subscriptions/
/etc/iptables/rules.v4
/etc/iptables/rules.v6
/etc/sysctl.d/90-hysteria2.conf
/etc/ssh/sshd_config.d/00-local-hardening.conf
/etc/systemd/system/sing-box.service.d/
/etc/systemd/system/caddy.service.d/
/etc/systemd/system/proxy-cert-check.service
/etc/systemd/system/proxy-cert-check.timer
/usr/local/sbin/proxy-cert-check
```

归档中包含私钥、密码和订阅地址，必须设置为 root-only：

```bash
install -d -o root -g root -m 0700 /etc/sing-box/backups/current-stable
chmod 0600 /etc/sing-box/backups/current-stable/*
```

每次生成新归档后先完成：

```bash
gzip -t current-stable-config.tar.gz
tar -tzf current-stable-config.tar.gz >FILES.txt
sha256sum current-stable-config.tar.gz MANIFEST.txt RESTORE.txt FILES.txt >SHA256SUMS
sha256sum -c SHA256SUMS
```

只有新归档验证成功，才替换上一份 `current-stable`。不要使用未校验的宽泛通配符删除 `/etc`、`/var` 或用户目录。

同机备份只能防止误改配置，不能防止 VPS 磁盘或账号丢失。需要灾难恢复时，应把稳定归档加密后保存一份离线副本；不要上传明文私钥归档到公开 Git 仓库或网盘分享链接。

## 19. 上线前验证

### 19.1 配置与服务

```bash
sing-box check -c /etc/sing-box/config.json
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sshd -t
iptables-restore --test /etc/iptables/rules.v4
ip6tables-restore --test /etc/iptables/rules.v6

systemctl is-enabled sing-box caddy netfilter-persistent
systemctl is-active sing-box caddy netfilter-persistent
systemctl --failed
```

### 19.2 监听端口

```bash
ss -H -lntup | grep -E ':(22|80|443|8443|20963)([[:space:]]|$)'
```

必须看到：

```text
TCP 22
TCP 80
TCP 443
TCP 8443
TCP 20963
UDP 20963
```

不得看到未计划的 UDP 443 或连续端口段监听。

### 19.3 防火墙

```bash
iptables -S INPUT
ip6tables -S INPUT
```

确认：

- IPv4 的允许规则位于最终 REJECT/DROP 之前。
- IPv6 `INPUT` 默认策略为 DROP。
- 允许已建立连接、回环和必要 ICMP/ICMPv6。
- 云安全组与本机规则端口一致。

### 19.4 订阅

```bash
curl --fail --silent --show-error --output /dev/null \
  --write-out 'http=%{http_code}\n' \
  'https://__PUBLIC_DOMAIN__/__RANDOM_PATH__/client-a.yaml'

curl --silent --output /dev/null --write-out 'root=%{http_code}\n' \
  'https://__PUBLIC_DOMAIN__/'
```

预期订阅为 200，根路径为 404。检查响应头：

```bash
curl -I 'https://__PUBLIC_DOMAIN__/__RANDOM_PATH__/client-a.yaml'
```

应包含：

```text
Cache-Control: no-store
Content-Type: application/yaml; charset=utf-8
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```

### 19.5 客户端

1. 在 Sparkle/Mihomo 中更新订阅，确认恰好出现三个节点。
2. 在 OpenClash 中更新订阅并运行配置检查。
3. 分别选择三个节点，访问 HTTPS 测试页。
4. 使用同一网络、同一测速目标分别测试，避免把测速服务器差异误判为协议差异。
5. 至少执行三轮并记录中位数。

通过本地 HTTP 代理进行基本测试：

```bash
curl -x http://127.0.0.1:7890 \
  -o /dev/null -sS \
  -w 'connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
  https://cp.cloudflare.com
```

### 19.6 重启验收

```bash
reboot
```

等待服务器恢复后重新验证：

```bash
uptime
systemctl is-active sing-box caddy netfilter-persistent
systemctl is-active ssh.socket
ss -H -lntup | grep -E ':(22|80|443|8443|20963)([[:space:]]|$)'
sshd -T | grep '^permitrootlogin '
journalctl -b -u sing-box -p warning --no-pager
journalctl -b -u caddy -p warning --no-pager
```

预期 `permitrootlogin no`，sing-box/Caddy 没有启动错误，订阅仍返回 200。

## 20. 日常维护

每月或配置变更前后检查：

```bash
systemctl --failed
systemctl status sing-box caddy --no-pager
journalctl -u sing-box --since '24 hours ago' -p warning --no-pager
journalctl -u caddy --since '24 hours ago' -p warning --no-pager
df -h /
free -h
systemctl list-timers --all | grep -E 'apt|cert|fstrim'
```

升级流程：

1. 生成并校验新的稳定备份。
2. 阅读 sing-box/Caddy 变更说明。
3. `apt-get update` 后先查看将升级的软件包。
4. 升级软件。
5. 执行 sing-box、Caddy、SSH 和防火墙配置校验。
6. 重启相关服务并测试三个节点。
7. 最后安排一次整机重启验收。

## 21. 常见故障判断

### 所有节点超时

- 同时检查云安全组与本机 iptables。
- 确认域名 A 记录正确并为“仅 DNS”。
- 确认客户端 `server` IP、端口没有过期。
- 检查 sing-box 是否 active、端口是否真实监听。

### AnyTLS 失败

- 检查证书指纹是否与服务器当前证书一致。
- 检查客户端 ECH CONFIGS 是否对应服务器 ECH KEYS。
- 检查 `INNER_SNI` 和客户端内核对 ECH/AnyTLS 的支持。

### VLESS REALITY 失败

- 检查 UUID、公钥、Short ID 是否成套。
- 检查服务器时间同步。
- 检查 REALITY 目标是否仍支持 TLS 1.3 且从 VPS 可达。
- 不要把 VLESS 配置中的 REALITY 公钥误填成服务端私钥。

### Hysteria2 失败或速度不稳定

- 确认云安全组和本机都允许 UDP 20963。
- 检查 Salamander 密码、证书指纹和 ALPN `h3`。
- 使用不同运营商网络做 A/B；UDP 被限速时，服务器调参通常无法修复运营商路径问题。
- 检查 UDP 错误是否持续增长，而不是只看开机以来的累计值。

### 订阅可用但节点不可用

Caddy/443 与三个代理入站是独立服务。订阅返回 200 只能证明 Caddy 和 HTTPS 正常，不能证明 8443/TCP、20963/TCP、20963/UDP 均可达。

## 22. 完成标准

只有以下条件全部成立，才把部署标记为长期稳定版本：

- 三个协议使用独立且足够长的客户端凭据。
- TLS 证书经过指纹校验，没有裸用跳过验证。
- REALITY 私钥和客户端 UUID 未公开。
- 私有订阅路径具有足够随机性并禁止缓存。
- root SSH 与密码登录关闭，普通用户 sudo 已实测。
- IPv4/IPv6 防火墙均已持久化并经过重启验证。
- sing-box 与 Caddy 以非 root 用户运行并启用 systemd 加固。
- rpcbind/NFS RPC 在不使用时关闭。
- 证书到期检查定时器启用。
- 配置、监听、日志、订阅及三个客户端节点全部通过验证。
- 当前稳定归档通过 SHA-256 校验，并妥善保护其中的私钥和密码。
