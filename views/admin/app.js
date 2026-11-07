const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const app = document.getElementById('app');
const state = {
  tab: 'overview', overview: null, rules: [], total: 0, page: 1, pageSize: 12,
  folders: [],
  filters: { search: '', match_type: '', enabled: '', group_id: '', folder_id: '' },
  stats: [], settings: null, draft: null, folderDialog: null, notice: '', error: '', loading: true,
};

const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[ch]));
const json = value => JSON.stringify(value, null, 2);
const apiGet = (endpoint, params = {}) => bridge.apiGet(endpoint, params);
const apiPost = (endpoint, body = {}) => bridge.apiPost(endpoint, body);

function notify(message, error = false) {
  state.notice = error ? '' : message;
  state.error = error ? message : '';
  render();
  setTimeout(() => { state.notice = ''; state.error = ''; render(); }, 4500);
}

function nav() {
  return [['overview', '总览'], ['rules', '回复列表'], ['create', '创建回复'],
    ['transfer', '导入 / 导出'], ['stats', '触发统计'], ['settings', '全局设置']];
}

function shell(body, title, subtitle = '') {
  return `<div class="layout"><aside class="sidebar"><div class="brand"><small>REPLY · ADMIN</small><h1>自定义回复插件</h1><p>关键词回复与消息链</p></div><nav class="nav" aria-label="管理页面">${nav().map(([id, label]) => `<button class="${state.tab === id ? 'active' : ''}" data-nav="${id}">${label}</button>`).join('')}</nav><div class="sidebar-foot">版本 v1.0.0<br>只通过 AstrBot WebUI 管理</div></aside><main class="content"><div class="topbar"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div><div class="actions"><button class="btn" data-action="refresh">刷新</button></div></div>${state.error ? `<div class="notice error" role="alert">${esc(state.error)}</div>` : ''}${state.notice ? `<div class="notice success" role="status">${esc(state.notice)}</div>` : ''}${body}</main></div>`;
}

function metric(label, value, detail) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></div>`;
}

function folderOptions(selected = '', includeAll = false) {
  const options = includeAll ? '<option value="">全部回复</option><option value="__none__">未分类回复</option>' : '<option value="">未分类</option>';
  return options + state.folders.map(folder => `<option value="${esc(folder.id)}" ${selected === folder.id ? 'selected' : ''}>${esc(folder.name)}</option>`).join('');
}

function overviewView() {
  const overview = state.overview || { total: 0, enabled: 0, disabled: 0, top_rules: [], folder_total: 0 };
  const top = overview.top_rules || [];
  return shell(`<section class="grid metrics">${metric('回复总数', overview.total, '全部自定义回复')}${metric('已启用', overview.enabled, '当前可触发')}${metric('已禁用', overview.disabled, '暂不参与匹配')}${metric('文件夹', overview.folder_total || state.folders.length, '分类数量')}</section><section class="grid two" style="margin-top:16px"><div class="panel"><h3>最常触发回复</h3>${top.length ? `<div class="list-card">${top.map(row => `<div class="row"><div><h4>${esc(row.name)}</h4><p>${esc(row.trigger_count)} 次触发</p></div><span class="badge good">统计已持久化</span></div>`).join('')}</div>` : '<div class="empty">还没有触发统计。</div>'}</div><div class="panel"><h3>运行提示</h3><p>回复、统计、冷却和全局设置都保存在插件数据目录中，并使用原子写入。导入 / 导出页面可以备份或恢复当前回复及文件夹。</p><span class="badge ${state.settings?.require_wake ? 'good' : ''}">${state.settings?.require_wake ? '保留唤醒触发' : '已允许普通消息触发'}</span></div></section>`, '总览', '查看回复数量、文件夹和触发概况。');
}

function folderToolbar() {
  const selectedFolder = state.filters.folder_id && state.filters.folder_id !== '__none__' ? state.filters.folder_id : '';
  return `<div class="folder-toolbar"><select id="folder_filter" aria-label="文件夹筛选">${folderOptions(state.filters.folder_id, true)}</select><button class="btn" data-action="new-folder">＋ 新建文件夹</button><button class="btn" data-action="edit-folder" ${selectedFolder ? '' : 'disabled'}>编辑文件夹</button><button class="btn danger" data-action="delete-folder" ${selectedFolder ? '' : 'disabled'}>删除文件夹</button></div>`;
}

function folderDialogView() {
  const dialog = state.folderDialog;
  if (!dialog) return '';
  if (dialog.mode === 'delete') {
    return `<div class="modal-backdrop" data-folder-dialog-backdrop><section class="modal" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title"><div class="modal-head"><div><h3 id="folder-dialog-title">删除文件夹</h3><p>文件夹中的回复会保留，并移动到未分类。</p></div><button class="modal-close" type="button" data-action="folder-cancel" aria-label="关闭">×</button></div><div class="modal-warning">确定删除“${esc(dialog.name)}”吗？</div><div class="modal-actions"><button class="btn" type="button" data-action="folder-cancel">取消</button><button class="btn danger" type="button" data-action="folder-submit">删除文件夹</button></div></section></div>`;
  }
  return `<div class="modal-backdrop" data-folder-dialog-backdrop><section class="modal" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title"><div class="modal-head"><div><h3 id="folder-dialog-title">${dialog.id ? '编辑文件夹' : '新建文件夹'}</h3><p>用文件夹整理自定义回复，之后仍可随时移动。</p></div><button class="modal-close" type="button" data-action="folder-cancel" aria-label="关闭">×</button></div><form id="folder-form"><div class="field"><label for="folder_name">文件夹名称</label><input id="folder_name" name="name" maxlength="80" value="${esc(dialog.name)}" placeholder="例如：菜单回复" autofocus></div><div class="field"><label for="folder_description">文件夹说明 <span class="hint">可选</span></label><textarea id="folder_description" name="description" maxlength="300" rows="3" placeholder="例如：常用菜单和帮助回复">${esc(dialog.description)}</textarea></div>${dialog.error ? `<div class="notice error" role="alert">${esc(dialog.error)}</div>` : ''}<div class="modal-actions"><button class="btn" type="button" data-action="folder-cancel">取消</button><button class="btn primary" type="submit">保存文件夹</button></div></form></section></div>`;
}

function rulesView() {
  const rows = state.rules || [];
  return shell(`<div class="panel"><div class="toolbar"><input class="grow" id="search" value="${esc(state.filters.search)}" placeholder="搜索回复名称或关键词"><select id="match_type" aria-label="匹配方式"><option value="">全部匹配方式</option><option value="exact" ${state.filters.match_type === 'exact' ? 'selected' : ''}>精确</option><option value="contains" ${state.filters.match_type === 'contains' ? 'selected' : ''}>包含</option><option value="prefix" ${state.filters.match_type === 'prefix' ? 'selected' : ''}>前缀</option><option value="regex" ${state.filters.match_type === 'regex' ? 'selected' : ''}>正则</option></select><select id="enabled" aria-label="启用状态"><option value="">全部状态</option><option value="true" ${state.filters.enabled === 'true' ? 'selected' : ''}>已启用</option><option value="false" ${state.filters.enabled === 'false' ? 'selected' : ''}>已禁用</option></select><input id="group_id" value="${esc(state.filters.group_id)}" placeholder="群号筛选"><button class="btn primary" data-action="apply-filter">查询</button><button class="btn" data-nav="create">＋ 新建回复</button></div>${folderToolbar()}<div class="table-wrap"><table class="table"><thead><tr><th>回复</th><th>关键词</th><th>匹配</th><th>文件夹</th><th>作用域</th><th>优先级</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.length ? rows.map(row => `<tr><td><strong>${esc(row.name)}</strong><br><span class="muted code">${esc(row.id)}</span></td><td>${esc((row.keywords || []).join('、'))}</td><td>${esc(row.match_type)} / ${row.case_sensitive ? '敏感' : '不敏感'}</td><td><select class="folder-select" data-folder-rule="${esc(row.id)}" aria-label="为回复选择文件夹">${folderOptions(row.folder_id || '')}</select></td><td>${esc(row.scope?.mode === 'whitelist' ? '白名单' : '黑名单')}<br><span class="muted">${esc((row.scope?.group_ids || []).length)} 群 / ${esc((row.scope?.user_ids || []).length)} 用户</span></td><td>${esc(row.priority)}</td><td><span class="badge ${row.enabled ? 'good' : 'off'}">${row.enabled ? '启用' : '停用'}</span></td><td><div class="row-actions"><button data-action="edit" data-id="${esc(row.id)}">编辑</button><button data-action="toggle" data-id="${esc(row.id)}">${row.enabled ? '禁用' : '启用'}</button><button data-action="copy" data-id="${esc(row.id)}">复制</button><button class="danger-text" data-action="delete" data-id="${esc(row.id)}">删除</button></div></td></tr>`).join('') : '<tr><td colspan="8" class="empty">没有匹配的回复。</td></tr>'}</tbody></table></div><div class="pagination"><span>共 ${state.total} 条，第 ${state.page} / ${Math.max(1, Math.ceil(state.total / state.pageSize))} 页</span><button class="btn" data-action="prev" ${state.page <= 1 ? 'disabled' : ''}>上一页</button><button class="btn" data-action="next" ${state.page >= Math.ceil(state.total / state.pageSize) ? 'disabled' : ''}>下一页</button></div></div>`, '回复列表', '搜索、筛选、分页管理全部自定义回复。');
}

function draftDefaults() {
  return { id: '', name: '', folder_id: '', keywords: [], match_type: 'exact', case_sensitive: false, reply_type: 'text', content: '', random_replies: [], components: [], scope: { mode: 'blacklist', group_ids: [], user_ids: [] }, priority: 0, enabled: true, cooldown: { rule_seconds: 0, user_seconds: 0, group_seconds: 0 }, daily_limit: 0, time_range: { start: '', end: '' } };
}

function formView() {
  const d = state.draft || draftDefaults();
  const components = d.components || [];
  const reply = d.reply_type === 'random' ? `<div class="field full"><span>随机回复内容 <span class="hint">每行一条，发送时随机抽取</span></span><textarea id="random_replies" rows="6">${esc((d.random_replies || []).join('\n'))}</textarea></div>` : d.reply_type === 'media' ? `<div class="field full"><span>多媒体消息组件</span><div id="components">${components.map((item, index) => `<div class="component-row" data-index="${index}"><select data-comp="type"><option value="image" ${item.type === 'image' ? 'selected' : ''}>图片</option><option value="video" ${item.type === 'video' ? 'selected' : ''}>视频</option><option value="record" ${['record', 'voice'].includes(item.type) ? 'selected' : ''}>语音</option><option value="file" ${item.type === 'file' ? 'selected' : ''}>文件</option><option value="at" ${item.type === 'at' ? 'selected' : ''}>At</option></select><input data-comp="value" value="${esc(item.value || item.url || item.file || '')}" placeholder="URL、文件路径或用户 ID"><input data-comp="name" value="${esc(item.name || '')}" placeholder="显示名（可选）"><button class="btn danger remove-component" data-action="remove-component" data-index="${index}">移除</button></div>`).join('')}</div><button class="btn" data-action="add-component">＋ 添加组件</button><p class="hint">媒体资源使用 AstrBot 原生消息链发送；路径或 URL 在触发时由平台适配器处理。</p></div>` : `<div class="field full"><span>回复内容</span><textarea id="content" rows="${d.reply_type === 'composite' ? 8 : 5}" placeholder="支持动态变量，例如：你好，{nickname}！">${esc(d.content)}</textarea><p class="hint">${d.reply_type === 'composite' ? '每行一段文本，按顺序组合发送。' : '支持 {sender} {nickname} {group_id} {group_name} {time} {date} {random}。'}</p></div>`;
  return shell(`<div class="panel"><div class="form-grid"><div class="field"><span>回复名称</span><input id="name" value="${esc(d.name)}" placeholder="例如：菜单帮助"></div><div class="field"><span>文件夹</span><select id="folder_id">${folderOptions(d.folder_id || '')}</select><span class="hint">可以在回复列表中随时移动或移出文件夹。</span></div><div class="field"><span>关键词 <span class="hint">每行一个，可绑定多个</span></span><textarea id="keywords" rows="3" placeholder="菜单\\n帮助">${esc((d.keywords || []).join('\n'))}</textarea></div><div class="field"><span>匹配方式</span><select id="match_type"><option value="exact" ${d.match_type === 'exact' ? 'selected' : ''}>精确匹配</option><option value="contains" ${d.match_type === 'contains' ? 'selected' : ''}>包含匹配</option><option value="prefix" ${d.match_type === 'prefix' ? 'selected' : ''}>前缀匹配</option><option value="regex" ${d.match_type === 'regex' ? 'selected' : ''}>正则表达式</option></select></div><div class="field"><span>回复类型</span><select id="reply_type"><option value="text" ${d.reply_type === 'text' ? 'selected' : ''}>固定文本</option><option value="random" ${d.reply_type === 'random' ? 'selected' : ''}>随机文本</option><option value="composite" ${d.reply_type === 'composite' ? 'selected' : ''}>多段文本</option><option value="media" ${d.reply_type === 'media' ? 'selected' : ''}>多媒体消息链</option></select></div><div class="field"><span>大小写</span><label class="check"><input id="case_sensitive" type="checkbox" ${d.case_sensitive ? 'checked' : ''}> 大小写敏感</label></div><div class="field"><span>状态</span><label class="check"><input id="enabled" type="checkbox" ${d.enabled ? 'checked' : ''}> 启用回复</label></div>${reply}<div class="field"><span>回复优先级</span><input id="priority" type="number" value="${esc(d.priority)}" min="-100000" max="100000"><span class="hint">数值越大越优先；相同优先级按匹配方式和关键词长度稳定排序。</span></div><div class="field"><span>作用域模式</span><select id="scope_mode"><option value="blacklist" ${d.scope?.mode !== 'whitelist' ? 'selected' : ''}>黑名单（默认）</option><option value="whitelist" ${d.scope?.mode === 'whitelist' ? 'selected' : ''}>白名单</option></select></div><div class="field"><span>群号</span><input id="scope_groups" value="${esc((d.scope?.group_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div><div class="field"><span>用户 ID</span><input id="scope_users" value="${esc((d.scope?.user_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div><div class="field"><span>回复冷却（秒）</span><input id="rule_seconds" type="number" min="0" value="${esc(d.cooldown?.rule_seconds || 0)}"></div><div class="field"><span>用户冷却（秒）</span><input id="user_seconds" type="number" min="0" value="${esc(d.cooldown?.user_seconds || 0)}"></div><div class="field"><span>群聊冷却（秒）</span><input id="group_seconds" type="number" min="0" value="${esc(d.cooldown?.group_seconds || 0)}"></div><div class="field"><span>每日触发上限</span><input id="daily_limit" type="number" min="0" value="${esc(d.daily_limit || 0)}"><span class="hint">0 表示不限制。</span></div><div class="field"><span>允许时间段</span><div class="choice-row"><input id="time_start" type="time" value="${esc(d.time_range?.start || '')}\"><input id="time_end" type="time" value="${esc(d.time_range?.end || '')}"></div><span class="hint">留空表示全天；支持跨午夜时间段。</span></div><div class="field full"><div class="panel" style="background:var(--surface-muted);box-shadow:none"><h4>变量说明</h4><p class="hint">{sender} 发送者 ID　{nickname} 昵称　{group_id} 群号　{group_name} 群名称　{time} 当前时间　{date} 当前日期　{random} 随机数</p></div></div></div><div class="panel" style="margin-top:16px;background:var(--surface-muted);box-shadow:none"><h3>回复测试</h3><div class="toolbar"><input id="test_message" class="grow" placeholder="输入模拟消息，例如：菜单"><input id="test_sender" placeholder="发送者 ID"><input id="test_group" placeholder="群号"><button class="btn" data-action="test">预览匹配</button></div><pre id="test_result" class="code"></pre></div><div class="form-actions"><button class="btn" data-nav="rules">取消</button>${d.id ? '<button class="btn danger" data-action="delete-current">删除回复</button>' : ''}<button class="btn primary" data-action="save">保存回复</button></div></div>`, d.id ? '编辑回复' : '创建回复', d.id ? '修改现有回复并立即更新缓存。' : '通过表单创建一条可触发的自定义回复。');
}

function transferView() {
  return shell(`<section class="grid two"><div class="panel"><h3>导出回复</h3><p>导出全部回复、文件夹和全局设置为 JSON 文件，不包含运行中的临时缓存。</p><button class="btn primary" data-action="export">下载 JSON</button></div><div class="panel"><h3>导入回复</h3><p>导入会替换当前回复和文件夹；执行前会在浏览器中二次确认。请保留导出文件备份。</p><div class="dropzone"><label for="import-file">选择 JSON 文件</label><input id="import-file" type="file" accept="application/json,.json"><p id="import-name" class="hint">尚未选择文件</p></div></div></section>`, '导入 / 导出', '备份回复、文件夹和设置，或在不同 AstrBot 实例间同步。');
}

function statsView() {
  return shell(`<div class="panel"><h3>回复触发统计</h3><div class="table-wrap"><table class="table"><thead><tr><th>回复</th><th>累计触发</th><th>最近触发</th><th>状态</th></tr></thead><tbody>${state.stats.length ? state.stats.map(row => `<tr><td>${esc(row.name)}</td><td><strong>${esc(row.trigger_count)}</strong></td><td>${esc(row.last_trigger_at || '尚未触发')}</td><td><span class="badge ${row.enabled ? 'good' : 'off'}">${row.enabled ? '启用' : '停用'}</span></td></tr>`).join('') : '<tr><td colspan="4" class="empty">暂无统计数据。</td></tr>'}</tbody></table></div></div>`, '触发统计', '统计写入插件数据目录，重载后仍会保留。');
}

function settingsView() {
  const settings = state.settings || {};
  return shell(`<div class="panel"><div class="form-grid"><div class="field full"><label class="check"><input id="require_wake" type="checkbox" ${settings.require_wake ? 'checked' : ''}> 仅响应 @机器人或唤醒命令（默认）</label><span class="hint">关闭后，所有普通消息都会参与匹配，请谨慎使用。</span></div><div class="field"><span>全局作用域模式</span><select id="global_scope_mode"><option value="blacklist" ${settings.scope_mode !== 'whitelist' ? 'selected' : ''}>黑名单（默认）</option><option value="whitelist" ${settings.scope_mode === 'whitelist' ? 'selected' : ''}>白名单</option></select></div><div class="field"><span>全局群号</span><input id="global_groups" value="${esc((settings.group_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div><div class="field"><span>全局用户 ID</span><input id="global_users" value="${esc((settings.user_ids || []).join(', '))}" placeholder="多个 ID 用逗号分隔"></div><div class="field"><span>WebUI 管理员账号（可选）</span><input id="webui_admins" value="${esc((settings.webui_admins || []).join(', '))}" placeholder="留空表示所有已登录管理面板账号"><span class="hint">AstrBot 管理面板 JWT 已先完成认证；填写后再按用户名限制。</span></div></div><div class="form-actions"><button class="btn primary" data-action="save-settings">保存全局设置</button></div></div>`, '全局设置', '控制唤醒范围和默认黑白名单。');
}

function render() {
  if (state.loading) { app.innerHTML = '<div class="content"><div class="panel empty">正在连接自定义回复插件…</div></div>'; return; }
  const views = { overview: overviewView, rules: rulesView, create: formView, transfer: transferView, stats: statsView, settings: settingsView };
  app.innerHTML = views[state.tab]() + folderDialogView();
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
  if (draft.reply_type === 'random') draft.random_replies = document.getElementById('random_replies').value.split(/\r?\n/).filter(Boolean);
  else if (draft.reply_type !== 'media') draft.content = document.getElementById('content').value;
  if (draft.reply_type === 'media') draft.components = [...document.querySelectorAll('.component-row')].map(row => ({ type: row.querySelector('[data-comp="type"]').value, value: row.querySelector('[data-comp="value"]').value.trim(), name: row.querySelector('[data-comp="name"]').value.trim() }));
  return draft;
}

async function load() {
  state.loading = true; render();
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

async function loadRules() {
  const result = await apiGet('rules', { ...state.filters, page: state.page, page_size: state.pageSize });
  state.rules = result.rows || []; state.total = result.total || 0;
}

async function switchTab(tab) {
  state.tab = tab;
  if (tab === 'create' && !state.draft) state.draft = draftDefaults();
  if (tab === 'rules') { state.page = 1; await loadRules(); }
  if (tab === 'stats') state.stats = (await apiGet('stats')).rows || [];
  render();
}

async function saveReply() {
  const reply = readForm();
  try { await apiPost('rules/save', reply); state.draft = null; state.tab = 'rules'; await loadRules(); state.overview = await apiGet('overview'); notify('回复已保存。'); }
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
    catch (error) { notify(error.message || String(error), true); }
    return;
  }
  const name = document.getElementById('folder_name')?.value.trim() || '';
  const description = document.getElementById('folder_description')?.value.trim() || '';
  if (!name) { dialog.error = '文件夹名称不能为空。'; render(); return; }
  try { await apiPost('folders/save', { id: dialog.id, name, description }); state.folderDialog = null; await loadFolders(); await loadRules(); state.overview = await apiGet('overview'); render(); notify('文件夹已保存。'); }
  catch (error) { dialog.error = error.message || String(error); render(); }
}

async function deleteFolder() {
  const folder = state.folders.find(item => item.id === state.filters.folder_id);
  openDeleteFolderDialog(folder);
}

async function action(event) {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const act = button.dataset.action;
  try {
    if (act === 'refresh') { await load(); return; }
    if (act === 'apply-filter') { state.filters = { search: document.getElementById('search').value.trim(), match_type: document.getElementById('match_type').value, enabled: document.getElementById('enabled').value, group_id: document.getElementById('group_id').value.trim(), folder_id: document.getElementById('folder_filter').value }; state.page = 1; await loadRules(); render(); return; }
    if (act === 'prev') { state.page--; await loadRules(); render(); return; }
    if (act === 'next') { state.page++; await loadRules(); render(); return; }
    if (act === 'new-folder') { openFolderDialog(); return; }
    if (act === 'edit-folder') { openFolderDialog(state.folders.find(item => item.id === state.filters.folder_id)); return; }
    if (act === 'delete-folder') { await deleteFolder(); return; }
    if (act === 'folder-cancel') { state.folderDialog = null; render(); return; }
    if (act === 'folder-submit') { await submitFolder(); return; }
    if (act === 'edit') { state.draft = await apiGet(`rules/${encodeURIComponent(button.dataset.id)}`); state.tab = 'create'; render(); return; }
    if (act === 'toggle') { const row = state.rules.find(item => item.id === button.dataset.id); await apiPost('rules/toggle', { id: button.dataset.id, enabled: !row.enabled }); await loadRules(); render(); return; }
    if (act === 'copy') { const result = await apiPost('rules/duplicate', { id: button.dataset.id }); state.draft = result.rule; state.tab = 'create'; render(); return; }
    if (act === 'delete' || act === 'delete-current') { const id = button.dataset.id || state.draft?.id; if (!id || !window.confirm('确定删除这条回复吗？删除后不可恢复。')) return; await apiPost('rules/delete', { id, confirm: true }); state.draft = null; state.tab = 'rules'; await loadRules(); notify('回复已删除。'); return; }
    if (act === 'save') { await saveReply(); return; }
    if (act === 'test') { await testReply(); return; }
    if (act === 'add-component') { state.draft = readForm(); state.draft.components.push({ type: 'image', value: '', name: '' }); render(); return; }
    if (act === 'remove-component') { state.draft = readForm(); state.draft.components.splice(Number(button.dataset.index), 1); render(); return; }
    if (act === 'export') { const data = await apiGet('export'); const blob = new Blob([json(data)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'custom-replies.json'; link.click(); URL.revokeObjectURL(link.href); notify('回复和文件夹已导出。'); return; }
    if (act === 'save-settings') { const settings = { require_wake: document.getElementById('require_wake').checked, scope_mode: document.getElementById('global_scope_mode').value, group_ids: document.getElementById('global_groups').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean), user_ids: document.getElementById('global_users').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean), webui_admins: document.getElementById('webui_admins').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean) }; state.settings = (await apiPost('settings/save', settings)).settings; state.overview = await apiGet('overview'); notify('全局设置已保存。'); }
  } catch (error) { notify(error.message || String(error), true); }
}

function bind() {
  document.querySelectorAll('[data-nav]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.nav)));
  app.onclick = action;
  const folderForm = document.getElementById('folder-form');
  if (folderForm) folderForm.addEventListener('submit', event => { event.preventDefault(); submitFolder(); });
  const backdrop = document.querySelector('[data-folder-dialog-backdrop]');
  if (backdrop) backdrop.addEventListener('click', event => { if (event.target === backdrop) { state.folderDialog = null; render(); } });
  document.querySelectorAll('[data-folder-rule]').forEach(select => select.addEventListener('change', async event => { try { await apiPost('rules/move', { id: event.target.dataset.folderRule, folder_id: event.target.value }); await loadRules(); notify(event.target.value ? '回复已移入文件夹。' : '回复已移出文件夹。'); } catch (error) { notify(error.message || String(error), true); } }));
  const input = document.getElementById('import-file');
  if (input) input.addEventListener('change', async () => { const file = input.files[0]; if (!file) return; document.getElementById('import-name').textContent = file.name; if (!window.confirm('导入会替换当前回复和文件夹，确定继续吗？')) return; try { const payload = JSON.parse(await file.text()); const result = await apiPost('import', payload); notify(`已导入 ${result.imported} 条回复。`); await load(); } catch (error) { notify(error.message || String(error), true); } });
  const type = document.getElementById('reply_type');
  if (type) type.addEventListener('change', () => { state.draft = readForm(); state.draft.reply_type = type.value; render(); });
}

(async () => {
  if (!bridge) { state.loading = false; state.error = '请从 AstrBot 插件详情页打开自定义回复插件。'; render(); return; }
  try { const context = await bridge.ready(); document.documentElement.dataset.theme = context?.isDark ? 'dark' : 'light'; bridge.onContext?.(value => { document.documentElement.dataset.theme = value?.isDark ? 'dark' : 'light'; }); await load(); }
  catch (error) { state.loading = false; state.error = error.message || String(error); render(); }
})();
