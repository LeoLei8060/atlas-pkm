const state = {
  status: null,
  settings: null,
  feed: [],
  collections: [],
  collectionTab: 'rss',
  patches: [],
  usageAccounts: [],
  usageData: [],
  usageLoading: false,
  sources: [],
  sourceCatalog: [],
  sourceCatalogLoaded: false,
  sourceGroup: 'github',
  view: 'dashboard',
  feedTab: 'rss',
  feedSort: 'relevance',
  feedQuery: '',
  feedStatus: '',
  feedSourceId: '',
  feedSelected: new Set(),
  feedOffset: 0,
  feedTotal: 0,
  feedHasMore: false,
  feedPageSize: 50,
  githubMeta: null,
  githubStack: 'cpp',
  githubMetric: 'new_week',
  githubRanking: null,
  githubLoading: false,
  learningMode: 'knowledge_doc',
  learningResult: null,
  profileSuggestions: null,
  addModelKind: 'official',
  settingsTab: 'model',
  scheduleMode: 'daily',
};

const VIEW_META = {
  dashboard: ['概览', '本地知识库与 Agent 的运行状态'],
  feed: ['资讯', 'RSS 资讯与 GitHub 技术栈榜单'],
  collections: ['收藏', '你主动留下的内容'],
  usage: ['用量', '各模型平台的 Token 消耗与余额'],
  wiki: ['LLM Wiki', '从 Markdown Vault 生成的只读视图'],
  learning: ['学习', '生成知识文档、面试题与周期复盘'],
  graph: ['图谱', '笔记之间的链接与标签关系'],
  ask: ['问答', '基于本地资料的带引用回答'],
  patches: ['补丁', 'Agent 对知识库的修改建议'],
  settings: ['设置', '模型、Vault 与采集配置'],
};

const PROVIDER_LABELS = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
  deepseek: 'DeepSeek',
};

const OFFICIAL_PROVIDERS = ['openai', 'anthropic', 'gemini', 'deepseek'];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeUrl(value) {
  const url = String(value || '');
  return /^https?:\/\//i.test(url) ? esc(url) : '#';
}

function fmtDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function fmtDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function fmtCount(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}m`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function inlineMarkdown(value) {
  let out = esc(value);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_, label, url) => `<a href="${safeUrl(url)}" target="_blank" rel="noreferrer">${label}</a>`
  );
  return out;
}

function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  const html = [];
  let list = null;
  let inCode = false;
  let code = [];
  const flushList = () => {
    if (list) {
      html.push(`<ul>${list.join('')}</ul>`);
      list = null;
    }
  };
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
        code = [];
        inCode = false;
      } else {
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    if (!line.trim()) {
      flushList();
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = Math.min(4, heading[1].length + 1);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const item = line.match(/^\s*[-*]\s+(.*)$/);
    if (item) {
      if (!list) list = [];
      list.push(`<li>${inlineMarkdown(item[1])}</li>`);
      continue;
    }
    flushList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  flushList();
  if (inCode) html.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
  return html.join('');
}

function toast(message, kind = '') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add('hidden'), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.detail || `请求失败 (${response.status})`);
  }
  return data;
}

function busy(button, on) {
  if (!button) return;
  if (on) {
    button.dataset.label = button.textContent;
    button.innerHTML = '<span class="spinner"></span>';
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function providerLabel(name, item) {
  const provider = item || state.settings?.providers?.[name] || {};
  return provider.label || PROVIDER_LABELS[name] || name || '未配置';
}

function sourceLabel(type) {
  if (type === 'github') return 'GitHub';
  if (type === 'rss') return 'RSS';
  if (type === 'arxiv') return 'arXiv';
  if (type === 'devto') return 'Dev.to';
  if (type === 'csdn') return 'CSDN';
  if (type === 'qt') return 'Qt Blog';
  if (type === 'author') return '博主';
  if (type === 'html') return '网页';
  return String(type || 'SOURCE').toUpperCase();
}

function emptyState(title, text, actions = '') {
  return `
    <div class="hero">
      <div class="hero-mark">◇</div>
      <h2>${esc(title)}</h2>
      <p>${esc(text)}</p>
      ${actions ? `<div class="hero-actions">${actions}</div>` : ''}
    </div>`;
}

function patchCount() {
  return state.patches.length;
}

function modelStatus() {
  const configured = Boolean(state.status?.ready);
  const active = state.settings?.active_provider || state.status?.active_provider || 'openai';
  const health = state.status?.model_health || {};
  if (!configured) return { state: 'unconfigured', label: '未配置模型', active, health };
  if (health.ok && health.provider === active) {
    return { state: 'ready', label: '模型已就绪', active, health };
  }
  if (health.error) return { state: 'error', label: '模型连接失败', active, health };
  return { state: 'unverified', label: '模型待验证', active, health };
}

function renderSetupBanner() {
  const banner = $('#setupBanner');
  if (!banner) return;
  const status = modelStatus();
  const vault = state.settings?.vault_path || state.status?.vault_path || 'vault';
  if (status.state === 'ready') {
    banner.className = 'setup-banner ready hidden';
    banner.innerHTML = '';
    return;
  }
  banner.classList.remove('hidden');
  banner.className = `setup-banner ${status.state === 'error' ? 'error' : ''}`;
  if (status.state === 'unconfigured') {
    banner.innerHTML = `
      <strong>开始使用</strong>
      <span class="hint">尚未配置模型。资讯抓取、翻译、摘要、匹配度和问答暂时不可用。知识库默认在 <code>${esc(vault)}</code>，首次启动已自动创建。</span>
      <button class="btn primary" data-setup="model">配置模型</button>
      <button class="btn ghost" data-setup="vault">知识库设置</button>`;
  } else if (status.state === 'error') {
    banner.innerHTML = `
      <strong>模型不可用</strong>
      <span class="hint">${esc(status.health.error || '连接测试失败')}</span>
      <button class="btn primary" data-setup="model">检查模型设置</button>
      <button class="btn ghost" data-setup="test">重新测试</button>`;
  } else {
    banner.innerHTML = `
      <strong>模型待验证</strong>
      <span class="hint">已保存 ${esc(providerLabel(status.active))} 配置，但还没有测试连接。建议先验证，避免抓取和问答时才报错。</span>
      <button class="btn primary" data-setup="test">测试连接</button>
      <button class="btn ghost" data-setup="model">检查设置</button>`;
  }
}

async function testActiveProvider() {
  const active = state.settings?.active_provider || state.status?.active_provider || 'deepseek';
  try {
    const result = await api('/api/providers/test', {
      method: 'POST',
      body: JSON.stringify({ provider: active }),
    });
    toast(`${providerLabel(active)} 连接成功：${result.reply || 'OK'}`);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    await loadCore();
  }
}

function renderChrome() {
  const status = modelStatus();
  const chip = $('#providerChip');
  chip.textContent = status.label;
  chip.className = `chip ${status.state === 'ready' ? 'ok' : status.state === 'unconfigured' || status.state === 'unverified' ? 'warn' : 'danger'}`;

  const dot = $('#sideDot');
  dot.className = `dot ${status.state === 'ready' ? 'ok' : 'warn'}`;
  $('#sideStatus').textContent = status.label;
  renderSetupBanner();

  const badge = $('#patchBadge');
  const count = patchCount();
  badge.textContent = String(count);
  badge.classList.toggle('hidden', count === 0);
}

function setView(view, updateHash = true) {
  if (!VIEW_META[view]) view = 'dashboard';
  state.view = view;
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  $$('.view').forEach(section => section.classList.toggle('active', section.id === `view-${view}`));
  const [title, subtitle] = VIEW_META[view] || ['', ''];
  $('#viewTitle').textContent = title;
  $('#viewSub').textContent = subtitle;
  if (updateHash && location.hash !== `#${view}`) {
    history.replaceState(null, '', `#${view}`);
  }
  if (view === 'wiki') {
    const frame = $('#wikiFrame');
    if (frame) frame.src = `/wiki/?t=${Date.now()}`;
    loadWikiSyncStatus();
  }
  if (view === 'graph') loadGraph();
  if (view === 'usage') loadUsage();
  if (view === 'learning') {
    renderLearning();
    loadReviewStats();
  }
}

async function loadWikiSyncStatus() {
  const hint = $('#wikiSyncHint');
  if (!hint) return;
  try {
    const status = await api('/api/wiki/status');
    const sync = status.sync || {};
    hint.textContent = sync.watching
      ? `自动同步已开启${sync.last_sync_at ? ` · 上次 ${fmtDateTime(sync.last_sync_at)}` : ''}`
      : '自动同步未运行';
  } catch (error) {
    hint.textContent = '';
  }
}

async function loadCore() {
  const [status, settings] = await Promise.all([api('/api/state'), api('/api/settings')]);
  state.status = status;
  state.settings = settings;
  renderChrome();
}

async function loadFeed(append = false) {
  if (!append) {
    state.feedOffset = 0;
    state.feedSelected.clear();
  }
  const params = new URLSearchParams({
    limit: String(state.feedPageSize),
    offset: String(state.feedOffset),
    sort: state.feedSort,
  });
  if (state.feedQuery.trim()) params.set('q', state.feedQuery.trim());
  if (state.feedStatus) params.set('status', state.feedStatus);
  if (state.feedSourceId) params.set('source_id', state.feedSourceId);
  const data = await api(`/api/feed?${params.toString()}`);
  const incoming = data.items || [];
  state.feed = append ? [...state.feed, ...incoming] : incoming;
  state.feedTotal = Number(data.total || 0);
  state.feedHasMore = Boolean(data.has_more);
  state.feedOffset = append ? state.feedOffset + incoming.length : incoming.length;
  renderFeed();
  renderDashboard();
}

async function loadMoreFeed() {
  if (!state.feedHasMore) return;
  await loadFeed(true);
}

async function loadCollections() {
  const data = await api('/api/collections');
  state.collections = data.items || [];
  renderCollections();
}

async function loadPatches() {
  const data = await api('/api/patches');
  state.patches = data.items || [];
  renderPatches();
  renderChrome();
  renderDashboard();
}

async function loadSources() {
  const data = await api('/api/sources');
  state.sources = data.items || [];
  if (state.feedSourceId && !state.sources.some(source => source.id === state.feedSourceId)) {
    state.feedSourceId = '';
  }
  renderSources();
  renderFeedSourceSidebar();
  if (state.view === 'settings') renderSettings();
}

async function loadSourceCatalog() {
  if (state.sourceCatalogLoaded) return;
  try {
    const data = await api('/api/sources/catalog');
    state.sourceCatalog = data.items || [];
    state.sourceCatalogLoaded = true;
    renderSourceCatalog();
  } catch (error) {
    $('#catalogHint').textContent = error.message;
  }
}

function renderSourceCatalog() {
  const container = $('#sourceCatalog');
  if (!container) return;
  const categories = [...new Set(state.sourceCatalog.map(item => item.category))];
  container.innerHTML = categories.map(category => {
    const items = state.sourceCatalog.filter(item => item.category === category);
    return `<div class="source-catalog-category"><h5>${esc(category)}</h5>${items.map(item => `
      <label class="source-catalog-item">
        <input type="checkbox" data-catalog-id="${esc(item.id)}" ${item.priority ? 'checked' : ''}>
        <span><strong>${esc(item.name)}</strong><small>${esc(item.description || '')}</small></span>
      </label>`).join('')}</div>`;
  }).join('');
}

async function importCatalog() {
  const ids = $$('[data-catalog-id]:checked').map(input => input.dataset.catalogId);
  if (!ids.length) {
    toast('先勾选要导入的来源', 'error');
    return;
  }
  const button = $('#importCatalog');
  busy(button, true);
  try {
    const result = await api('/api/sources/catalog', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
    toast(`已添加 ${result.items?.length || 0} 个来源`);
    await loadCore();
    await loadSources();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function refreshAll() {
  try {
    await loadCore();
    await Promise.all([loadFeed(), loadCollections(), loadPatches(), loadSources()]);
    renderSettings();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderDashboard() {
  const container = $('#dashboardContent');
  if (!container) return;
  const status = state.status;
  if (!status) {
    container.innerHTML = emptyState('正在加载…', '读取本地知识库状态。');
    return;
  }
  if (!status.ready && !state.feed.length) {
    container.innerHTML = emptyState(
      '还没有连接模型',
      '应用可以空着运行。配置任意一家 API Key 后，Agent 才能生成摘要、翻译和回答问题。',
      `<button class="btn primary" data-action="go-settings">配置模型</button>
       <button class="btn ghost" data-action="seed-demo">加载示例内容</button>`
    );
    return;
  }

  const stats = status.stats || {};
  const cards = `
    <div class="stats-grid">
      <div class="stat"><div class="num">${stats.feed ?? 0}</div><div class="label">资讯条目</div></div>
      <div class="stat"><div class="num">${stats.saved ?? 0}</div><div class="label">收藏</div></div>
      <div class="stat"><div class="num">${stats.notes ?? 0}</div><div class="label">Markdown 笔记</div></div>
      <div class="stat"><div class="num">${stats.patches ?? 0}</div><div class="label">待审补丁</div></div>
    </div>`;

  if (!status.ready) {
    container.innerHTML = cards + `
      <div class="panel" style="margin-bottom:16px">
        <h3>模型未配置</h3>
        <p class="subtle">可以浏览已有内容；AI 摘要、翻译和问答需要先配置模型。</p>
        <div class="card-actions" style="border-top:0;padding-top:10px">
          <button class="btn primary" data-action="go-settings">配置模型</button>
        </div>
      </div>` + dashboardPanels();
    return;
  }

  if (!state.feed.length) {
    container.innerHTML = cards + emptyState(
      '模型已就绪，知识库为空',
      '抓取一批 RSS 或 GitHub 热门仓库，Agent 会生成中文摘要，保存后进入 Vault。',
      `<button class="btn primary" data-action="go-feed">去抓取资讯</button>
       <button class="btn ghost" data-action="seed-demo">加载示例内容</button>`
    );
    return;
  }

  container.innerHTML = cards + dashboardPanels();
}

function dashboardPanels() {
  const recent = state.feed.slice(0, 4).map(item => `
    <div class="mini-item">
      <div class="t">${esc(item.title)}</div>
      <div class="m">${esc(sourceLabel(item.source_type))} · ${fmtDate(item.retrieved_at)}</div>
    </div>`).join('');
  const patches = state.patches.slice(0, 4).map(patch => `
    <div class="mini-item">
      <div class="t">${esc(patch.title)}</div>
      <div class="m">${esc(patch.patch_type)}</div>
    </div>`).join('');

  return `
    <div class="dashboard-grid">
      <div class="panel">
        <h3>最新资讯</h3>
        <div class="mini-list">${recent || '<div class="subtle">暂无资讯</div>'}</div>
      </div>
      <div class="panel">
        <h3>待处理</h3>
        <div class="mini-list">${patches || '<div class="subtle">没有待审补丁</div>'}</div>
      </div>
    </div>`;
}

function feedCard(item, { collection = false } = {}) {
  const summary = item.summary_zh || item.summary || (item.content || '').slice(0, 220);
  const translation = item.translation_zh || '';
  const tags = (item.tags || []).slice(0, 6).map(tag => `<span class="tag">${esc(tag)}</span>`).join('');
  const meta = [
    item.primary_language,
    item.stars ? `★ ${item.stars}` : '',
    item.license,
    fmtDate(item.published_at || item.retrieved_at),
  ].filter(Boolean).map(value => `<span>${esc(value)}</span>`).join('');
  const relevance = Math.round(Number(item.relevance_score || 0) * 100);
  const relevanceHtml = relevance
    ? `<span class="relevance ${relevance >= 70 ? 'high' : relevance >= 40 ? 'mid' : 'low'}" title="${esc(item.relevance_reason || '')}">匹配 ${relevance}%</span>`
    : '';
  const gaps = (item.knowledge_gaps || []).slice(0, 3)
    .map(gap => `<span class="gap-tag">${esc(gap)}</span>`).join('');
  const aiLabel = item.summary_zh && item.translation_zh ? '重新翻译+摘要' : 'AI 翻译+摘要';

  const selected = !collection && state.feedSelected.has(item.id);
  return `
    <article class="card ${selected ? 'selected' : ''}" data-id="${esc(item.id)}">
      ${collection ? '' : `<label class="feed-select"><input type="checkbox" data-select-feed="${esc(item.id)}" ${selected ? 'checked' : ''}></label>`}
      <div class="card-top">
        <div style="min-width:0">
          <span class="source-badge ${item.source_type === 'github' ? 'github' : ''}">${esc(sourceLabel(item.source_type))}</span>
          <h3 class="card-title"><a href="${safeUrl(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}</a></h3>
          <p class="card-summary">${esc(summary || '（暂无中文摘要，等待 AI 补全）')}</p>
        </div>
      </div>
      <div class="card-meta">${meta}${relevanceHtml}</div>
      ${tags ? `<div class="tags">${tags}</div>` : ''}
      ${gaps ? `<div class="gaps"><span class="hint">知识缺口</span>${gaps}</div>` : ''}
      ${translation ? `<details class="translation"><summary>中文翻译</summary><div class="translation-body">${esc(translation)}</div></details>` : ''}
      <div class="card-actions">
        ${collection ? '' : `<button class="btn" data-action="summarize">${aiLabel}</button>`}
        ${item.status === 'saved'
          ? '<span class="chip ok">已收藏</span>'
          : item.status === 'dismissed'
            ? '<span class="chip">已忽略</span>'
            : `<button class="btn primary" data-action="save">收藏</button>`}
        ${collection
          ? `<button class="btn ghost" data-action="unsave">取消收藏</button>`
          : item.status === 'dismissed'
            ? `<button class="btn ghost" data-action="restore">恢复未读</button>`
            : `<button class="btn ghost" data-action="dismiss">忽略</button>`}
        <button class="btn ghost" data-action="import">入库</button>
        <a class="btn ghost" href="${safeUrl(item.url)}" target="_blank" rel="noreferrer">打开原文</a>
      </div>
    </article>`;
}

const PROFILE_LANGUAGES = [
  'C', 'C++', 'C#', 'Python', 'Go', 'Rust', 'Java', 'JavaScript',
  'TypeScript', 'SQL', 'Shell', 'Kotlin', 'Swift', '其他',
];

const FEED_SOURCE_TYPES = [
  ['github', 'GitHub'],
  ['rss', 'RSS'],
  ['arxiv', 'arXiv'],
  ['devto', 'Dev.to'],
  ['csdn', 'CSDN'],
  ['qt', 'Qt Blog'],
  ['author', '博主'],
  ['html', '网页'],
];

const FEED_FILTER_GROUPS = [
  { key: 'skills', configKey: 'feed_filter_skills', label: '已有技能' },
  { key: 'interests', configKey: 'feed_filter_interests', label: '兴趣方向' },
  { key: 'goals', profileKey: 'learning_goals', configKey: 'feed_filter_goals', label: '学习目标' },
];

function renderFeedProfileFilter() {
  const container = $('#feedProfileFilterGroups');
  if (!container || !state.settings) return;
  const profile = state.settings.profile || {};
  const selectedSources = new Set(state.settings.feed_filter_sources || []);
  const sourceChips = FEED_SOURCE_TYPES.map(([value, label]) => `
    <label class="filter-chip">
      <input type="checkbox" data-feed-source-filter="${value}" value="${value}" ${selectedSources.has(value) ? 'checked' : ''}>
      <span>${label}</span>
    </label>`).join('');
  const sourceGroup = `<div class="filter-chip-group"><span class="filter-group-label">抓取来源</span>${sourceChips}</div>`;
  const groups = FEED_FILTER_GROUPS.map(group => {
    const values = profile[group.profileKey || group.key] || [];
    const selected = new Set(state.settings[group.configKey] || []);
    if (!values.length) {
      return `<div class="filter-chip-group"><span class="filter-group-label">${group.label}</span><span class="hint">未填写</span></div>`;
    }
    const chips = values.map(value => `
      <label class="filter-chip">
        <input type="checkbox" data-feed-filter-group="${group.key}" value="${esc(value)}" ${selected.has(value) ? 'checked' : ''}>
        <span>${esc(value)}</span>
      </label>`).join('');
    return `<div class="filter-chip-group"><span class="filter-group-label">${group.label}</span>${chips}</div>`;
  }).join('');
  container.innerHTML = sourceGroup + groups;
}

function renderFeedSourceSidebar() {
  const container = $('#feedSourceList');
  if (!container) return;
  const sources = state.sources.filter(source => (source.source_group || 'other') !== 'github');
  const allCount = sources.reduce((sum, source) => sum + Number(source.item_count || 0), 0);
  const rows = [
    `<button class="feed-source-item ${state.feedSourceId ? '' : 'active'}" data-feed-source-id="">
      <span>全部</span><span>${allCount}</span>
    </button>`,
    ...sources.map(source => `
      <button class="feed-source-item ${state.feedSourceId === source.id ? 'active' : ''}" data-feed-source-id="${esc(source.id)}">
        <span>${esc(source.name || source.url)}</span><span>${Number(source.item_count || 0)}</span>
      </button>`),
  ];
  container.innerHTML = rows.join('');
}

function renderFeed() {
  renderFeedProfileFilter();
  const github = state.feedTab === 'github';
  $('#rssPanel').hidden = github;
  $('#githubPanel').hidden = !github;
  $$('.feed-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.feedTab === state.feedTab);
  });
  $$('.sort-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.feedSort === state.feedSort);
  });
  renderFeedSourceSidebar();
  if (github) {
    renderGithub();
    return;
  }

  const container = $('#feedList');
  const enrich = state.status?.feed_enrichment;
  const hint = $('#enrichHint');
  if (hint) {
    if (enrich?.running) {
      hint.textContent = `正在翻译+摘要 ${enrich.done}/${enrich.total}`;
    } else if (enrich?.pending) {
      hint.textContent = `待补全 ${enrich.pending} 条`;
    } else {
      hint.textContent = '';
    }
  }
  const items = state.feed.filter(item => item.source_type !== 'github');
  const hintText = $('#feedFilterHint');
  if (hintText) hintText.textContent = `${items.length}/${state.feedTotal || items.length} 条`;
  if (!items.length) {
    const filtered = Boolean(state.feedQuery.trim() || state.feedStatus || state.feedSourceId);
    container.innerHTML = emptyState(
      filtered ? '没有符合筛选的资讯' : '还没有 RSS 资讯',
      filtered
        ? '换一个关键词或清空筛选条件。'
        : (state.status?.ready
          ? '在设置页添加 RSS 源，或者用顶部输入框抓取一个 Feed。'
          : '先配置模型，再抓取资讯。'),
      filtered
        ? '<button class="btn ghost" data-action="clear-feed-filter">清空筛选</button>'
        : (state.status?.ready
          ? '<button class="btn primary" data-action="go-feed-top">去抓取</button>'
          : '<button class="btn primary" data-action="go-settings">配置模型</button>')
    );
    updateBulkUI();
    return;
  }
  const loadMore = state.feedHasMore
    ? `<div class="load-more"><button class="btn ghost" data-action="load-more-feed">加载更多（已显示 ${items.length}/${state.feedTotal}）</button></div>`
    : '<div class="load-more"><span class="hint">已显示全部</span></div>';
  container.innerHTML = items.map(item => feedCard(item)).join('') + loadMore;
  updateBulkUI();
}

function updateBulkUI() {
  const visible = state.feed.filter(item => item.source_type !== 'github');
  const ids = visible.map(item => item.id);
  const selected = ids.filter(id => state.feedSelected.has(id));
  const selectAll = $('#selectAllFeed');
  if (selectAll) {
    selectAll.checked = ids.length > 0 && selected.length === ids.length;
    selectAll.indeterminate = selected.length > 0 && selected.length < ids.length;
  }
  ['bulkRead', 'bulkUnread', 'bulkSave', 'bulkDismiss', 'bulkDelete'].forEach(id => {
    const button = document.getElementById(id);
    if (button) button.disabled = selected.length === 0;
  });
}

function renderGithubControls() {
  const meta = state.githubMeta;
  const stackBox = $('#githubStacks');
  const metricBox = $('#githubMetrics');
  if (!meta) {
    stackBox.innerHTML = '';
    metricBox.innerHTML = '';
    return;
  }
  stackBox.innerHTML = meta.stacks.map(stack => `
    <button class="stack-chip ${stack.id === state.githubStack ? 'active' : ''}" data-stack="${esc(stack.id)}">${esc(stack.name)}</button>
  `).join('');
  metricBox.innerHTML = meta.metrics.map(metric => `
    <button class="rank-tab ${metric.id === state.githubMetric ? 'active' : ''}" data-metric="${esc(metric.id)}">${esc(metric.name)}</button>
  `).join('');
}

function rankCard(item, index) {
  const topics = (item.topics || []).slice(0, 4)
    .map(topic => `<span class="tag">${esc(topic)}</span>`).join('');
  const description = item.summary_zh || item.summary || (item.content || '').slice(0, 220);
  const translation = item.translation_zh || '';
  return `
    <article class="rank-card" data-rank-index="${index}">
      <div class="rank-index">${String(index + 1).padStart(2, '0')}</div>
      <div class="rank-main">
        <div class="rank-title">
          <a href="${safeUrl(item.url)}" target="_blank" rel="noreferrer">${esc(item.repo_full_name || item.title)}</a>
          ${item.primary_language ? `<span class="rank-language">${esc(item.primary_language)}</span>` : ''}
        </div>
        <p class="rank-desc">${esc(description || '暂无描述')}</p>
        <div class="rank-meta">
          <span>★ ${fmtCount(item.stars)}</span>
          ${item.star_gain ? `<span class="star-gain">+${fmtCount(item.star_gain)} ★ / ${item.snapshot_days} 天</span>` : ''}
          <span>Fork ${fmtCount(item.forks)}</span>
          ${item.license ? `<span>${esc(item.license)}</span>` : ''}
          <span>创建 ${fmtDate(item.published_at)}</span>
        </div>
        ${topics ? `<div class="tags">${topics}</div>` : ''}
        ${translation ? `<details class="translation"><summary>中文翻译</summary><div class="translation-body">${esc(translation)}</div></details>` : ''}
      </div>
      <div class="rank-actions">
        <button class="btn ghost" data-github-favorite>收藏</button>
        <a class="btn ghost rank-open" href="${safeUrl(item.url)}" target="_blank" rel="noreferrer">GitHub</a>
      </div>
    </article>`;
}

function renderGithub() {
  renderGithubControls();
  const container = $('#githubRanking');
  const notice = $('#githubNotice');
  const data = state.githubRanking;
  if (!state.githubMeta) {
    container.innerHTML = '<div class="rank-loading">正在加载 GitHub 技术栈…</div>';
    return;
  }
  if (!data && state.githubLoading) {
    container.innerHTML = '<div class="rank-loading">正在查询 GitHub 榜单…</div>';
    return;
  }
  if (!data) {
    notice.textContent = state.githubMeta.notice || '';
    container.innerHTML = '<div class="rank-empty">选择一个技术栈查看榜单。</div>';
    return;
  }
  const metric = data.metric || {};
  const cacheText = data.cached
    ? `缓存 ${fmtDateTime(data.fetched_at)}${data.stale ? ' · 已过期' : ''}`
    : `更新于 ${fmtDateTime(data.fetched_at)}`;
  notice.textContent = `${metric.hint || ''} · ${cacheText}${data.notice ? ` · ${data.notice}` : ''}${data.error ? ` · ${data.error}` : ''}`;
  notice.title = state.githubMeta.notice || '';
  if (!data.items?.length) {
    const message = data.notice || data.error || '这个榜单暂时没有结果。';
    container.innerHTML = `<div class="rank-empty">${esc(message)}</div>`;
    return;
  }
  container.innerHTML = data.items.map((item, index) => rankCard(item, index)).join('');
}

async function loadGithubMeta() {
  if (state.githubMeta) return;
  state.githubMeta = await api('/api/github/meta');
  renderGithubControls();
}

async function loadGithubRanking(refresh = false) {
  if (!state.githubMeta) await loadGithubMeta();
  state.githubLoading = true;
  renderGithub();
  try {
    const query = new URLSearchParams({
      stack: state.githubStack,
      metric: state.githubMetric,
      limit: '10',
      refresh: refresh ? 'true' : 'false',
    });
    state.githubRanking = await api(`/api/github/rankings?${query}`);
  } catch (error) {
    state.githubRanking = { items: [], error: error.message, metric: {}, cached: false };
  } finally {
    state.githubLoading = false;
    renderGithub();
  }
}

async function switchFeedTab(tab) {
  state.feedTab = tab;
  renderFeed();
  if (tab === 'github') {
    try {
      await loadGithubMeta();
      if (!state.githubRanking) await loadGithubRanking();
    } catch (error) {
      toast(error.message, 'error');
    }
  }
}

async function applyFeedFilters() {
  state.feedStatus = $('#feedStatus').value;
  await loadFeed();
}

async function clearFeedFilters() {
  $('#feedStatus').value = '';
  state.feedQuery = '';
  state.feedStatus = '';
  state.feedSourceId = '';
  await loadFeed();
}

async function bulkFeedStatus(action) {
  const ids = [...state.feedSelected];
  if (!ids.length) return;
  if (action === 'delete' && !confirm(`永久删除选中的 ${ids.length} 条资讯？此操作不可恢复。`)) return;
  try {
    const result = await api('/api/feed/bulk', {
      method: 'POST',
      body: JSON.stringify({ ids, action }),
    });
    toast(`已更新 ${result.updated} 条资讯`);
    await loadFeed();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderCollections() {
  const container = $('#collectionsList');
  if (!container) return;
  $$('.collection-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.collectionTab === state.collectionTab);
  });
  const github = state.collectionTab === 'github';
  const items = state.collections.filter(item => (item.source_type === 'github') === github);
  if (!items.length) {
    container.innerHTML = emptyState(
      github ? '还没有 GitHub 收藏' : '还没有 RSS / 其他收藏',
      '在资讯页点击“收藏”，内容会以引用形式出现在这里。',
    );
    return;
  }
  container.innerHTML = items.map(item => feedCard(item, { collection: true })).join('');
}

async function loadUsage(force = false) {
  const summary = $('#usageSummary');
  if (summary && state.usageLoading) return;
  state.usageLoading = true;
  if (summary) summary.innerHTML = '<div class="hint">正在读取平台用量…</div>';
  try {
    const accounts = await api('/api/usage/accounts');
    state.usageAccounts = accounts.items || [];
    let data = [];
    if (state.usageAccounts.length) {
      const result = await api(`/api/usage/overview${force ? '?force=true' : ''}`);
      data = result.items || [];
    }
    state.usageData = data;
    renderUsage();
  } catch (error) {
    if (summary) summary.innerHTML = `<div class="hint">${esc(error.message)}</div>`;
  } finally {
    state.usageLoading = false;
  }
}

function usageMoney(value, currency = '¥') {
  if (value === null || value === undefined) return '—';
  return `${currency}${Number(value).toFixed(2)}`;
}

function renderUsage() {
  const summary = $('#usageSummary');
  const accounts = $('#usageAccounts');
  if (!summary || !accounts) return;
  if (!state.usageAccounts.length) {
    summary.innerHTML = emptyState('还没有用量账户', '添加 DeepSeek、米醋或 CCTQ 账户后，这里会显示 Token 消耗和余额。');
  } else {
    summary.innerHTML = state.usageData.map(item => {
      if (!item.ok) {
        return `<div class="usage-card"><h4>${esc(item.name)}</h4><div class="hint">${esc(item.error || '读取失败')}</div></div>`;
      }
      const balance = item.balance || {};
      const today = item.today || {};
      const period = item.period || {};
      const models = (item.models || []).slice(0, 6)
        .map(model => `<div class="usage-stat"><span>${esc(model.model)}</span><strong>${fmtCount(model.tokens)}</strong></div>`).join('');
      return `<div class="usage-card">
        <h4>${esc(item.name)}</h4>
        <div class="usage-stat"><span>余额</span><strong>${usageMoney(balance.remaining, balance.currency || '¥')}</strong></div>
        ${balance.used !== undefined ? `<div class="usage-stat"><span>累计已用</span><strong>${usageMoney(balance.used, balance.currency || '¥')}</strong></div>` : ''}
        <div class="usage-stat"><span>今日 Token</span><strong>${fmtCount(today.tokens || 0)}</strong></div>
        <div class="usage-stat"><span>今日请求</span><strong>${fmtCount(today.requests || 0)}</strong></div>
        <div class="usage-stat"><span>近 30 天 Token</span><strong>${fmtCount(period.tokens || 0)}</strong></div>
        ${models ? `<div class="usage-note">按模型</div>${models}` : ''}
        ${item.note ? `<div class="usage-note">${esc(item.note)}</div>` : ''}
      </div>`;
    }).join('');
  }
  accounts.innerHTML = state.usageAccounts.map(account => {
    const credential = account.kind === 'deepseek'
      ? `API Key ${account.has_api_key ? '已配置' : '未配置'}${account.has_platform_token ? ' · Platform Token 已配置' : ''}`
      : `${account.base_url || '未填写 Base URL'} · 用户 ${account.user_id || '未填写'} · Token ${account.has_access_token ? '已配置' : '未配置'}`;
    return `<div class="usage-account-row">
      <div><strong>${esc(account.name)}</strong><small>${esc(credential)}</small></div>
      <button class="btn danger small" data-delete-usage="${esc(account.id)}">删除</button>
    </div>`;
  }).join('');
}

async function addUsageAccount() {
  const button = $('#addUsageAccount');
  const kind = $('#usageKind').value;
  const payload = {
    name: $('#usageName').value.trim(),
    kind,
    base_url: $('#usageBaseUrl').value.trim(),
    user_id: $('#usageUserId').value.trim(),
    access_token: $('#usageAccessToken').value.trim(),
    api_key: $('#usageApiKey').value.trim(),
    platform_token: $('#usagePlatformToken').value.trim(),
  };
  if (!payload.name) {
    toast('填写账户名称', 'error');
    return;
  }
  if (kind === 'newapi' && (!payload.base_url || !payload.access_token || !payload.user_id)) {
    toast('New API 需要 Base URL、Access Token 和用户 ID', 'error');
    return;
  }
  if (kind === 'deepseek' && !payload.api_key && !payload.platform_token) {
    toast('DeepSeek 需要 API Key 或 Platform Token', 'error');
    return;
  }
  busy(button, true);
  try {
    await api('/api/usage/accounts', { method: 'POST', body: JSON.stringify(payload) });
    $('#usageName').value = '';
    $('#usageBaseUrl').value = '';
    $('#usageUserId').value = '';
    $('#usageAccessToken').value = '';
    $('#usageApiKey').value = '';
    $('#usagePlatformToken').value = '';
    toast('用量账户已保存');
    await loadUsage(true);
  } catch (error) {
    $('#usageHint').textContent = error.message;
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function loginUsageAccount() {
  const button = $('#loginUsageAccount');
  const kind = $('#usageKind').value;
  const payload = {
    name: $('#usageName').value.trim(),
    kind,
    base_url: $('#usageBaseUrl').value.trim(),
  };
  if (!payload.name) {
    toast('先填写账户名称', 'error');
    return;
  }
  if (kind === 'newapi' && !payload.base_url) {
    toast('New API 登录需要 Base URL', 'error');
    return;
  }
  busy(button, true);
  $('#usageHint').textContent = '请在登录窗口完成平台登录，然后点击“完成绑定”。';
  try {
    await api('/api/usage/login', { method: 'POST', body: JSON.stringify(payload) });
    toast('账户绑定成功');
    $('#usageName').value = '';
    $('#usageBaseUrl').value = '';
    $('#usageUserId').value = '';
    $('#usageAccessToken').value = '';
    $('#usageApiKey').value = '';
    $('#usagePlatformToken').value = '';
    await loadUsage(true);
  } catch (error) {
    $('#usageHint').textContent = error.message;
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function deleteUsageAccount(accountId) {
  if (!confirm('删除该用量账户？')) return;
  try {
    await api(`/api/usage/accounts/${accountId}`, { method: 'DELETE' });
    await loadUsage(true);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderPatches() {
  const container = $('#patchList');
  if (!container) return;
  if (!state.patches.length) {
    container.innerHTML = emptyState('没有待处理补丁', '问答时勾选“同时生成知识页补丁”，或让 Agent 维护知识库后，会在这里出现。');
    return;
  }
  container.innerHTML = state.patches.map(patch => {
    const refs = (patch.source_refs || []).length;
    return `
      <article class="card patch-card" data-id="${esc(patch.id)}">
        <div class="card-top">
          <div>
            <span class="patch-type ${patch.patch_type === 'conflict' ? 'conflict' : ''}">${esc(patch.patch_type)}</span>
            <h3 class="card-title">${esc(patch.title)}</h3>
            <div class="patch-target">${esc(patch.target_path)}</div>
          </div>
          <div class="card-meta">${refs} 个来源</div>
        </div>
        <div class="patch-preview">${esc((patch.content || '').slice(0, 900))}</div>
        <div class="card-actions">
          <button class="btn primary" data-action="apply-patch">应用</button>
          <button class="btn danger" data-action="reject-patch">拒绝</button>
          <span class="hint">${esc(fmtDate(patch.created_at))} 创建</span>
        </div>
      </article>`;
  }).join('');
}

const SOURCE_ADAPTER_LABELS = {
  github_trending: 'GitHub 热门',
  github_search: 'GitHub 搜索',
  github_repo: 'GitHub 仓库',
  rss: 'RSS',
  csdn: 'CSDN',
  qt: 'Qt Blog',
  arxiv: 'arXiv',
  devto: 'Dev.to',
  author: '博主',
  html: 'HTML',
};

const SOURCE_ADAPTER_OPTIONS = {
  github: [
    ['github_search', 'GitHub 搜索订阅'],
    ['github_repo', 'GitHub 仓库订阅'],
    ['github_trending', 'GitHub 热门'],
  ],
  other: [
    ['rss', 'RSS / Atom'],
    ['author', '博主主页'],
    ['csdn', 'CSDN 博主'],
    ['qt', 'Qt Blog'],
    ['html', '通用 HTML 列表'],
    ['arxiv', 'arXiv'],
    ['devto', 'Dev.to'],
  ],
};

function renderSourceForm() {
  const adapter = $('#newSourceAdapter');
  const query = $('#newSourceQuery');
  if (!adapter || !query) return;
  const options = SOURCE_ADAPTER_OPTIONS[state.sourceGroup] || [];
  adapter.innerHTML = options.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
  const github = state.sourceGroup === 'github';
  query.classList.toggle('hidden', !github);
  $('#newSourceLanguage').classList.toggle('hidden', !github);
  $('#newSourceStars').classList.toggle('hidden', !github);
  query.placeholder = '查询词，例如 C++、Qt、compiler';
  const url = $('#newSourceUrl');
  url.placeholder = github
    ? 'GitHub 搜索可填 https://github.com（可选）'
    : '博主主页 / RSS / CSDN / Qt Blog 地址';
  $('#sourceAddHint').textContent = github
    ? 'GitHub 搜索订阅会按查询词定时抓取仓库；也可以填写 owner/repo 订阅单个仓库。'
    : '粘贴博主主页或 RSS 地址，点“自动识别”可检测 Feed / CSDN / Qt Blog。';
}

function renderSources() {
  const container = $('#sourceList');
  if (!container) return;
  renderSourceForm();
  $$('.source-group-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.sourceGroup === state.sourceGroup);
  });
  const items = state.sources.filter(source => (source.source_group || 'other') === state.sourceGroup);
  if (!items.length) {
    container.innerHTML = state.sourceGroup === 'github'
      ? '<div class="hint">还没有 GitHub 订阅。添加一个搜索词，或订阅 owner/repo。</div>'
      : '<div class="hint">还没有其他来源。可以添加 RSS、CSDN 博主、Qt Blog 或博主主页。</div>';
    return;
  }
  container.innerHTML = items.map(source => {
    const adapter = source.adapter || 'rss';
    const label = SOURCE_ADAPTER_LABELS[adapter] || adapter;
    const github = source.source_group === 'github';
    const status = source.last_status === 'ok'
      ? '正常'
      : source.last_status === 'error' ? '失败' : '未抓取';
    const statusClass = source.last_status === 'ok' ? 'ok' : '';
    const last = source.last_fetch_at ? fmtDateTime(source.last_fetch_at) : '尚未抓取';
    const error = source.last_error ? ` · ${source.last_error.slice(0, 80)}` : '';
    const config = source.config || {};
    const detail = github
      ? [config.query, config.language, config.min_stars ? `★>${config.min_stars}` : ''].filter(Boolean).join(' · ')
      : (config.feed_url || config.rss_url || config.user || source.url);
    return `
      <div class="source-item" data-id="${esc(source.id)}">
        <input type="checkbox" data-source-toggle ${source.enabled ? 'checked' : ''} title="启用/停用">
        <div class="source-main">
          <div class="source-name">
            <span class="source-kind ${github ? 'github' : ''}">${esc(label)}</span>
            ${esc(source.name || source.url)}
            <span class="status-pill ${statusClass}">${status}</span>
          </div>
          <div class="source-url">${esc(detail || source.url)}</div>
          <div class="hint">${source.item_count || 0} 条 · ${esc(last)}${esc(error)}</div>
        </div>
        <div class="source-actions">
          <button class="btn" data-source-fetch>抓取</button>
          <button class="btn ghost" data-source-edit>编辑</button>
          <button class="btn danger" data-source-delete>删除</button>
        </div>
      </div>`;
  }).join('');
}

const OFFICIAL_MODEL_DEFAULTS = {
  openai: 'gpt-4o-mini',
  anthropic: 'claude-3-5-haiku-latest',
  gemini: 'gemini-1.5-flash',
  deepseek: 'deepseek-chat',
};

function modelCard(name, item, active) {
  const label = providerLabel(name, item);
  const thirdParty = item.kind === 'third_party';
  const status = item.has_key ? '已配置' : '待配置';
  return `
    <div class="model-card ${name === active ? 'active' : ''}" data-provider="${esc(name)}">
      <div class="model-card-head">
        <label class="model-radio">
          <input type="radio" name="activeProvider" value="${esc(name)}" ${name === active ? 'checked' : ''}>
          <span>${esc(label)}</span>
        </label>
        <div class="model-card-actions">
          <span class="provider-tag">${thirdParty ? '第三方' : '官方'}</span>
          <span class="status-pill ${item.has_key ? 'ok' : ''}">${status}</span>
          <button class="btn ghost small" data-save-model="${esc(name)}">保存</button>
          <button class="btn danger small" data-remove-model="${esc(name)}" data-model-kind="${thirdParty ? 'third_party' : 'official'}">移除</button>
        </div>
      </div>
      <div class="model-meta">
        <code>${esc(item.model || '未填写模型')}</code>
        <span>${thirdParty ? `${esc(item.protocol || 'openai-compatible')} · ${esc(item.base_url || '未填写 Base URL')}` : '官方接口（无需 Base URL）'}</span>
      </div>
      <div class="model-fields">
        <label class="field">
          <span>API Key</span>
          <input class="input" type="password" data-field="api_key" placeholder="${item.has_key ? '已保存，留空保持不变' : '粘贴 API Key'}">
          <span class="hint">修改后点本卡片“保存”，或直接点“测试当前模型”。</span>
        </label>
        <div class="field model-picker">
          <span>模型名</span>
          <div class="model-picker-row">
            <input class="input" data-field="model" value="${esc(item.model || '')}">
            <button class="btn ghost" type="button" data-fetch-model-list="${esc(name)}">获取模型</button>
          </div>
          <select class="input model-list hidden" data-model-select></select>
        </div>
        ${thirdParty ? `
          <label class="field">
            <span>显示名称</span>
            <input class="input" data-field="label" value="${esc(item.label || label)}">
          </label>
          <label class="field">
            <span>协议</span>
            <select class="input" data-field="protocol">
              <option value="openai-compatible" ${!['anthropic-compatible', 'openai-responses'].includes(item.protocol) ? 'selected' : ''}>OpenAI Chat Completions</option>
              <option value="openai-responses" ${item.protocol === 'openai-responses' ? 'selected' : ''}>OpenAI Responses</option>
              <option value="anthropic-compatible" ${item.protocol === 'anthropic-compatible' ? 'selected' : ''}>Anthropic Messages</option>
            </select>
          </label>
          <label class="field model-base-field">
            <span>Base URL</span>
            <input class="input" data-field="base_url" value="${esc(item.base_url || '')}">
          </label>
` : ''}
      </div>
    </div>`;
}

function renderAddModelPanel() {
  const thirdParty = state.addModelKind === 'third-party';
  $('#addOfficialSection')?.classList.toggle('hidden', thirdParty);
  $('#addThirdPartySection')?.classList.toggle('hidden', !thirdParty);
  $$('#addModelTabs .model-kind-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.addKind === state.addModelKind);
  });
  const select = $('#officialVendor');
  if (select) {
    const providers = state.settings?.providers || {};
    const available = OFFICIAL_PROVIDERS.filter(name => !providers[name]?.has_key);
    select.innerHTML = available.length
      ? available.map(name => `<option value="${esc(name)}">${esc(providerLabel(name))}</option>`).join('')
      : '<option value="">全部官方厂商已配置</option>';
    select.disabled = !available.length;
    if (available.length) {
      select.value = available[0];
      $('#officialModel').value = OFFICIAL_MODEL_DEFAULTS[available[0]] || '';
    } else {
      $('#officialModel').value = '';
    }
  }
}

function renderSettingsTab() {
  $$('.settings-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.settingsTab === state.settingsTab);
  });
  $$('.settings-panel').forEach(panel => {
    panel.classList.toggle('hidden', panel.id !== `settings-panel-${state.settingsTab}`);
  });
}

function renderScheduleMode() {
  const daily = state.scheduleMode === 'daily';
  $('#dailyScheduleRow')?.classList.toggle('hidden', !daily);
  $('#intervalScheduleRow')?.classList.toggle('hidden', daily);
  $$('#scheduleModeTabs .schedule-mode-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.scheduleMode === state.scheduleMode);
  });
}

function renderProfileLanguages(languages) {
  const container = $('#profileLanguages');
  if (!container) return;
  const selected = new Set(languages || []);
  container.innerHTML = PROFILE_LANGUAGES.map(language => `
    <label class="filter-chip">
      <input type="checkbox" data-profile-language value="${esc(language)}" ${selected.has(language) ? 'checked' : ''}>
      <span>${esc(language)}</span>
    </label>`).join('');
  const technical = $('#profileTechnical').checked;
  $('#profileLanguagesBox').classList.toggle('hidden', !technical);
}

function renderSettings() {
  if (!state.settings) return;
  const settings = state.settings;
  const active = settings.active_provider || 'openai';
  const providers = settings.providers || {};
  const entries = Object.entries(providers)
    .filter(([, item]) => item.has_key || item.kind === 'third_party')
    .sort(([aName, a], [bName, b]) => {
      if (aName === active) return -1;
      if (bName === active) return 1;
      const aOfficial = a.kind !== 'third_party';
      const bOfficial = b.kind !== 'third_party';
      if (aOfficial !== bOfficial) return aOfficial ? -1 : 1;
      return providerLabel(aName, a).localeCompare(providerLabel(bName, b));
    });
  const list = $('#configuredModelList');
  if (list) {
    list.innerHTML = entries.length
      ? entries.map(([name, item]) => modelCard(name, item, active)).join('')
      : emptyState('还没有配置模型', '添加官方厂商或第三方模型后，会在这里看到全部配置。');
  }
  const summary = $('#modelSummary');
  if (summary) {
    const activeItem = providers[active];
    const configured = entries.filter(([, item]) => item.has_key).length;
    summary.innerHTML = activeItem?.has_key
      ? `<span class="dot"></span> 当前使用 <strong>${esc(providerLabel(active, activeItem))}</strong> · 已配置 ${configured} 个模型`
      : `当前模型未配置 · 已配置 ${configured} 个模型`;
  }
  renderAddModelPanel();

  $('#vaultPathInfo').textContent = settings.vault_path || '';
  $('#feedWindow').value = String(settings.feed_window_days || 3);
  const profile = settings.profile || {};
  $('#profileRole').value = profile.target_role || '';
  $('#profileLevel').value = profile.level || '';
  $('#profileHours').value = String(profile.weekly_hours || 5);
  $('#profileTechnical').checked = Boolean(profile.is_technical || (profile.languages || []).length);
  renderProfileLanguages(profile.languages || []);
  $('#profileSkills').value = (profile.skills || []).join(', ');
  $('#profileGoals').value = (profile.learning_goals || []).join(', ');
  const scoring = state.status?.feed_scoring;
  $('#scoreHint').textContent = scoring?.running
    ? `正在评估 ${scoring.done}/${scoring.total}`
    : scoring?.pending ? `待评估 ${scoring.pending} 条` : '';
  $('#queryExpansion').checked = Boolean(settings.query_expansion_enabled);
  $('#autoRefresh').checked = Boolean(settings.auto_refresh_enabled);
  state.scheduleMode = settings.schedule_mode === 'interval' ? 'interval' : 'daily';
  $('#dailyTime').value = settings.daily_time || '06:00';
  $('#refreshInterval').value = String(settings.refresh_interval_minutes ?? 120);
  renderScheduleMode();
  $('#autoGithub').checked = Boolean(settings.auto_refresh_github);
  $('#autoReview').checked = Boolean(settings.auto_review_enabled);
  $('#reviewInterval').value = String(settings.review_interval_days ?? 7);
  const embedding = settings.embedding || {};
  $('#embeddingProvider').value = embedding.provider || 'local';
  $('#embeddingModel').value = embedding.model || '';
  $('#embeddingBase').value = embedding.base_url || '';
  $('#embeddingKey').value = '';
  $('#embeddingKey').placeholder = embedding.has_key
    ? '已保存，留空保持不变'
    : (embedding.provider === 'local' || embedding.provider === 'ollama' ? '不需要' : '粘贴 API Key');
  const embStatus = state.status?.embedding;
  if (embStatus) {
    const pending = embStatus.pending_documents || 0;
    const indexer = state.status?.embedding_indexer;
    $('#embeddingHint').textContent = `${embStatus.provider} · ${embStatus.model} · 已索引 ${embStatus.indexed_documents}/${embStatus.total_documents}${pending ? ` · 待索引 ${pending}` : ''}${embStatus.dimension ? ` · ${embStatus.dimension} 维` : ''}${indexer?.running ? ' · 正在补全…' : ''}`;
  }
  renderSources();
  loadSourceCatalog();
  const sched = state.status?.scheduler;
  const modeLabel = sched?.schedule_mode === 'interval'
    ? `每 ${sched.interval_minutes} 分钟`
    : `每天 ${sched?.daily_time || '06:00'}`;
  $('#schedulerHint').textContent = sched?.enabled
    ? `${modeLabel} · 上次：${sched.last_run ? fmtDateTime(sched.last_run) : '尚未运行'} · 下次：${sched.next_run ? fmtDateTime(sched.next_run) : '等待中'}`
    : '未启用。应用关闭后不会采集。';
  $('#githubToken').value = '';
  $('#githubToken').placeholder = settings.github_token_set ? '已保存，留空保持不变' : '可选';
  $$('.model-card').forEach(card => {
    card.addEventListener('click', event => {
      if (event.target.closest('input, select, button')) return;
      const radio = card.querySelector('input[type=radio]');
      if (radio) {
        radio.checked = true;
        $$('.model-card').forEach(other => other.classList.toggle('active', other === card));
      }
    });
    const remove = card.querySelector('[data-remove-model]');
    if (remove) {
      remove.addEventListener('click', event => {
        event.stopPropagation();
        removeModel(remove.dataset.removeModel, remove.dataset.modelKind);
      });
    }
  });
  renderFeedProfileFilter();
  renderSettingsTab();
}

function gatherSettings() {
  const active = $('input[name=activeProvider]:checked')?.value || 'openai';
  const providers = {};
  $$('.model-card').forEach(card => {
    const name = card.dataset.provider;
    const provider = {};
    const key = card.querySelector('[data-field=api_key]').value.trim();
    if (key) provider.api_key = key;
    const label = card.querySelector('[data-field=label]');
    if (label) provider.label = label.value.trim();
    const protocol = card.querySelector('[data-field=protocol]');
    if (protocol) provider.protocol = protocol.value;
    provider.model = card.querySelector('[data-field=model]').value.trim();
    const baseUrl = card.querySelector('[data-field=base_url]');
    if (baseUrl) provider.base_url = baseUrl.value.trim();
    providers[name] = provider;
  });
  return {
    active_provider: active,
    providers,
    embedding: {
      provider: $('#embeddingProvider').value,
      model: $('#embeddingModel').value.trim(),
      base_url: $('#embeddingBase').value.trim(),
      api_key: $('#embeddingKey').value.trim(),
    },
    profile: {
      target_role: $('#profileRole').value.trim(),
      level: $('#profileLevel').value.trim(),
      is_technical: $('#profileTechnical').checked,
      languages: $('#profileTechnical').checked
        ? $$('[data-profile-language]:checked').map(input => input.value)
        : [],
      weekly_hours: Number($('#profileHours').value || 5),
      skills: $('#profileSkills').value.split(',').map(value => value.trim()).filter(Boolean),
      learning_goals: $('#profileGoals').value.split(',').map(value => value.trim()).filter(Boolean),
    },
    feed_window_days: Number($('#feedWindow').value || 3),
    github_token: $('#githubToken').value.trim(),
    query_expansion_enabled: $('#queryExpansion').checked,
    auto_refresh_enabled: $('#autoRefresh').checked,
    schedule_mode: state.scheduleMode,
    daily_time: $('#dailyTime').value || '06:00',
    refresh_interval_minutes: Number($('#refreshInterval').value || 120),
    auto_refresh_github: $('#autoGithub').checked,
    auto_review_enabled: $('#autoReview').checked,
    review_interval_days: Number($('#reviewInterval').value || 7),
  };
}

async function learnProfile() {
  const button = $('#learnProfile');
  busy(button, true);
  $('#profileLearnHint').textContent = '分析反馈中…';
  try {
    const result = await api('/api/profile/learn', { method: 'POST' });
    state.profileSuggestions = result.suggestions;
    const additions = [
      ...(result.suggestions.skills_add || []),
      ...(result.suggestions.interests_add || []),
      ...(result.suggestions.learning_goals_add || []),
    ];
    $('#profileLearnHint').textContent = result.suggestions.summary || `建议补充：${additions.join('、') || '无'}`;
    $('#applyProfile').classList.toggle('hidden', !additions.length);
  } catch (error) {
    toast(error.message, 'error');
    $('#profileLearnHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function applyProfileSuggestions() {
  if (!state.profileSuggestions) return;
  const button = $('#applyProfile');
  busy(button, true);
  try {
    await api('/api/profile/apply', {
      method: 'POST',
      body: JSON.stringify({ suggestions: state.profileSuggestions }),
    });
    toast('个人画像已更新');
    state.profileSuggestions = null;
    $('#profileLearnHint').textContent = '';
    $('#applyProfile').classList.add('hidden');
    await loadCore();
    renderSettings();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function fetchModels(button) {
  const picker = button.closest('.model-picker');
  if (!picker) return;
  const input = picker.querySelector('input[data-field=model]') || picker.querySelector('input');
  const select = picker.querySelector('[data-model-select]') || picker.querySelector('select');
  const card = button.closest('.model-card');
  if (!input || !select) {
    toast('模型选择器未加载，请关闭后重新打开添加模型面板', 'error');
    return;
  }
  let provider = button.dataset.fetchModelList || null;
  let apiKey = '';
  let baseUrl = '';
  let protocol = null;
  if (card) {
    apiKey = card.querySelector('[data-field=api_key]')?.value.trim() || '';
    baseUrl = card.querySelector('[data-field=base_url]')?.value.trim() || '';
    protocol = card.querySelector('[data-field=protocol]')?.value || null;
  } else if (button.id === 'fetchOfficialModels') {
    provider = $('#officialVendor').value;
    apiKey = $('#officialKey').value.trim();
  } else if (button.id === 'fetchCustomModels') {
    apiKey = $('#customProviderKey').value.trim();
    baseUrl = $('#customProviderBase').value.trim();
    protocol = $('#customProviderProtocol').value;
  }
  if (!provider && !baseUrl) {
    toast('先填写 Base URL', 'error');
    return;
  }
  busy(button, true);
  try {
    const result = await api('/api/providers/models', {
      method: 'POST',
      body: JSON.stringify({
        provider,
        api_key: apiKey || null,
        base_url: baseUrl || null,
        protocol,
      }),
    });
    const models = result.models || [];
    if (!models.length) {
      toast('接口没有返回可用模型', 'error');
      return;
    }
    select.innerHTML = models.map(model => `<option value="${esc(model)}">${esc(model)}</option>`).join('');
    select.classList.remove('hidden');
    const current = input.value.trim();
    select.value = models.includes(current) ? current : models[0];
    input.value = select.value;
    select.onchange = () => {
      input.value = select.value;
    };
    toast(`获取到 ${models.length} 个模型`);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function addOfficialProvider() {
  const button = $('#addOfficialProvider');
  const vendor = $('#officialVendor').value;
  const model = $('#officialModel').value.trim();
  const key = $('#officialKey').value.trim();
  if (!vendor || !model || !key) {
    toast('请选择厂商并填写模型名和 API Key', 'error');
    return;
  }
  busy(button, true);
  try {
    const current = state.settings?.providers?.[state.settings.active_provider];
    const payload = {
      providers: { [vendor]: { api_key: key, model } },
    };
    if (!current?.has_key) payload.active_provider = vendor;
    state.settings = await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    $('#officialKey').value = '';
    $('#officialAddHint').textContent = '已添加，可在列表中编辑或设为当前模型。';
    await loadCore();
    renderSettings();
    toast('官方模型已添加');
  } catch (error) {
    toast(error.message, 'error');
    $('#officialAddHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function removeModel(providerId, kind) {
  if (!providerId) return;
  if (kind === 'third_party') {
    deleteCustomProvider(providerId);
    return;
  }
  if (!confirm(`清除官方模型「${providerId}」的配置？`)) return;
  try {
    state.settings = await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({ providers: { [providerId]: { clear_api_key: true } } }),
    });
    await loadCore();
    renderSettings();
    toast('已清除该官方模型配置');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function addCustomProvider() {
  const button = $('#addCustomProvider');
  const payload = {
    id: $('#customProviderId').value.trim(),
    label: $('#customProviderLabel').value.trim(),
    protocol: $('#customProviderProtocol').value,
    base_url: $('#customProviderBase').value.trim(),
    model: $('#customProviderModel').value.trim(),
    api_key: $('#customProviderKey').value.trim(),
  };
  if (!payload.id || !payload.label || !payload.base_url || !payload.model) {
    toast('请填写标识、显示名称、Base URL 和模型名', 'error');
    return;
  }
  busy(button, true);
  try {
    state.settings = await api('/api/providers/custom', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    $('#customProviderId').value = '';
    $('#customProviderLabel').value = '';
    $('#customProviderBase').value = '';
    $('#customProviderModel').value = '';
    $('#customProviderKey').value = '';
    $('#customProviderHint').textContent = '';
    state.addModelKind = 'third-party';
    renderChrome();
    renderSettings();
    toast('第三方模型已添加，填好 Key 后可测试连接');
  } catch (error) {
    toast(error.message, 'error');
    $('#customProviderHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function deleteCustomProvider(providerId) {
  if (!confirm(`删除第三方模型「${providerId}」？`)) return;
  try {
    state.settings = await api(`/api/providers/custom/${encodeURIComponent(providerId)}`, {
      method: 'DELETE',
    });
    await loadCore();
    renderSettings();
    toast('第三方模型已删除');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function saveSettings(silent = false) {
  const button = $('#saveSettings');
  if (!silent) busy(button, true);
  try {
    state.settings = await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(gatherSettings()),
    });
    await loadCore();
    renderSettings();
    if (!silent) toast('设置已保存');
    return true;
  } catch (error) {
    toast(error.message, 'error');
    return false;
  } finally {
    if (!silent) busy(button, false);
  }
}

async function askQuestion() {
  const question = $('#question').value.trim();
  if (!question) {
    toast('先输入一个问题', 'error');
    return;
  }
  const button = $('#askBtn');
  busy(button, true);
  const panel = $('#answerPanel');
  panel.classList.remove('hidden');
  panel.innerHTML = '<div class="hint"><span class="spinner"></span> 正在检索本地资料并调用模型…</div>';
  try {
    const result = await api('/api/ask', {
      method: 'POST',
      body: JSON.stringify({
        question,
        save_patch: $('#savePatch').checked,
        limit: 6,
      }),
    });
    const citations = (result.citations || []).map(citation => {
      const target = citation.source_url
        ? `<a href="${safeUrl(citation.source_url)}" target="_blank" rel="noreferrer">${esc(citation.title)}</a>`
        : `<span>${esc(citation.title)}</span>`;
      return `<div class="citation"><span class="idx">[${citation.index}]</span><div>${target}<br><span>${esc(citation.path || citation.kind || '')}</span></div></div>`;
    }).join('');
    panel.innerHTML = `
      <h3>回答</h3>
      <div class="answer-text">${renderMarkdown(result.answer)}</div>
      <div class="citations">
        <h4>本地引用 · ${result.context_count} 条上下文</h4>
        ${citations || '<div class="hint">本地没有检索到资料，回答基于模型自身知识。</div>'}
      </div>
      ${result.patch ? `<div class="hint" style="margin-top:12px">已加入补丁队列：${esc(result.patch.target_path)}</div>` : ''}`;
    if (result.patch) await loadPatches();
  } catch (error) {
    panel.innerHTML = `<div class="hint">${esc(error.message)}</div>`;
  } finally {
    busy(button, false);
  }
}

async function itemAction(id, action, button) {
  const card = button?.closest('.card');
  busy(button, true);
  try {
    if (action === 'summarize') {
      await api(`/api/feed/${id}/summarize`, { method: 'POST' });
      toast('中文翻译与摘要已生成');
    } else if (action === 'translate') {
      await api(`/api/feed/${id}/translate`, { method: 'POST' });
      toast('翻译已生成');
    } else if (action === 'save') {
      await api(`/api/feed/${id}/save`, { method: 'POST' });
      toast('已收藏');
    } else if (action === 'import') {
      const result = await api(`/api/feed/${id}/import`, { method: 'POST' });
      toast(`已入库：${result.path || '知识库'}`);
    } else if (action === 'unsave') {
      await api(`/api/feed/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'read' }) });
      toast('已取消收藏');
    } else if (action === 'dismiss') {
      await api(`/api/feed/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'dismissed' }) });
      toast('已忽略，可在状态筛选“已忽略”中查看');
    } else if (action === 'restore') {
      await api(`/api/feed/${id}/status`, { method: 'POST', body: JSON.stringify({ status: 'unread' }) });
      toast('已恢复为未读');
    }
    await loadCore();
    await Promise.all([loadFeed(), loadCollections()]);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
    if (card) card.classList.remove('busy');
  }
}

async function refreshDevto() {
  const tag = $('#devtoTag').value.trim();
  const button = $('#refreshDevto');
  busy(button, true);
  try {
    if (!(await saveSettings(true))) return;
    const result = await api('/api/devto/refresh', {
      method: 'POST',
      body: JSON.stringify({ tag, limit: 10 }),
    });
    toast(`Dev.to 抓取 ${result.fetched} 篇，新增 ${result.new} 篇${result.filtered_out ? `，筛选掉 ${result.filtered_out} 篇` : ''}`);
    await loadCore();
    await loadFeed();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function refreshArxiv() {
  const query = $('#arxivQuery').value.trim();
  if (!query) {
    toast('先填一个 arXiv 搜索词', 'error');
    return;
  }
  const button = $('#refreshArxiv');
  busy(button, true);
  try {
    if (!(await saveSettings(true))) return;
    const result = await api('/api/arxiv/refresh', {
      method: 'POST',
      body: JSON.stringify({ query, limit: 10 }),
    });
    toast(`arXiv 抓取 ${result.fetched} 篇，新增 ${result.new} 篇${result.filtered_out ? `，筛选掉 ${result.filtered_out} 篇` : ''}`);
    await loadCore();
    await loadFeed();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function refreshRss() {
  const url = $('#rssUrl').value.trim();
  if (!url) {
    toast('先填一个 RSS 地址', 'error');
    return;
  }
  const button = $('#refreshRss');
  busy(button, true);
  try {
    if (!(await saveSettings(true))) return;
    const result = await api('/api/feed/refresh', {
      method: 'POST',
      body: JSON.stringify({ kind: 'rss', url }),
    });
    toast(`抓取 ${result.fetched} 条，新增 ${result.new} 条${result.filtered_out ? `，筛选掉 ${result.filtered_out} 条` : ''}`);
    await loadCore();
    await loadFeed();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function refreshGithubRanking() {
  const button = $('#refreshGithubRanking');
  busy(button, true);
  try {
    await loadGithubRanking(true);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function seedDemo() {
  try {
    await api('/api/dev/seed', { method: 'POST' });
    toast('示例内容已加载');
    await refreshAll();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function buildWiki() {
  const button = $('#buildWiki');
  busy(button, true);
  try {
    const result = await api('/api/wiki/build', { method: 'POST' });
    toast(`Wiki 已重建：${result.pages} 页`);
    $('#wikiFrame').src = `/wiki/?t=${Date.now()}`;
    await loadCore();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function patchAction(id, action, button) {
  busy(button, true);
  try {
    await api(`/api/patches/${id}/${action}`, { method: 'POST' });
    toast(action === 'apply' ? '补丁已应用' : '补丁已拒绝');
    await loadPatches();
    await loadCore();
    await loadFeed();
    if (action === 'apply') {
      $('#wikiFrame').src = `/wiki/?t=${Date.now()}`;
    }
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function addSource() {
  const group = state.sourceGroup;
  const adapter = $('#newSourceAdapter').value;
  const name = $('#newSourceName').value.trim();
  const query = $('#newSourceQuery').value.trim();
  const language = $('#newSourceLanguage').value.trim();
  const minStars = Number($('#newSourceStars').value || 0);
  let url = $('#newSourceUrl').value.trim();
  if (group === 'github') {
    if (adapter !== 'github_trending' && !query) {
      toast('GitHub 订阅需要查询词或 owner/repo', 'error');
      return;
    }
    if (adapter === 'github_search') {
      url = `https://github.com/search?q=${encodeURIComponent(query)}`;
    } else if (adapter === 'github_repo') {
      url = `https://github.com/${query}`;
    } else {
      url = 'https://github.com/trending';
    }
  }
  if (!url) {
    toast('先填一个来源地址', 'error');
    return;
  }
  const button = $('#addSource');
  busy(button, true);
  try {
    const result = await api('/api/sources', {
      method: 'POST',
      body: JSON.stringify({
        url,
        name,
        group,
        adapter,
        config: group === 'github'
          ? {
              query,
              language,
              min_stars: minStars,
            }
          : {},
      }),
    });
    $('#newSourceUrl').value = '';
    $('#newSourceName').value = '';
    $('#newSourceQuery').value = '';
    $('#newSourceLanguage').value = '';
    $('#newSourceStars').value = '';
    toast(`${SOURCE_ADAPTER_LABELS[adapter] || '来源'}已添加`);
    await loadCore();
    await loadSources();
    await sourceFetch(result.id, button);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function discoverSource() {
  const url = $('#newSourceUrl').value.trim();
  if (!url) {
    toast('先粘贴一个主页或 Feed 地址', 'error');
    return;
  }
  const button = $('#discoverSource');
  busy(button, true);
  try {
    const draft = await api('/api/sources/discover', {
      method: 'POST',
      body: JSON.stringify({ url, name: '', group: state.sourceGroup, adapter: 'rss' }),
    });
    state.sourceGroup = draft.group || 'other';
    renderSources();
    $('#newSourceAdapter').value = draft.adapter || 'rss';
    $('#newSourceUrl').value = draft.url || url;
    $('#newSourceName').value = draft.name || '';
    $('#newSourceQuery').value = draft.config?.query || '';
    $('#sourceAddHint').textContent = `已识别为 ${SOURCE_ADAPTER_LABELS[draft.adapter] || draft.adapter}`;
    $('#newSourceAdapter').dispatchEvent(new Event('change'));
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function sourceEdit(sourceId) {
  const source = state.sources.find(item => item.id === sourceId);
  if (!source) return;
  const config = { ...(source.config || {}) };
  if ((source.source_group || 'other') === 'github') {
    const query = prompt('查询词 / owner/repo', config.query || '');
    if (query === null) return;
    config.query = query.trim();
    if (config.query && (source.adapter === 'github_repo')) {
      config.query = config.query.replace(/^https?:\/\/github\.com\//, '');
    }
    const language = prompt('语言筛选（可选，例如 C++）', config.language || '');
    if (language === null) return;
    config.language = language.trim();
    const stars = prompt('最低 Star（可选）', String(config.min_stars || 0));
    if (stars === null) return;
    config.min_stars = Math.max(0, Number(stars) || 0);
  }
  const include = prompt(
    '必须包含的词（逗号分隔，留空不限）',
    (config.include_any || []).join(', '),
  );
  if (include === null) return;
  config.include_any = include.split(',').map(value => value.trim()).filter(Boolean);
  const exclude = prompt(
    '排除词（逗号分隔，命中即丢弃）',
    (config.exclude_any || []).join(', '),
  );
  if (exclude === null) return;
  config.exclude_any = exclude.split(',').map(value => value.trim()).filter(Boolean);
  const name = prompt('来源名称', source.name || '');
  if (name === null) return;
  try {
    await api(`/api/sources/${sourceId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name, config }),
    });
    toast('来源已更新');
    await loadSources();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function sourceFetch(sourceId, button) {
  busy(button, true);
  try {
    if (!(await saveSettings(true))) return;
    const result = await api(`/api/sources/${sourceId}/fetch`, { method: 'POST' });
    toast(`抓取 ${result.fetched || 0} 条，新增 ${result.new || 0} 条${result.filtered_out ? `，筛选掉 ${result.filtered_out} 条` : ''}`);
    await loadCore();
    await Promise.all([loadFeed(), loadSources(), loadPatches()]);
  } catch (error) {
    toast(error.message, 'error');
    await loadSources();
  } finally {
    busy(button, false);
  }
}

async function sourceDelete(sourceId) {
  if (!confirm('删除这个 RSS 源？已抓取的内容会保留。')) return;
  try {
    await api(`/api/sources/${sourceId}`, { method: 'DELETE' });
    toast('来源已删除');
    await loadCore();
    await loadSources();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderLearning() {
  $$('.rank-tab[data-learning-mode]').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.learningMode === state.learningMode);
  });
  const interview = state.learningMode === 'interview';
  const options = $('#interviewOptions');
  if (options) options.classList.toggle('hidden', !interview);
  const generate = $('#generateLearning');
  if (generate) generate.textContent = interview ? '生成面试题' : '生成知识文档';
  const output = $('#learningOutput');
  if (!output) return;
  const result = state.learningResult;
  if (!result) {
    output.classList.add('hidden');
    output.innerHTML = '';
    return;
  }
  output.classList.remove('hidden');
  const citations = (result.citations || []).map(citation => `
    <div class="citation">
      <span class="idx">[${citation.index}]</span>
      <div>${esc(citation.title)}<br><span>${esc(citation.path || citation.kind || '')}</span></div>
    </div>`).join('');
  const stats = result.stats ? `
    <div class="review-stats">
      <span>新增 ${result.stats.feed_total}</span>
      <span>收藏 ${result.stats.saved}</span>
      <span>笔记 ${result.stats.notes_total}</span>
      <span>平均匹配 ${Math.round((result.stats.avg_relevance || 0) * 100)}%</span>
    </div>` : '';
  const title = result.mode === 'review'
    ? `周期复盘 · ${result.days} 天`
    : result.mode === 'interview' ? `面试题 · ${result.topic}` : `知识文档 · ${result.topic}`;
  const saveCheck = result.mode === 'review' ? '' : renderSaveContext(result.save_context || {});
  output.innerHTML = `
    <div class="section-head">
      <div><h3>${esc(title)}</h3><p class="hint">由 DeepSeek 基于本地资料生成</p></div>
      <div class="toolbar-group">
        ${result.mode === 'review' ? '' : '<button class="btn primary" data-learning-save>保存为草稿补丁</button>'}
        <button class="btn ghost" data-learning-discard>不保存</button>
      </div>
    </div>
    ${stats}
    ${saveCheck}
    <div class="answer-text learning-markdown">${renderMarkdown(result.markdown || '')}</div>
    ${citations ? `<div class="citations"><h4>本地引用</h4>${citations}</div>` : ''}`;
}

function renderSaveContext(context) {
  const related = context.related || [];
  const duplicate = context.duplicate;
  const target = context.target_path ? `<span class="hint">目标：${esc(context.target_path)}</span>` : '';
  const items = related.map(item => `
    <div class="related-item">
      <div class="related-top">
        <strong>${esc(item.title)}</strong>
        <span class="similarity">相似 ${Math.round((item.similarity || 0) * 100)}%${item.coverage ? ` · 关键词 ${Math.round(item.coverage * 100)}%` : ''}</span>
      </div>
      <div class="hint">${esc(item.path)}${item.same_target ? ' · 同名草稿' : ''}</div>
      <p>${esc(item.excerpt || '')}</p>
      ${item.same_target ? '' : `<button class="btn ghost" data-append-path="${esc(item.path)}">追加到这篇</button>`}
    </div>`).join('');
  return `
    <div class="save-check">
      <div class="save-check-head">
        <strong>保存前检查</strong>
        ${target}
      </div>
      ${context.target_exists ? '<div class="save-warning">同名草稿已存在，保存时会自动改用新文件名，不会覆盖。</div>' : ''}
      ${duplicate ? `<div class="save-warning">本地已有高度相似笔记《${esc(duplicate.title)}》（${Math.round(duplicate.similarity * 100)}%），建议先对比或追加。</div>` : ''}
      ${related.length ? `<div class="related-list">${items}</div>` : '<p class="hint">本地没有明显相似内容，可以直接新建草稿。</p>'}
    </div>`;
}

async function appendLearningToNote(path) {
  const result = state.learningResult;
  if (!result) return;
  try {
    await api('/api/learning/append', {
      method: 'POST',
      body: JSON.stringify({
        path,
        topic: result.topic,
        markdown: result.markdown,
        citations: result.citations || [],
      }),
    });
    toast('已生成追加补丁，去“补丁”页应用');
    await loadPatches();
    setView('patches', false);
    history.replaceState(null, '', '#patches');
  } catch (error) {
    toast(error.message, 'error');
  }
}

function discardLearning() {
  state.learningResult = null;
  renderLearning();
}

async function generateLearning() {
  const topic = $('#learningTopic').value.trim();
  if (!topic) {
    toast('先填写一个学习主题', 'error');
    return;
  }
  const button = $('#generateLearning');
  busy(button, true);
  $('#learningHint').textContent = '生成中…';
  try {
    state.learningResult = await api('/api/learning/generate', {
      method: 'POST',
      body: JSON.stringify({
        topic,
        mode: state.learningMode,
        difficulty: $('#learningDifficulty').value,
        count: Number($('#learningCount').value || 5),
      }),
    });
    renderLearning();
    $('#learningHint').textContent = '';
  } catch (error) {
    toast(error.message, 'error');
    $('#learningHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function saveLearning() {
  const result = state.learningResult;
  if (!result || !result.markdown) return;
  try {
    const patch = await api('/api/learning/save', {
      method: 'POST',
      body: JSON.stringify({
        topic: result.mode === 'review' ? `复盘-${result.days}天` : result.topic,
        markdown: result.markdown,
        citations: result.citations || [],
      }),
    });
    toast('已加入补丁队列，去“补丁”页应用');
    await loadPatches();
    if (patch?.target_path) {
      setView('patches', false);
      history.replaceState(null, '', '#patches');
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function generateReview() {
  const button = $('#generateReview');
  const days = Number($('#reviewDays').value || 7);
  busy(button, true);
  $('#reviewStats').textContent = '生成中…';
  try {
    const result = await api('/api/review', {
      method: 'POST',
      body: JSON.stringify({ days }),
    });
    state.learningResult = { ...result, mode: 'review', days };
    renderLearning();
    $('#reviewStats').textContent = '';
  } catch (error) {
    toast(error.message, 'error');
    $('#reviewStats').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function loadReviewStats() {
  const days = Number($('#reviewDays')?.value || 7);
  try {
    const stats = await api(`/api/review/stats?days=${days}`);
    const hint = $('#reviewStats');
    if (hint) hint.textContent = `${stats.feed_total} 条资讯 · ${stats.saved} 收藏 · 平均匹配 ${Math.round((stats.avg_relevance || 0) * 100)}%`;
  } catch (error) {
    // Keep the review card usable even if stats fail.
  }
}

function loadGraph() {
  const svg = $('#graphSvg');
  if (!svg) return;
  svg.innerHTML = '<text x="450" y="280" text-anchor="middle" class="graph-muted">正在加载…</text>';
  api('/api/graph').then(graph => {
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    const stats = graph.stats || {};
    $('#graphStats').textContent = `${stats.notes || 0} 个节点 · ${stats.links || 0} 条关系 · ${stats.isolated || 0} 个孤立节点`;
    const select = $('#graphNote');
    const previous = select.value;
    select.innerHTML = nodes.map(node => `<option value="${esc(node.id)}">${esc(node.label)}</option>`).join('');
    if (nodes.some(node => node.id === previous)) select.value = previous;
    const width = 900;
    const height = 560;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(225, 130 + nodes.length * 5);
    const positions = {};
    nodes.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1) - Math.PI / 2;
      positions[node.id] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
    });
    const color = type => {
      if (type === 'source') return '#37618e';
      if (type === 'concept') return '#2f7d5b';
      if (type === 'technology') return '#b45309';
      if (type === 'draft') return '#8a6a3f';
      return '#716b60';
    };
    const lines = edges.map(edge => {
      const a = positions[edge.source];
      const b = positions[edge.target];
      if (!a || !b) return '';
      return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="graph-edge ${edge.kind}" />`;
    }).join('');
    const circles = nodes.map(node => {
      const position = positions[node.id];
      const size = 7 + Math.min(8, node.degree || 0);
      const label = node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label;
      return `<g class="graph-node">
        <title>${esc(node.label)} · ${esc(node.type)} · ${node.degree || 0} 条关系</title>
        <circle cx="${position.x}" cy="${position.y}" r="${size}" fill="${color(node.type)}" />
        <text x="${position.x}" y="${position.y + size + 13}" text-anchor="middle">${esc(label)}</text>
      </g>`;
    }).join('');
    svg.innerHTML = `${lines}${circles}`;
    $('#graphLegend').textContent = '蓝：来源 · 绿：概念 · 橙：技术 · 棕：草稿 · 灰：其他；连线来自 wikilink 或共同标签。';
  }).catch(error => {
    svg.innerHTML = `<text x="450" y="280" text-anchor="middle" class="graph-muted">${esc(error.message)}</text>`;
  });
}

async function suggestGraphLinks() {
  const path = $('#graphNote').value;
  if (!path) {
    toast('先选择一篇笔记', 'error');
    return;
  }
  const button = $('#suggestLinks');
  busy(button, true);
  $('#linkHint').textContent = '分析关联中…';
  try {
    const result = await api('/api/graph/suggest', {
      method: 'POST',
      body: JSON.stringify({ path, limit: 5 }),
    });
    if (result.patch) {
      $('#linkHint').textContent = `已生成 ${result.suggestions.length} 条关联建议，去“补丁”页应用`;
      toast('关联建议已加入补丁队列');
      await loadPatches();
    } else {
      $('#linkHint').textContent = '没有发现新的关联';
    }
  } catch (error) {
    toast(error.message, 'error');
    $('#linkHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function suggestAllGraphLinks() {
  const button = $('#suggestAllLinks');
  busy(button, true);
  $('#linkHint').textContent = '批量分析中…';
  try {
    const result = await api('/api/graph/suggest_all?max_notes=8', { method: 'POST' });
    $('#linkHint').textContent = `已为 ${result.notes} 篇笔记生成关联建议`;
    toast(result.patches ? `已生成 ${result.patches} 个关联补丁` : '没有新的关联建议');
    await loadPatches();
  } catch (error) {
    toast(error.message, 'error');
    $('#linkHint').textContent = error.message;
  } finally {
    busy(button, false);
  }
}

async function runSchedulerNow(button, replace = false) {
  busy(button, true);
  try {
    const saved = await saveSettings(true);
    if (!saved) return;
    const result = await api(`/api/scheduler/run${replace ? '?replace=true' : ''}`, { method: 'POST' });
    if (result.skipped) {
      toast(result.reason || '没有运行', 'error');
    } else {
      const rssCount = (result.rss || []).reduce((sum, item) => sum + (item.new || 0), 0);
      const githubCount = result.github?.new || 0;
      const targeted = result.targeted || {};
      const filtered = (result.rss || []).reduce((sum, item) => sum + (item.filtered_out || 0), 0)
        + (result.github?.filtered_out || 0)
        + (targeted.filtered_out || 0);
      const removed = result.removed || 0;
      toast(`采集完成：RSS 新增 ${rssCount} 条，GitHub 新增 ${githubCount} 个，画像定向新增 ${targeted.new || 0} 条${filtered ? `，筛选掉 ${filtered} 条` : ''}${removed ? `，清空旧资讯 ${removed} 条` : ''}`);
    }
    await refreshAll();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy(button, false);
  }
}

function bindEvents() {
  $$('.nav-item').forEach(button => {
    button.addEventListener('click', () => setView(button.dataset.view));
  });

  document.addEventListener('click', async event => {
    const actionEl = event.target.closest('[data-action]');
    if (!actionEl) return;
    const action = actionEl.dataset.action;
    if (action === 'go-settings') return setView('settings');
    if (action === 'go-feed' || action === 'go-feed-top') return setView('feed');
    if (action === 'clear-feed-filter') return clearFeedFilters();
    if (action === 'load-more-feed') return loadMoreFeed();
    if (action === 'seed-demo') return seedDemo();
    if (action === 'summarize' || action === 'translate' || action === 'save' || action === 'unsave' || action === 'dismiss') {
      const card = actionEl.closest('.card');
      return itemAction(card.dataset.id, action, actionEl);
    }
    if (action === 'apply-patch' || action === 'reject-patch') {
      const card = actionEl.closest('.card');
      return patchAction(card.dataset.id, action === 'apply-patch' ? 'apply' : 'reject', actionEl);
    }
  });

  $('#scoreAll').addEventListener('click', async () => {
    const button = $('#scoreAll');
    busy(button, true);
    try {
      const saved = await saveSettings(true);
      if (!saved) return;
      const status = await api('/api/feed/score_all', { method: 'POST' });
      toast(status.running ? `开始评估 ${status.total} 条资讯` : '没有待评估的资讯');
      await loadCore();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy(button, false);
    }
  });
  $('#learnProfile').addEventListener('click', learnProfile);
  $('#applyProfile').addEventListener('click', applyProfileSuggestions);
  $('#refreshGithubRanking').addEventListener('click', refreshGithubRanking);
  $('#learningModes').addEventListener('click', event => {
    const tab = event.target.closest('[data-learning-mode]');
    if (!tab) return;
    state.learningMode = tab.dataset.learningMode;
    state.learningResult = null;
    renderLearning();
  });
  $('#generateLearning').addEventListener('click', generateLearning);
  $('#generateReview').addEventListener('click', generateReview);
  $('#reviewDays').addEventListener('change', loadReviewStats);
  $('#refreshGraph').addEventListener('click', loadGraph);
  $('#suggestLinks').addEventListener('click', suggestGraphLinks);
  $('#suggestAllLinks').addEventListener('click', suggestAllGraphLinks);
  $('#learningOutput').addEventListener('click', event => {
    if (event.target.closest('[data-learning-save]')) {
      saveLearning();
      return;
    }
    if (event.target.closest('[data-learning-discard]')) {
      discardLearning();
      return;
    }
    const append = event.target.closest('[data-append-path]');
    if (append) appendLearningToNote(append.dataset.appendPath);
  });
  $$('.feed-tab').forEach(tab => {
    tab.addEventListener('click', () => switchFeedTab(tab.dataset.feedTab));
  });
  $$('.sort-tab').forEach(tab => {
    tab.addEventListener('click', async () => {
      state.feedSort = tab.dataset.feedSort;
      await loadFeed();
    });
  });
  $('#feedStatus').addEventListener('change', applyFeedFilters);
  $('#feedSourceList').addEventListener('click', async event => {
    const item = event.target.closest('[data-feed-source-id]');
    if (!item) return;
    state.feedSourceId = item.dataset.feedSourceId || '';
    await loadFeed();
  });
  $('#feedList').addEventListener('change', event => {
    const checkbox = event.target.closest('[data-select-feed]');
    if (!checkbox) return;
    if (checkbox.checked) state.feedSelected.add(checkbox.dataset.selectFeed);
    else state.feedSelected.delete(checkbox.dataset.selectFeed);
    checkbox.closest('.card')?.classList.toggle('selected', checkbox.checked);
    updateBulkUI();
  });
  $('#selectAllFeed').addEventListener('change', event => {
    const visible = state.feed.filter(item => item.source_type !== 'github');
    state.feedSelected.clear();
    if (event.target.checked) visible.forEach(item => state.feedSelected.add(item.id));
    renderFeed();
  });
  $('#bulkRead').addEventListener('click', () => bulkFeedStatus('read'));
  $('#bulkUnread').addEventListener('click', () => bulkFeedStatus('unread'));
  $('#bulkSave').addEventListener('click', () => bulkFeedStatus('saved'));
  $('#bulkDismiss').addEventListener('click', () => bulkFeedStatus('dismissed'));
  $('#bulkDelete').addEventListener('click', () => bulkFeedStatus('delete'));
  $('#githubRanking').addEventListener('click', async event => {
    const button = event.target.closest('[data-github-favorite]');
    if (!button) return;
    const card = button.closest('[data-rank-index]');
    const item = state.githubRanking?.items?.[Number(card?.dataset.rankIndex)];
    if (!item) return;
    busy(button, true);
    try {
      await api('/api/github/favorite', {
        method: 'POST',
        body: JSON.stringify({ item }),
      });
      toast('GitHub 项目已收藏');
      await loadCollections();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy(button, false);
    }
  });
  $('#githubStacks').addEventListener('click', async event => {
    const chip = event.target.closest('[data-stack]');
    if (!chip) return;
    state.githubStack = chip.dataset.stack;
    state.githubRanking = null;
    await loadGithubRanking();
  });
  $('#githubMetrics').addEventListener('click', async event => {
    const tab = event.target.closest('[data-metric]');
    if (!tab) return;
    state.githubMetric = tab.dataset.metric;
    state.githubRanking = null;
    await loadGithubRanking();
  });
  $('#saveSettings').addEventListener('click', () => saveSettings(false));
  $('#profileTechnical').addEventListener('change', () => {
    const selected = $$('[data-profile-language]:checked').map(input => input.value);
    renderProfileLanguages(selected);
  });
  $('#settingsTabs').addEventListener('click', event => {
    const tab = event.target.closest('[data-settings-tab]');
    if (!tab) return;
    state.settingsTab = tab.dataset.settingsTab;
    renderSettingsTab();
  });
  $('#scheduleModeTabs').addEventListener('click', event => {
    const tab = event.target.closest('[data-schedule-mode]');
    if (!tab) return;
    state.scheduleMode = tab.dataset.scheduleMode;
    renderScheduleMode();
  });
  $('#addCustomProvider').addEventListener('click', addCustomProvider);
  $('#addOfficialProvider').addEventListener('click', addOfficialProvider);
  $('#fetchOfficialModels').addEventListener('click', event => fetchModels(event.currentTarget));
  $('#fetchCustomModels').addEventListener('click', event => fetchModels(event.currentTarget));
  $('#configuredModelList').addEventListener('click', async event => {
    const fetchButton = event.target.closest('[data-fetch-model-list]');
    if (fetchButton) {
      fetchModels(fetchButton);
      return;
    }
    const saveButton = event.target.closest('[data-save-model]');
    if (!saveButton) return;
    busy(saveButton, true);
    try {
      if (await saveSettings(true)) toast('模型配置已保存');
    } finally {
      busy(saveButton, false);
    }
  });
  $('#toggleAddModel').addEventListener('click', () => {
    const panel = $('#addModelPanel');
    panel?.classList.toggle('hidden');
    if (panel && !panel.classList.contains('hidden')) renderAddModelPanel();
  });
  $('#addModelTabs').addEventListener('click', event => {
    const tab = event.target.closest('[data-add-kind]');
    if (!tab) return;
    state.addModelKind = tab.dataset.addKind;
    renderAddModelPanel();
  });
  $('#officialVendor').addEventListener('change', () => {
    $('#officialModel').value = OFFICIAL_MODEL_DEFAULTS[$('#officialVendor').value] || '';
  });
  $('#testProvider').addEventListener('click', async () => {
    const button = $('#testProvider');
    busy(button, true);
    try {
      const saved = await saveSettings(true);
      if (!saved) return;
      const active = $('input[name=activeProvider]:checked')?.value || 'deepseek';
      const result = await api('/api/providers/test', {
        method: 'POST',
        body: JSON.stringify({ provider: active }),
      });
      toast(`${providerLabel(active)} 连接成功：${result.reply || 'OK'}`);
      $('#settingsHint').textContent = `测试通过 · ${result.model}`;
    } catch (error) {
      toast(error.message, 'error');
      $('#settingsHint').textContent = error.message;
    } finally {
      await loadCore();
      busy(button, false);
    }
  });
  $('#askBtn').addEventListener('click', askQuestion);
  $('#testEmbedding').addEventListener('click', async () => {
    const button = $('#testEmbedding');
    busy(button, true);
    try {
      const saved = await saveSettings(true);
      if (!saved) return;
      const result = await api('/api/embeddings/test', { method: 'POST' });
      toast(`Embedding 连接成功：${result.model} · ${result.dimension} 维`);
      $('#embeddingHint').textContent = `${result.provider} · ${result.model} · ${result.dimension} 维`;
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy(button, false);
    }
  });
  $('#rebuildEmbedding').addEventListener('click', async () => {
    const button = $('#rebuildEmbedding');
    busy(button, true);
    try {
      const saved = await saveSettings(true);
      if (!saved) return;
      const result = await api('/api/embeddings/rebuild', { method: 'POST' });
      toast(`向量索引已重建：${result.indexed} 条 · ${result.model}`);
      await loadCore();
      renderSettings();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy(button, false);
    }
  });
  $('#incrementalEmbedding').addEventListener('click', async () => {
    const button = $('#incrementalEmbedding');
    busy(button, true);
    try {
      const saved = await saveSettings(true);
      if (!saved) return;
      const result = await api('/api/embeddings/incremental?max_docs=100', { method: 'POST' });
      toast(result.skipped ? '本地 n-gram 不需要补全索引' : `已开始补全：待索引 ${result.pending || 0} 条`);
      await loadCore();
      renderSettings();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy(button, false);
    }
  });
  $('#runScheduler').addEventListener('click', event => runSchedulerNow(event.currentTarget));
  $('#refreshAllFeeds').addEventListener('click', event => runSchedulerNow(event.currentTarget));
  $('#question').addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') askQuestion();
  });
  $('#buildWiki').addEventListener('click', buildWiki);
  $('#refreshPatches').addEventListener('click', loadPatches);
  $('#refreshCollections').addEventListener('click', loadCollections);
  $('#refreshUsage').addEventListener('click', () => loadUsage(true));
  $('#addUsageAccount').addEventListener('click', addUsageAccount);
  $('#loginUsageAccount').addEventListener('click', loginUsageAccount);
  $('#usageKind').addEventListener('change', () => {
    const deepseek = $('#usageKind').value === 'deepseek';
    $('#usageNewapiFields').classList.toggle('hidden', deepseek);
    $('#usageDeepseekFields').classList.toggle('hidden', !deepseek);
  });
  $('#usageAccounts').addEventListener('click', event => {
    const button = event.target.closest('[data-delete-usage]');
    if (button) deleteUsageAccount(button.dataset.deleteUsage);
  });
  $$('.collection-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      state.collectionTab = tab.dataset.collectionTab;
      renderCollections();
    });
  });
  $('#addSource').addEventListener('click', addSource);
  $('#discoverSource').addEventListener('click', discoverSource);
  $('#importCatalog').addEventListener('click', importCatalog);
  $('#newSourceAdapter').addEventListener('change', () => {
    const query = $('#newSourceQuery');
    const adapter = $('#newSourceAdapter').value;
    query.classList.toggle('hidden', state.sourceGroup !== 'github');
    query.placeholder = adapter === 'github_repo' ? 'owner/repo' : '查询词，例如 C++、Qt、compiler';
  });
  $('#sourceGroupTabs').addEventListener('click', event => {
    const tab = event.target.closest('[data-source-group]');
    if (!tab) return;
    state.sourceGroup = tab.dataset.sourceGroup;
    renderSources();
  });
  $('#sourceList').addEventListener('change', async event => {
    const toggle = event.target.closest('[data-source-toggle]');
    if (!toggle) return;
    const item = toggle.closest('.source-item');
    try {
      await api(`/api/sources/${item.dataset.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: toggle.checked }),
      });
      await loadCore();
      await loadSources();
    } catch (error) {
      toast(error.message, 'error');
      await loadSources();
    }
  });
  $('#sourceList').addEventListener('click', async event => {
    const item = event.target.closest('.source-item');
    if (!item) return;
    const fetchButton = event.target.closest('[data-source-fetch]');
    if (fetchButton) return sourceFetch(item.dataset.id, fetchButton);
    const editButton = event.target.closest('[data-source-edit]');
    if (editButton) return sourceEdit(item.dataset.id);
    const deleteButton = event.target.closest('[data-source-delete]');
    if (deleteButton) return sourceDelete(item.dataset.id);
  });

  $('#setupBanner').addEventListener('click', async event => {
    const action = event.target.closest('[data-setup]')?.dataset.setup;
    if (!action) return;
    if (action === 'test') {
      await testActiveProvider();
      return;
    }
    state.settingsTab = action === 'vault' ? 'collect' : 'model';
    setView('settings');
    renderSettingsTab();
  });
  $('#themeToggle').addEventListener('click', () => {
    const root = document.documentElement;
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    localStorage.setItem('pkm-theme', next);
  });
}

function initTheme() {
  const saved = localStorage.getItem('pkm-theme');
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.dataset.theme = saved;
  }
}

(async function init() {
  initTheme();
  bindEvents();
  const initial = location.hash.replace('#', '');
  setView(VIEW_META[initial] ? initial : 'dashboard', false);
  window.addEventListener('hashchange', () => {
    const view = location.hash.replace('#', '');
    if (VIEW_META[view]) setView(view, false);
  });
  await refreshAll();
  const params = new URLSearchParams(location.search);
  if (params.get('stack')) state.githubStack = params.get('stack');
  if (params.get('metric')) state.githubMetric = params.get('metric');
  if (params.get('tab') === 'github' || params.get('tab') === 'rss') {
    setView('feed', false);
    if (params.get('tab') === 'github') {
      await switchFeedTab('github');
    } else {
      state.feedTab = 'rss';
      renderFeed();
    }
  }
  const preset = params.get('q');
  if (preset) {
    setView('ask', false);
    $('#question').value = preset;
    await askQuestion();
  }
  setInterval(async () => {
    if (state.status?.feed_enrichment?.running || state.status?.feed_scoring?.running) {
      await loadCore();
      await loadFeed();
    }
  }, 5000);
})();
