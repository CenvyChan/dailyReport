/* 仅从受保护的状态端点轮询；不把服务端错误消息作为 HTML 插入。 */
(() => {
  const panel = document.getElementById('ea-task');
  if (!panel || panel.dataset.finished === 'true') return;
  const note = document.getElementById('ea-poll-note');
  let failures = 0;
  async function poll() {
    try {
      const response = await fetch(panel.dataset.statusUrl, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('status');
      const data = await response.json();
      const status = document.getElementById('ea-task-status');
      status.textContent = data.label;
      status.dataset.status = data.status;
      for (const item of data.items) {
        const article = [...panel.querySelectorAll('[data-kind]')].find(node => node.dataset.kind === item.kind);
        if (article) article.querySelector('.ea-result-status').textContent =
          ({SUCCESS: '已生成', FAILED: '生成失败', SKIPPED: '模块未购买，已跳过', PENDING: '等待生成'})[item.status] || item.status;
      }
      failures = 0;
      note.textContent = '';
      if (data.finished) { window.location.reload(); return; }
    } catch (_) {
      failures += 1;
      note.textContent = failures >= 3 ? '自动更新暂不可用，请刷新页面；任务仍会在后台运行。' : '正在重新连接进度服务…';
    }
    if (failures < 3) window.setTimeout(poll, 3000);
  }
  window.setTimeout(poll, 2000);
})();
