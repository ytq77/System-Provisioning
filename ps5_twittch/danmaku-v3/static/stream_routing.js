(() => {
  const byId = id => document.getElementById(id);
  const radios = [...document.querySelectorAll('input[name="stream-mode"]')];
  let initialized = false;
  let dirty = false;
  let busy = false;
  let fetching = false;
  const selectedMode = () => radios.find(r => r.checked).value;
  const showFields = () => { byId('routing-direct-fields').hidden = selectedMode() !== 'direct'; };
  radios.forEach(r => r.addEventListener('change', () => { dirty = true; showFields(); }));
  byId('routing-destination').addEventListener('input', () => { dirty = true; });

  function display(data) {
    if (!initialized || !dirty) {
      radios.forEach(r => { r.checked = r.value === data.mode; });
      showFields();
    }
    initialized = true;
    byId('routing-save').disabled = busy;
    byId('routing-mode-badge').textContent = data.mode === 'obs' ? '已选 OBS' : '已选直接转推';
    byId('routing-status').textContent = data.message;
    byId('routing-status').style.color = data.state === 'error' ? '#f85149' : '#8b949e';
    byId('routing-saved-hint').textContent = data.direct_url_configured
      ? '已保存推流地址。留空沿用；填写新地址后会替换。' : '首次直推需要填写完整地址。';
    byId('routing-obs-url').value = data.stream_key
      ? `rtmp://${window.location.hostname}:1935/app/${data.stream_key}` : '';
    byId('routing-copy').disabled = !data.stream_key;
  }

  async function refresh() {
    if (busy || fetching) return;
    fetching = true;
    try {
      const response = await fetch('/api/stream-routing', { cache: 'no-store' });
      if (!response.ok) throw new Error('读取失败');
      // A save may have begun while this GET was in flight.
      const data = await response.json();
      if (!busy) display(data);
    } catch (_) {
      if (!busy) {
        byId('routing-status').textContent = '无法连接管理服务，请检查容器状态；当前模式尚未确认。';
        byId('routing-status').style.color = '#f85149';
        byId('routing-obs-url').value = '';
        byId('routing-copy').disabled = true;
      }
    } finally { fetching = false; }
  }

  byId('routing-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !initialized) return;
    busy = true;
    byId('routing-save').disabled = true;
    radios.forEach(r => { r.disabled = true; });
    byId('routing-destination').disabled = true;
    try {
      const response = await fetch('/api/stream-routing', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: selectedMode(), direct_url: byId('routing-destination').value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '保存失败');
      dirty = false;
      byId('routing-destination').value = '';
      display(data);
    } catch (error) {
      byId('routing-status').textContent = `保存未确认：${error.message}。请刷新状态后重试。`;
      byId('routing-status').style.color = '#f85149';
    } finally {
      busy = false;
      byId('routing-save').disabled = false;
      radios.forEach(r => { r.disabled = false; });
      byId('routing-destination').disabled = false;
    }
  });

  byId('routing-copy').addEventListener('click', async () => {
    const input = byId('routing-obs-url');
    if (!input.value) return;
    try {
      if (!navigator.clipboard) throw new Error('HTTP fallback');
      await navigator.clipboard.writeText(input.value);
      byId('routing-status').textContent = 'OBS 媒体源地址已复制';
    } catch (_) {
      input.focus(); input.select();
      const copied = document.execCommand('copy');
      byId('routing-status').textContent = copied ? 'OBS 媒体源地址已复制' : '地址已选中，请按 Ctrl+C 复制';
    }
  });
  refresh();
  setInterval(refresh, 2000);
})();
