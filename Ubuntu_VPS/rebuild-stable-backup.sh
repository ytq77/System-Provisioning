#!/usr/bin/env bash
set -Eeuo pipefail

backup_root=/etc/sing-box/backups
stable_name=current-stable
stable_path="${backup_root}/${stable_name}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
new_path="${backup_root}/.${stable_name}.new-${stamp}"
old_path="${backup_root}/.${stable_name}.old-${stamp}"
failed_path="${backup_root}/.${stable_name}.failed-${stamp}"
old_moved=0
new_promoted=0

restore_on_error() {
  rc=$?
  trap - ERR INT TERM
  if [[ ${new_promoted} -eq 1 && -d ${stable_path} && -d ${old_path} ]]; then
    mv -- "${stable_path}" "${failed_path}" || true
    mv -- "${old_path}" "${stable_path}" || true
    rm -rf -- "${failed_path}" || true
  elif [[ ${old_moved} -eq 1 && ! -e ${stable_path} && -d ${old_path} ]]; then
    mv -- "${old_path}" "${stable_path}" || true
  fi
  if [[ -d ${new_path} ]]; then
    rm -rf -- "${new_path}"
  fi
  exit "${rc}"
}
trap restore_on_error ERR INT TERM

[[ ${EUID} -eq 0 ]]
[[ ! -L ${backup_root} ]]
[[ $(readlink -f -- "${backup_root}") == "${backup_root}" ]]
[[ -d ${stable_path} ]]
[[ ! -L ${stable_path} ]]
[[ $(readlink -f -- "${stable_path}") == "${stable_path}" ]]

mapfile -t existing_entries < <(find "${backup_root}" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)
[[ ${#existing_entries[@]} -eq 1 ]]
[[ ${existing_entries[0]} == "${stable_name}" ]]

paths=(
  etc/sing-box/config.json
  etc/sing-box/certs
  etc/sing-box/ech
  etc/sing-box/client-materials
  etc/sing-box/full-config-sources
  etc/caddy/Caddyfile
  var/lib/caddy/private-subscriptions
  etc/iptables/rules.v4
  etc/iptables/rules.v6
  etc/sysctl.d/90-hysteria2.conf
  etc/sysctl.d/99-bbr.conf
  etc/modules-load.d/tcp_bbr.conf
  etc/ssh/sshd_config.d/00-ytvp-disable-root.conf
  etc/ssh/sshd_config.d/60-vps-hardening.conf
  home/ubuntu/.ssh/authorized_keys
  etc/systemd/system/sing-box.service.d/hardening.conf
  etc/systemd/system/caddy.service.d/hardening.conf
  etc/systemd/system/ytvp-cert-check.service
  etc/systemd/system/ytvp-cert-check.timer
  usr/local/sbin/ytvp-cert-check
  usr/local/libexec/ytvp-generate-mihomo-full-config.py
)

for path in "${paths[@]}"; do
  [[ -e /${path} ]]
done

sing-box check -c /etc/sing-box/config.json
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sshd -t
iptables-restore --test /etc/iptables/rules.v4
ip6tables-restore --test /etc/iptables/rules.v6
[[ $(sysctl -n net.ipv4.tcp_congestion_control) == bbr ]]
[[ $(sysctl -n net.core.default_qdisc) == fq ]]
grep -Eq '^[[:space:]]*net\.ipv4\.tcp_congestion_control[[:space:]]*=[[:space:]]*bbr[[:space:]]*$' /etc/sysctl.d/99-bbr.conf
grep -Eq '^[[:space:]]*net\.core\.default_qdisc[[:space:]]*=[[:space:]]*fq[[:space:]]*$' /etc/sysctl.d/99-bbr.conf
grep -Eq '^[[:space:]]*tcp_bbr[[:space:]]*$' /etc/modules-load.d/tcp_bbr.conf

install -d -o root -g root -m 0700 "${new_path}"
archive="${new_path}/current-stable-config.tar.gz"

tar -C / -czpf "${archive}" -- "${paths[@]}"
gzip -t "${archive}"
tar -tzf "${archive}" | LC_ALL=C sort >"${new_path}/FILES.txt"

grep -Fxq 'etc/sysctl.d/99-bbr.conf' "${new_path}/FILES.txt"
grep -Fxq 'etc/modules-load.d/tcp_bbr.conf' "${new_path}/FILES.txt"
archive_entries=$(wc -l <"${new_path}/FILES.txt")
sing_box_version=$(sing-box version)
sing_box_version=${sing_box_version%%$'\n'*}

{
  echo 'Stable deployment backup'
  echo 'Contains credentials and private keys; keep root-only.'
  printf 'Created-UTC: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'OS: %s\n' "$(. /etc/os-release && printf '%s' "${PRETTY_NAME}")"
  printf 'Kernel: %s\n' "$(uname -r)"
  printf 'sing-box: %s\n' "${sing_box_version}"
  printf 'Caddy: %s\n' "$(caddy version)"
  echo 'Inbounds: AnyTLS/TCP 8443, VLESS-REALITY/TCP 20963, Hysteria2/UDP 20963'
  echo 'Subscription service: Caddy/TCP 80 and 443'
  echo 'SSH: public-key ubuntu account with sudo; direct root login disabled'
  echo 'IPv6 input policy: DROP'
  echo 'TCP congestion control: BBR with fq'
  printf 'Archive entries: %s\n' "${archive_entries}"
} >"${new_path}/MANIFEST.txt"

{
  echo 'Restore only to a compatible, trusted Ubuntu host.'
  echo 'This archive contains private keys, passwords, subscription addresses, and SSH authorization data.'
  echo '1. Install compatible sing-box, Caddy, iptables-persistent, and OpenSSH packages.'
  echo '2. Stop sing-box and Caddy.'
  echo '3. From /, extract current-stable-config.tar.gz while preserving owners and modes.'
  echo '4. Run systemctl daemon-reload and sysctl --system.'
  echo '5. Validate sing-box, Caddy, sshd, IPv4 rules, and IPv6 rules before applying them.'
  echo '6. Enable the saved services and timer, then restart the host and repeat all validation checks.'
} >"${new_path}/RESTORE.txt"

chown -R root:root "${new_path}"
find "${new_path}" -type d -exec chmod 0700 {} +
find "${new_path}" -type f -exec chmod 0600 {} +

(
  cd "${new_path}"
  sha256sum current-stable-config.tar.gz MANIFEST.txt RESTORE.txt FILES.txt >SHA256SUMS
  chmod 0600 SHA256SUMS
  sha256sum -c SHA256SUMS
)

mv -- "${stable_path}" "${old_path}"
old_moved=1
mv -- "${new_path}" "${stable_path}"
new_promoted=1

[[ ! -L ${stable_path} ]]
[[ $(readlink -f -- "${stable_path}") == "${stable_path}" ]]
(
  cd "${stable_path}"
  gzip -t current-stable-config.tar.gz
  sha256sum -c SHA256SUMS
)

[[ -d ${old_path} ]]
[[ ! -L ${old_path} ]]
[[ $(dirname -- "$(readlink -f -- "${old_path}")") == "${backup_root}" ]]
rm -rf -- "${old_path}"

mapfile -t final_entries < <(find "${backup_root}" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)
[[ ${#final_entries[@]} -eq 1 ]]
[[ ${final_entries[0]} == "${stable_name}" ]]

trap - ERR INT TERM
printf 'STABLE_BACKUP_REPLACED=%s\n' "${stable_path}"
printf 'ARCHIVE_ENTRIES=%s\n' "${archive_entries}"
echo 'OLD_BACKUP_REMOVED=yes'
