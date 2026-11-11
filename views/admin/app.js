const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const app = document.getElementById('app');
const state = {
  tab: 'overview', overview: null, rules: [], total: 0, page: 1, pageSize: 12,
  folders: [],
  filters: { search: '', match_type: '', enabled: '', group_id: '', folder_id: '' },
  stats: [], settings: null, draft: null, folderDialog: null, confirmDialog: null, pendingImport: null, notice: '', error: '', loading: true, noticeTimer: null,
};

const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[ch]));
const json = value => JSON.stringify(value, null, 2);
const apiGet = (endpoint, params = {}) => bridge.apiGet(endpoint, params);
const apiPost = (endpoint, body = {}) => bridge.apiPost(endpoint, body);

// Material Design Icons, the set used by the AstrBot dashboard.
const ICONS = {
  dashboard: 'M19,5V7H15V5H19M9,5V11H5V5H9M19,13V19H15V13H19M9,17V19H5V17H9M21,3H13V9H21V3M11,3H3V13H11V3M21,11H13V21H21V11M11,15H3V21H11V15Z',
  list: 'M7,5H21V7H7V5M7,13V11H21V13H7M4,4.5A1.5,1.5 0 0,1 5.5,6A1.5,1.5 0 0,1 4,7.5A1.5,1.5 0 0,1 2.5,6A1.5,1.5 0 0,1 4,4.5M4,10.5A1.5,1.5 0 0,1 5.5,12A1.5,1.5 0 0,1 4,13.5A1.5,1.5 0 0,1 2.5,12A1.5,1.5 0 0,1 4,10.5M7,19V17H21V19H7M4,16.5A1.5,1.5 0 0,1 5.5,18A1.5,1.5 0 0,1 4,19.5A1.5,1.5 0 0,1 2.5,18A1.5,1.5 0 0,1 4,16.5Z',
  plus: 'M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z',
  swap: 'M9,3L5,7H8V14H10V7H13M16,17V10H14V17H11L15,21L19,17H16Z',
  chart: 'M9 17H7V10H9V17M13 17H11V7H13V17M17 17H15V13H17V17M19 19H5V5H19V19.1M19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V5C21 3.9 20.1 3 19 3Z',
  cog: 'M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10M10,22C9.75,22 9.54,21.82 9.5,21.58L9.13,18.93C8.5,18.68 7.96,18.34 7.44,17.94L4.95,18.95C4.73,19.03 4.46,18.95 4.34,18.73L2.34,15.27C2.21,15.05 2.27,14.78 2.46,14.63L4.57,12.97L4.5,12L4.57,11L2.46,9.37C2.27,9.22 2.21,8.95 2.34,8.73L4.34,5.27C4.46,5.05 4.73,4.96 4.95,5.05L7.44,6.05C7.96,5.66 8.5,5.32 9.13,5.07L9.5,2.42C9.54,2.18 9.75,2 10,2H14C14.25,2 14.46,2.18 14.5,2.42L14.87,5.07C15.5,5.32 16.04,5.66 16.56,6.05L19.05,5.05C19.27,4.96 19.54,5.05 19.66,5.27L21.66,8.73C21.79,8.95 21.73,9.22 21.54,9.37L19.43,11L19.5,12L19.43,13L21.54,14.63C21.73,14.78 21.79,15.05 21.66,15.27L19.66,18.73C19.54,18.95 19.27,19.04 19.05,18.95L16.56,17.95C16.04,18.34 15.5,18.68 14.87,18.93L14.5,21.58C14.46,21.82 14.25,22 14,22H10M11.25,4L10.88,6.61C9.68,6.86 8.62,7.5 7.85,8.39L5.44,7.35L4.69,8.65L6.8,10.2C6.4,11.37 6.4,12.64 6.8,13.8L4.68,15.36L5.43,16.66L7.86,15.62C8.63,16.5 9.68,17.14 10.87,17.38L11.24,20H12.76L13.13,17.39C14.32,17.14 15.37,16.5 16.14,15.62L18.57,16.66L19.32,15.36L17.2,13.81C17.6,12.64 17.6,11.37 17.2,10.2L19.31,8.65L18.56,7.35L16.15,8.39C15.38,7.5 14.32,6.86 13.12,6.62L12.75,4H11.25Z',
  refresh: 'M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z',
  close: 'M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;
const MATCH_LABELS = { exact: '精确', contains: '包含', prefix: '前缀', regex: '正则' };

function notify(message, error = false) {
  if (state.noticeTimer) clearTimeout(state.noticeTimer);
  state.notice = error ? '' : message;
  state.error = error ? message : '';
  renderNotices();
  state.noticeTimer = setTimeout(() => { state.notice = ''; state.error = ''; state.noticeTimer = null; renderNotices(); }, 4500);
}

function noticesHtml() {
  return `${state.error ? `<div class="notice error" role="alert">${esc(state.error)}</div>` : ''}${state.notice ? `<div class="notice success" role="status">${esc(state.notice)}</div>` : ''}`;
}

// Notices are patched in place so a message never rebuilds a form the user is typing in.
function renderNotices() {
  const box = document.getElementById('notices');
  if (box) box.innerHTML = noticesHtml();
}

function nav() {
  return [['overview', '总览', 'dashboard'], ['rules', '回复列表', 'list'], ['create', '创建回复', 'plus'],
    ['transfer', '导入 / 导出', 'swap'], ['stats', '触发统计', 'chart'], ['settings', '全局设置', 'cog']];
}

function shell(body, title, subtitle = '') {
  const tabs = nav().map(([id, label, name]) => `<button type="button" class="tab ${state.tab === id ? 'active' : ''}" ${state.tab === id ? 'aria-current="page"' : ''} data-nav="${id}">${icon(name)}<span>${label}</span></button>`).join('');
  const version = state.overview?.version ? `<div class="sidebar-foot">版本 ${esc(state.overview.version)}</div>` : '';
  return `<div class="layout">
    <aside class="sidebar">
      <nav class="nav" aria-label="管理页面">${tabs}</nav>
      ${version}
    </aside>
    <main class="content">
      <div class="page-head"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div><button type="button" class="btn text" data-action="refresh">${icon('refresh')}刷新</button></div>
      ${body}
    </main>
  </div>
  <div id="notices">${noticesHtml()}</div>`;
}

function metric(label, value, detail) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></div>`;
}

function folderOptions(selected = '', includeAll = false) {
  const options = includeAll ? `<option value="">全部回复</option><option value="__none__" ${selected === '__none__' ? 'selected' : ''}>未分类回复</option>` : '<option value="">未分类</option>';
  return options + state.folders.map(folder => `<option value="${esc(folder.id)}" ${selected === folder.id ? 'selected' : ''}>${esc(folder.name)}</option>`).join('');
}

function overviewView() {
  const overview = state.overview || { total: 0, enabled: 0, disabled: 0, top_rules: [], folder_total: 0 };
  const top = overview.top_rules || [];
  const topRows = top.length
    ? `<div class="list-card">${top.map(row => `<div class="row"><h4>${esc(row.name)}</h4><span class="badge">${esc(row.trigger_count)} 次</span></div>`).join('')}</div>`
    : '<div class="empty">还没有触发统计。</div>';
  return shell(`<div class="stack">
    <section class="grid metrics">${metric('回复总数', overview.total, '全部自定义回复')}${metric('已启用', overview.enabled, '当前可触发')}${metric('已禁用', overview.disabled, '暂不参与匹配')}${metric('文件夹', overview.folder_total || state.folders.length, '分类数量')}</section>
    <section class="grid two">
      <div class="panel"><h3>最常触发回复</h3>${topRows}</div>
      <div class="panel"><h3>运行提示</h3><p>回复、统计、冷却和全局设置都保存在插件数据目录中，并使用原子写入。导入 / 导出页面可以备份或恢复当前回复及文件夹。</p><span class="badge ${state.settings?.require_wake ? 'good' : ''}">${state.settings?.require_wake ? '保留唤醒触发' : '已允许普通消息触发'}</span></div>
    </section>
  </div>`, '总览', '查看回复数量、文件夹和触发概况。');
}

function folderToolbar() {
  const selectedFolder = state.filters.folder_id && state.filters.folder_id !== '__none__' ? state.filters.folder_id : '';
  return `<div class="folder-toolbar"><select id="folder_filter" aria-label="文件夹筛选">${folderOptions(state.filters.folder_id, true)}</select><button type="button" class="btn text" data-action="new-folder">${icon('plus')}新建文件夹</button><button type="button" class="btn text" data-action="edit-folder" ${selectedFolder ? '' : 'disabled'}>编辑文件夹</button><button type="button" class="btn text danger" data-action="delete-folder" ${selectedFolder ? '' : 'disabled'}>删除文件夹</button></div>`;
}

function folderDialogView() {
  const dialog = state.folderDialog;
  if (!dialog) return '';
  const close = `<button class="modal-close" type="button" data-action="folder-cancel" aria-label="关闭">${icon('close')}</button>`;
  if (dialog.mode === 'delete') {
    return `<div class="modal-backdrop" data-folder-dialog-backdrop><section class="modal" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title"><div class="modal-head"><div><h3 id="folder-dialog-title">删除文件夹</h3><p>文件夹中的回复会保留，并移动到未分类。</p></div>${close}</div><div class="modal-warning">确定删除“${esc(dialog.name)}”吗？</div><div class="modal-actions"><button class="btn text" type="button" data-action="folder-cancel">取消</button><button class="btn tonal-danger" type="button" data-action="folder-submit">删除文件夹</button></div></section></div>`;
  }
  return `<div class="modal-backdrop" data-folder-dialog-backdrop><section class="modal" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title"><div class="modal-head"><div><h3 id="folder-dialog-title">${dialog.id ? '编辑文件夹' : '新建文件夹'}</h3><p>用文件夹整理自定义回复，之后仍可随时移动。</p></div>${close}</div><form id="folder-form"><div class="field"><label for="folder_name">文件夹名称</label><input id="folder_name" name="name" maxlength="80" value="${esc(dialog.name)}" placeholder="例如：菜单回复" autofocus></div><div class="field"><label for="folder_description">文件夹说明 <span class="hint">可选</span></label><textarea id="folder_description" name="description" maxlength="300" rows="3" placeholder="例如：常用菜单和帮助回复">${esc(dialog.description)}</textarea></div>${dialog.error ? `<div class="inline-error" role="alert">${esc(dialog.error)}</div>` : ''}<div class="modal-actions"><button class="btn text" type="button" data-action="folder-cancel">取消</button><button class="btn primary" type="submit">保存文件夹</button></div></form></section></div>`;
}

function confirmDialogView() {
  const dialog = state.confirmDialog;
  if (!dialog) return '';
  return `<div class="modal-backdrop" data-confirm-dialog-backdrop><section class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title"><div class="modal-head"><div><h3 id="confirm-dialog-title">${esc(dialog.title)}</h3><p>${esc(dialog.message)}</p></div><button class="modal-close" type="button" data-action="confirm-cancel" aria-label="关闭">${icon('close')}</button></div><div class="modal-actions"><button class="btn text" type="button" data-action="confirm-cancel">取消</button><button class="btn tonal-danger" type="button" data-action="confirm-submit">${esc(dialog.confirmLabel || '确认')}</button></div></section></div>`;
}

function rulesView() {
  const rows = state.rules || [];
  const option = (field, value, label) => `<option value="${value}" ${state.filters[field] === value ? 'selected' : ''}>${label}</option>`;
  const lastPage = Math.max(1, Math.ceil(state.total / state.pageSize));
  const body = rows.length ? rows.map(row => `<tr>
    <td><strong title="ID：${esc(row.id)}">${esc(row.name)}</strong></td>
    <td class="keywords">${esc((row.keywords || []).join('、'))}</td>
    <td>${esc(MATCH_LABELS[row.match_type] || row.match_type)}<div class="muted small">${row.case_sensitive ? '大小写敏感' : '大小写不敏感'}</div></td>
    <td><select class="folder-select" data-folder-rule="${esc(row.id)}" aria-label="为回复选择文件夹">${folderOptions(row.folder_id || '')}</select></td>
    <td>${esc(row.scope?.mode === 'whitelist' ? '白名单' : '黑名单')}<div class="muted small">${esc((row.scope?.group_ids || []).length)} 群 / ${esc((row.scope?.user_ids || []).length)} 用户</div></td>
    <td>${esc(row.priority)}</td>
    <td><span class="badge ${row.enabled ? 'good' : 'off'}">${row.enabled ? '启用' : '停用'}</span></td>
    <td><div class="row-actions"><button type="button" data-action="edit" data-id="${esc(row.id)}">编辑</button><button type="button" data-action="toggle" data-id="${esc(row.id)}">${row.enabled ? '禁用' : '启用'}</button><button type="button" data-action="copy" data-id="${esc(row.id)}">复制</button><button type="button" class="danger-text" data-action="delete" data-id="${esc(row.id)}">删除</button></div></td>
  </tr>`).join('') : '<tr><td colspan="8" class="empty">没有匹配的回复。</td></tr>';
  return shell(`<div class="panel">
    <div class="toolbar">
      <input class="grow" id="search" value="${esc(state.filters.search)}" placeholder="搜索回复名称或关键词" aria-label="搜索回复">
      <select id="match_type" aria-label="匹配方式"><option value="">全部匹配方式</option>${option('match_type', 'exact', '精确')}${option('match_type', 'contains', '包含')}${option('match_type', 'prefix', '前缀')}${option('match_type', 'regex', '正则')}</select>
      <select id="enabled" aria-label="启用状态"><option value="">全部状态</option>${option('enabled', 'true', '已启用')}${option('enabled', 'false', '已禁用')}</select>
      <input id="group_id" value="${esc(state.filters.group_id)}" placeholder="群号筛选" aria-label="群号筛选">
      <button type="button" class="btn tonal" data-action="apply-filter">查询</button>
      <button type="button" class="btn primary" data-nav="create">${icon('plus')}新建回复</button>
    </div>
    ${folderToolbar()}
    <div class="table-wrap"><table class="table"><thead><tr><th>回复</th><th>关键词</th><th>匹配</th><th>文件夹</th><th>作用域</th><th>优先级</th><th>状态</th><th>操作</th></tr></thead><tbody>${body}</tbody></table></div>
    <div class="pagination"><span>共 ${state.total} 条，第 ${state.page} / ${lastPage} 页</span><button type="button" class="btn text" data-action="prev" ${state.page <= 1 ? 'disabled' : ''}>上一页</button><button type="button" class="btn text" data-action="next" ${state.page >= Math.ceil(state.total / state.pageSize) ? 'disabled' : ''}>下一页</button></div>
  </div>`, '回复列表', '搜索、筛选、分页管理全部自定义回复。');
}

function draftDefaults() {
  return { id: '', name: '', folder_id: '', keywords: [], match_type: 'exact', case_sensitive: false, reply_type: 'text', content: '', random_replies: [], components: [], scope: { mode: 'blacklist', group_ids: [], user_ids: [] }, priority: 0, enabled: true, cooldown: { rule_seconds: 0, user_seconds: 0, group_seconds: 0 }, daily_limit: 0, time_range: { start: '', end: '' } };
}

function formView() {
  const d = state.draft || draftDefaults();
  const components = d.components || [];
  const selected = (current, value) => current === value ? 'selected' : '';
  const variables = '{sender} 发送者 ID　{nickname} 昵称　{group_id} 群号　{group_name} 群名称　{time} 当前时间　{date} 当前日期　{random} 随机数';
  const componentRows = components.map((item, index) => `<div class="component-row" data-index="${index}"><select data-comp="type" aria-label="组件类型"><option value="image" ${selected(item.type, 'image')}>图片</option><option value="video" ${selected(item.type, 'video')}>视频</option><option value="record" ${['record', 'voice'].includes(item.type) ? 'selected' : ''}>语音</option><option value="file" ${selected(item.type, 'file')}>文件</option><option value="at" ${selected(item.type, 'at')}>At</option></select><input data-comp="value" value="${esc(item.value || item.url || item.file || '')}" placeholder="URL、文件路径或用户 ID" aria-label="资源地址"><input data-comp="name" value="${esc(item.name || '')}" placeholder="显示名（可选）" aria-label="显示名"><button type="button" class="btn text danger remove-component" data-action="remove-component" data-index="${index}">移除</button></div>`).join('');
  const editor = d.reply_type === 'random'
    ? `<div class="field full"><label for="random_replies">随机回复内容 <span class="hint">每行一条，发送时随机抽取</span></label><textarea id="random_replies" rows="6">${esc((d.random_replies || []).join('\n'))}</textarea></div>`
    : d.reply_type === 'media'
      ? `<div class="field full"><span class="field-label">多媒体消息组件</span><div id="components">${componentRows}</div><div><button type="button" class="btn tonal" data-action="add-component">${icon('plus')}添加组件</button></div><span class="hint">媒体资源使用 AstrBot 原生消息链发送；路径或 URL 在触发时由平台适配器处理。</span></div>`
      : `<div class="field full"><label for="content">回复内容</label><textarea id="content" rows="${d.reply_type === 'composite' ? 8 : 5}" placeholder="支持动态变量，例如：你好，{nickname}！">${esc(d.content)}</textarea><span class="hint">${d.reply_type === 'composite' ? '每行一段，每段单独发送一条消息，最多 100 段。' : '支持下方列出的动态变量。'}</span></div>`;
  return shell(`<div class="stack">
    <section class="panel"><h3>基础信息</h3><div class="form-grid">
      <div class="field"><label for="name">回复名称</label><input id="name" value="${esc(d.name)}" placeholder="例如：菜单帮助"></div>
      <div class="field"><label for="folder_id">文件夹</label><select id="folder_id">${folderOptions(d.folder_id || '')}</select><span class="hint">可以在回复列表中随时移动或移出文件夹。</span></div>
      <div class="field full"><label for="keywords">关键词 <span class="hint">每行一个，可绑定多个</span></label><textarea id="keywords" rows="3" placeholder="菜单&#10;帮助">${esc((d.keywords || []).join('\n'))}</textarea></div>
      <div class="field"><label for="match_type">匹配方式</label><select id="match_type"><option value="exact" ${selected(d.match_type, 'exact')}>精确匹配</option><option value="contains" ${selected(d.match_type, 'contains')}>包含匹配</option><option value="prefix" ${selected(d.match_type, 'prefix')}>前缀匹配</option><option value="regex" ${selected(d.match_type, 'regex')}>正则表达式</option></select></div>
      <div class="field switches"><label class="check"><input id="case_sensitive" type="checkbox" ${d.case_sensitive ? 'checked' : ''}> 大小写敏感</label><label class="check"><input id="enabled" type="checkbox" ${d.enabled ? 'checked' : ''}> 启用回复</label></div>
    </div></section>
    <section class="panel"><h3>回复内容</h3><div class="form-grid">
      <div class="field"><label for="reply_type">回复类型</label><select id="reply_type"><option value="text" ${selected(d.reply_type, 'text')}>固定文本</option><option value="random" ${selected(d.reply_type, 'random')}>随机文本</option><option value="composite" ${selected(d.reply_type, 'composite')}>多段文本</option><option value="media" ${selected(d.reply_type, 'media')}>多媒体消息链</option></select></div>
      ${editor}
      <div class="field full"><div class="variables"><strong>动态变量</strong><span>${esc(variables)}</span></div></div>
    </div></section>
    <section class="panel"><h3>作用域与优先级</h3><div class="form-grid">
      <div class="field"><label for="priority">回复优先级</label><input id="priority" type="number" value="${esc(d.priority)}" min="-100000" max="100000"><span class="hint">数值越大越优先；相同优先级按匹配方式和关键词长度稳定排序。</span></div>
      <div class="field"><label for="scope_mode">作用域模式</label><select id="scope_mode"><option value="blacklist" ${d.scope?.mode !== 'whitelist' ? 'selected' : ''}>黑名单（默认）</option><option value="whitelist" ${d.scope?.mode === 'whitelist' ? 'selected' : ''}>白名单</option></select></div>
      <div class="field"><label for="scope_groups">群号</label><input id="scope_groups" value="${esc((d.scope?.group_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div>
      <div class="field"><label for="scope_users">用户 ID</label><input id="scope_users" value="${esc((d.scope?.user_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div>
    </div></section>
    <section class="panel"><h3>冷却与限制</h3><div class="form-grid three">
      <div class="field"><label for="rule_seconds">回复冷却（秒）</label><input id="rule_seconds" type="number" min="0" value="${esc(d.cooldown?.rule_seconds || 0)}"></div>
      <div class="field"><label for="user_seconds">用户冷却（秒）</label><input id="user_seconds" type="number" min="0" value="${esc(d.cooldown?.user_seconds || 0)}"></div>
      <div class="field"><label for="group_seconds">群聊冷却（秒）</label><input id="group_seconds" type="number" min="0" value="${esc(d.cooldown?.group_seconds || 0)}"></div>
      <div class="field"><label for="daily_limit">每日触发上限</label><input id="daily_limit" type="number" min="0" value="${esc(d.daily_limit || 0)}"><span class="hint">0 表示不限制。</span></div>
      <div class="field wide"><label for="time_start">允许时间段</label><div class="time-range"><input id="time_start" type="time" value="${esc(d.time_range?.start || '')}" aria-label="开始时间"><span>至</span><input id="time_end" type="time" value="${esc(d.time_range?.end || '')}" aria-label="结束时间"></div><span class="hint">留空表示全天；支持跨午夜时间段。</span></div>
    </div></section>
    <section class="panel"><h3>回复测试</h3><div class="toolbar"><input id="test_message" class="grow" placeholder="输入模拟消息，例如：菜单" aria-label="模拟消息"><input id="test_sender" placeholder="发送者 ID" aria-label="发送者 ID"><input id="test_group" placeholder="群号" aria-label="群号"><button type="button" class="btn tonal" data-action="test">预览匹配</button></div><pre id="test_result" class="code"></pre></section>
    <div class="form-actions"><button type="button" class="btn text" data-nav="rules">取消</button>${d.id ? '<button type="button" class="btn text danger" data-action="delete-current">删除回复</button>' : ''}<button type="button" class="btn primary" data-action="save">保存回复</button></div>
  </div>`, d.id ? '编辑回复' : '创建回复', d.id ? '修改现有回复并立即生效。' : '通过表单创建一条可触发的自定义回复。');
}

function transferView() {
  return shell(`<section class="grid two">
    <div class="panel"><h3>导出回复</h3><p>导出全部回复、文件夹和全局设置为 JSON 文件，不包含运行中的临时缓存。</p><button type="button" class="btn primary" data-action="export">下载 JSON</button></div>
    <div class="panel"><h3>导入回复</h3><p>导入会替换当前回复和文件夹，并覆盖文件中的全局设置（WebUI 管理员列表除外）；执行前会在浏览器中二次确认。请保留导出文件备份。</p><div class="dropzone"><label for="import-file" class="btn tonal">选择 JSON 文件</label><input id="import-file" type="file" accept="application/json,.json"><p id="import-name" class="hint">尚未选择文件</p></div></div>
  </section>`, '导入 / 导出', '备份回复、文件夹和设置，或在不同 AstrBot 实例间同步。');
}

function statsView() {
  const rows = state.stats.length
    ? state.stats.map(row => `<tr><td>${esc(row.name)}</td><td><strong>${esc(row.trigger_count)}</strong></td><td>${esc(row.last_trigger_at || '尚未触发')}</td><td><span class="badge ${row.enabled ? 'good' : 'off'}">${row.enabled ? '启用' : '停用'}</span></td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">暂无统计数据。</td></tr>';
  return shell(`<div class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>回复</th><th>累计触发</th><th>最近触发</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div></div>`, '触发统计', '统计写入插件数据目录，重载后仍会保留。');
}

function settingsView() {
  const settings = state.settings || {};
  return shell(`<div class="stack">
    <section class="panel"><h3>触发范围</h3><div class="form-grid">
      <div class="field full"><label class="check"><input id="require_wake" type="checkbox" ${settings.require_wake ? 'checked' : ''}> 仅响应 @机器人或唤醒命令（默认）</label><span class="hint">关闭后，所有普通消息都会参与匹配，请谨慎使用。</span></div>
      <div class="field"><label for="global_scope_mode">全局作用域模式</label><select id="global_scope_mode"><option value="blacklist" ${settings.scope_mode !== 'whitelist' ? 'selected' : ''}>黑名单（默认）</option><option value="whitelist" ${settings.scope_mode === 'whitelist' ? 'selected' : ''}>白名单</option></select></div>
      <div class="field"><label for="global_groups">全局群号</label><input id="global_groups" value="${esc((settings.group_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div>
      <div class="field"><label for="global_users">全局用户 ID</label><input id="global_users" value="${esc((settings.user_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div>
    </div></section>
    <section class="panel"><h3>管理权限</h3><div class="form-grid">
      <div class="field full"><label for="webui_admins">WebUI 管理员账号（可选）</label><input id="webui_admins" value="${esc((settings.webui_admins || []).join(', '))}" placeholder="留空表示所有已登录管理面板账号"><span class="hint">AstrBot 管理面板 JWT 已先完成认证；填写后再按用户名限制，且必须包含当前登录账号。</span></div>
    </div></section>
    <div class="form-actions"><button type="button" class="btn primary" data-action="save-settings">保存全局设置</button></div>
  </div>`, '全局设置', '控制唤醒范围和默认黑白名单。');
}

function render() {
  if (state.loading) { app.innerHTML = '<div class="content"><div class="panel empty">正在连接自定义回复插件…</div></div>'; return; }
  const views = { overview: overviewView, rules: rulesView, create: formView, transfer: transferView, stats: statsView, settings: settingsView };
  app.innerHTML = views[state.tab]() + folderDialogView() + confirmDialogView();
  bind();
}

function readForm() {
  const draft = state.draft || draftDefaults();
  draft.name = document.getElementById('name').value.trim();
  draft.folder_id = document.getElementById('folder_id').value;
  draft.keywords = document.getElementById('keywords').value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  draft.match_type = document.getElementById('match_type').value;
  draft.reply_type = document.getElementById('reply_type').value;
  draft.case_sensitive = document.getElementById('case_sensitive').checked;
  draft.enabled = document.getElementById('enabled').checked;
  draft.priority = Number(document.getElementById('priority').value || 0);
  draft.scope = { mode: document.getElementById('scope_mode').value, group_ids: document.getElementById('scope_groups').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean), user_ids: document.getElementById('scope_users').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean) };
  draft.cooldown = { rule_seconds: Number(document.getElementById('rule_seconds').value || 0), user_seconds: Number(document.getElementById('user_seconds').value || 0), group_seconds: Number(document.getElementById('group_seconds').value || 0) };
  draft.daily_limit = Number(document.getElementById('daily_limit').value || 0);
  draft.time_range = { start: document.getElementById('time_start').value, end: document.getElementById('time_end').value };
  // Only the editor for the previously rendered reply type exists in the DOM.
  const randomInput = document.getElementById('random_replies');
  const contentInput = document.getElementById('content');
  if (randomInput) draft.random_replies = randomInput.value.split(/\r?\n/).filter(Boolean);
  if (contentInput) draft.content = contentInput.value;
  if (document.getElementById('components')) draft.components = [...document.querySelectorAll('.component-row')].map(row => ({ type: row.querySelector('[data-comp="type"]').value, value: row.querySelector('[data-comp="value"]').value.trim(), name: row.querySelector('[data-comp="name"]').value.trim() }));
  return draft;
}

async function load() {
  state.loading = true; state.error = ''; render();
  try {
    const [overview, settings, folders] = await Promise.all([apiGet('overview'), apiGet('settings'), apiGet('folders')]);
    state.overview = overview; state.settings = settings; state.folders = folders.rows || [];
    await loadRules(); state.stats = (await apiGet('stats')).rows || [];
  } catch (error) { state.error = error.message || String(error); }
  state.loading = false; render();
}

async function loadFolders() {
  state.folders = (await apiGet('folders')).rows || [];
}

async function fetchRules() {
  return apiGet('rules', { ...state.filters, page: state.page, page_size: state.pageSize });
}

async function loadRules() {
  let result = await fetchRules();
  const lastPage = Math.max(1, Math.ceil((result.total || 0) / state.pageSize));
  if (state.page > lastPage) { state.page = lastPage; result = await fetchRules(); }
  state.rules = result.rows || []; state.total = result.total || 0;
}

function readFilters() {
  return { search: document.getElementById('search').value.trim(), match_type: document.getElementById('match_type').value, enabled: document.getElementById('enabled').value, group_id: document.getElementById('group_id').value.trim(), folder_id: document.getElementById('folder_filter').value };
}

async function applyFilters() {
  state.filters = readFilters(); state.page = 1; await loadRules(); render();
}

async function switchTab(tab) {
  state.tab = tab;
  // Edit and copy open their draft directly, so navigating here always means a new reply.
  state.draft = tab === 'create' ? draftDefaults() : null;
  if (tab === 'overview') state.overview = await apiGet('overview');
  if (tab === 'rules') { state.page = 1; await loadRules(); }
  if (tab === 'stats') state.stats = (await apiGet('stats')).rows || [];
  render();
}

async function saveReply() {
  const reply = readForm();
  try { await apiPost('rules/save', reply); state.draft = null; state.tab = 'rules'; await loadRules(); state.overview = await apiGet('overview'); render(); notify('回复已保存。'); }
  catch (error) { notify(error.message || String(error), true); }
}

async function testReply() {
  const message = document.getElementById('test_message').value.trim();
  if (!message) { notify('请输入模拟消息。', true); return; }
  const context = { sender: document.getElementById('test_sender').value.trim(), group_id: document.getElementById('test_group').value.trim() };
  try { const result = await apiPost('test', { message, context }); document.getElementById('test_result').textContent = json(result); }
  catch (error) { notify(error.message || String(error), true); }
}

function openFolderDialog(existing = null) {
  state.folderDialog = { mode: 'edit', id: existing?.id || '', name: existing?.name || '', description: existing?.description || '', error: '' };
  render();
  requestAnimationFrame(() => document.getElementById('folder_name')?.focus());
}

function openDeleteFolderDialog(folder) {
  if (!folder) return;
  state.folderDialog = { mode: 'delete', id: folder.id, name: folder.name, description: '' };
  render();
}

async function submitFolder() {
  const dialog = state.folderDialog;
  if (!dialog) return;
  if (dialog.mode === 'delete') {
    try { await apiPost('folders/delete', { id: dialog.id, confirm: true }); state.folderDialog = null; state.filters.folder_id = ''; await loadFolders(); await loadRules(); state.overview = await apiGet('overview'); render(); notify('文件夹已删除，回复已移到未分类。'); }
    catch (error) { state.folderDialog = null; render(); notify(error.message || String(error), true); }
    return;
  }
  const name = document.getElementById('folder_name')?.value.trim() || '';
  const description = document.getElementById('folder_description')?.value.trim() || '';
  dialog.name = name; dialog.description = description;
  if (!name) { dialog.error = '文件夹名称不能为空。'; render(); return; }
  try { await apiPost('folders/save', { id: dialog.id, name, description }); state.folderDialog = null; await loadFolders(); await loadRules(); state.overview = await apiGet('overview'); render(); notify('文件夹已保存。'); }
  catch (error) { dialog.error = error.message || String(error); render(); }
}

function openConfirmDialog(dialog) {
  state.confirmDialog = dialog;
  render();
}

async function submitConfirm() {
  const dialog = state.confirmDialog;
  if (!dialog) return;
  try {
    if (dialog.kind === 'delete-reply') {
      await apiPost('rules/delete', { id: dialog.id, confirm: true });
      state.confirmDialog = null; state.draft = null; state.tab = 'rules'; await loadRules(); render(); notify('回复已删除。');
      return;
    }
    if (dialog.kind === 'import') {
      const result = await apiPost('import', state.pendingImport?.payload || {});
      state.confirmDialog = null; state.pendingImport = null; notify(`已导入 ${result.imported} 条回复。`); await load();
    }
  } catch (error) { state.confirmDialog = null; state.pendingImport = null; render(); notify(error.message || String(error), true); }
}

async function deleteFolder() {
  const folder = state.folders.find(item => item.id === state.filters.folder_id);
  openDeleteFolderDialog(folder);
}

async function action(event) {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const act = button.dataset.action;
  try {
    if (act === 'refresh') { if (state.tab === 'create') state.draft = readForm(); await load(); return; }
    if (act === 'apply-filter') { await applyFilters(); return; }
    if (act === 'prev') { state.page--; await loadRules(); render(); return; }
    if (act === 'next') { state.page++; await loadRules(); render(); return; }
    if (act === 'new-folder') { openFolderDialog(); return; }
    if (act === 'edit-folder') { openFolderDialog(state.folders.find(item => item.id === state.filters.folder_id)); return; }
    if (act === 'delete-folder') { await deleteFolder(); return; }
    if (act === 'folder-cancel') { state.folderDialog = null; render(); return; }
    if (act === 'folder-submit') { await submitFolder(); return; }
    if (act === 'confirm-cancel') { state.confirmDialog = null; state.pendingImport = null; render(); return; }
    if (act === 'confirm-submit') { await submitConfirm(); return; }
    if (act === 'edit') { state.draft = await apiGet(`rules/${encodeURIComponent(button.dataset.id)}`); state.tab = 'create'; render(); return; }
    if (act === 'toggle') { const row = state.rules.find(item => item.id === button.dataset.id); await apiPost('rules/toggle', { id: button.dataset.id, enabled: !row.enabled }); await loadRules(); render(); return; }
    if (act === 'copy') { const result = await apiPost('rules/duplicate', { id: button.dataset.id }); state.draft = result.rule; state.tab = 'create'; render(); return; }
    if (act === 'delete' || act === 'delete-current') { if (act === 'delete-current') state.draft = readForm(); const id = button.dataset.id || state.draft?.id; if (!id) return; openConfirmDialog({ kind: 'delete-reply', id, title: '删除回复', message: '删除后不可恢复，确定继续吗？', confirmLabel: '删除回复' }); return; }
    if (act === 'save') { await saveReply(); return; }
    if (act === 'test') { await testReply(); return; }
    if (act === 'add-component') { state.draft = readForm(); state.draft.components.push({ type: 'image', value: '', name: '' }); render(); return; }
    if (act === 'remove-component') { state.draft = readForm(); state.draft.components.splice(Number(button.dataset.index), 1); render(); return; }
    if (act === 'export') { const data = await apiGet('export'); const blob = new Blob([json(data)], { type: 'application/json' }); const link = document.createElement('a'); const objectUrl = URL.createObjectURL(blob); link.href = objectUrl; link.download = 'custom-replies.json'; link.style.display = 'none'; document.body.appendChild(link); link.click(); setTimeout(() => { URL.revokeObjectURL(objectUrl); link.remove(); }, 0); notify('回复和文件夹已导出。'); return; }
    if (act === 'save-settings') { const settings = { require_wake: document.getElementById('require_wake').checked, scope_mode: document.getElementById('global_scope_mode').value, group_ids: document.getElementById('global_groups').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean), user_ids: document.getElementById('global_users').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean), webui_admins: document.getElementById('webui_admins').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean) }; state.settings = (await apiPost('settings/save', settings)).settings; state.overview = await apiGet('overview'); render(); notify('全局设置已保存。'); }
  } catch (error) { notify(error.message || String(error), true); }
}

function bind() {
  document.querySelectorAll('[data-nav]').forEach(button => button.addEventListener('click', async () => {
    try { await switchTab(button.dataset.nav); }
    catch (error) { notify(error.message || String(error), true); }
  }));
  app.onclick = action;
  const folderForm = document.getElementById('folder-form');
  if (folderForm) folderForm.addEventListener('submit', event => { event.preventDefault(); submitFolder(); });
  const backdrop = document.querySelector('[data-folder-dialog-backdrop]');
  if (backdrop) backdrop.addEventListener('click', event => { if (event.target === backdrop) { state.folderDialog = null; render(); } });
  const confirmBackdrop = document.querySelector('[data-confirm-dialog-backdrop]');
  if (confirmBackdrop) confirmBackdrop.addEventListener('click', event => { if (event.target === confirmBackdrop) { state.confirmDialog = null; state.pendingImport = null; render(); } });
  document.querySelectorAll('[data-folder-rule]').forEach(select => select.addEventListener('change', async event => { try { await apiPost('rules/move', { id: event.target.dataset.folderRule, folder_id: event.target.value }); await loadRules(); render(); notify(event.target.value ? '回复已移入文件夹。' : '回复已移出文件夹。'); } catch (error) { notify(error.message || String(error), true); } }));
  const folderFilter = document.getElementById('folder_filter');
  if (folderFilter) folderFilter.addEventListener('change', async () => { try { await applyFilters(); } catch (error) { notify(error.message || String(error), true); } });
  const input = document.getElementById('import-file');
  if (input) input.addEventListener('change', async () => { const file = input.files[0]; if (!file) return; document.getElementById('import-name').textContent = file.name; try { const payload = JSON.parse(await file.text()); state.pendingImport = { name: file.name, payload }; openConfirmDialog({ kind: 'import', title: '导入回复', message: '导入会替换当前回复和文件夹，并覆盖文件中的全局设置（WebUI 管理员列表除外），确定继续吗？', confirmLabel: '确认导入' }); } catch (error) { notify(`导入文件不是有效 JSON：${error.message || String(error)}`, true); } });
  const type = document.getElementById('reply_type');
  if (type) type.addEventListener('change', () => { state.draft = readForm(); state.draft.reply_type = type.value; render(); });
}

(async () => {
  if (!bridge) { state.loading = false; state.error = '请从 AstrBot 插件详情页打开自定义回复插件。'; render(); return; }
  try { const context = await bridge.ready(); document.documentElement.dataset.theme = context?.isDark ? 'dark' : 'light'; bridge.onContext?.(value => { document.documentElement.dataset.theme = value?.isDark ? 'dark' : 'light'; }); await load(); }
  catch (error) { state.loading = false; state.error = error.message || String(error); render(); }
})();
