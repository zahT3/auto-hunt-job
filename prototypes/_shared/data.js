// 合成数据：公司、岗位、事实全部虚构，只用于原型。字段名尽量贴近后端（triage、bucket、structure、rows、counts）。
// 时间固定在 2026-11-02，截图才稳定。
window.PROTO = (function () {
  const NOW = '2026-11-02T10:00:00+08:00';

  const directions = [
    { id: 'backend', name: '后端开发' },
    { id: 'ai-app', name: 'AI 应用开发' },
    { id: 'data-eng', name: '数据开发' },
  ];

  const sources = [
    { id: 'official', name: '公司官网', kind: '官网', enabled: true, last: { state: 'ok', at: '2026-11-02T09:12:00+08:00', found: 41, note: '' } },
    { id: 'moka', name: 'Moka', kind: '招聘系统', enabled: true, last: { state: 'login', at: '2026-11-02T09:13:00+08:00', found: 6, note: '列表可读；要看完整表单需要登录核验' } },
    { id: 'feishu', name: '飞书招聘', kind: '招聘系统', enabled: true, last: { state: 'ok', at: '2026-11-02T09:13:00+08:00', found: 17, note: '' } },
    { id: 'beisen', name: '北森', kind: '招聘系统', enabled: true, last: { state: 'failed', at: '2026-11-02T09:14:00+08:00', found: 0, note: '返回 429，访问太频繁；30 分钟后再试' } },
    { id: 'greenhouse', name: 'Greenhouse', kind: '海外招聘系统', enabled: true, last: { state: 'ok', at: '2026-11-02T09:14:00+08:00', found: 9, note: '' } },
    { id: 'lever', name: 'Lever', kind: '海外招聘系统', enabled: false, last: { state: 'never', at: null, found: 0, note: '' } },
    { id: 'sitemap', name: '官网站点地图', kind: '官网', enabled: true, last: { state: 'ok', at: '2026-11-02T09:15:00+08:00', found: 12, note: '只能看到地址，在招状态要再确认' } },
  ];

  // 事实来自"已确认的简历"。confirmed=false 的是待确认。
  const facts = [
    { id: 'F1', text: '2022 年 7 月至今，在合成支付公司做 Go 服务端开发，共 4 年 4 个月', confirmed: true, where: '简历第 1 页 工作经历' },
    { id: 'F2', text: '负责对账服务重构，从 PHP 迁到 Go，接口 P99 从 820ms 降到 140ms', confirmed: true, where: '简历第 1 页 项目' },
    { id: 'F3', text: '对账服务日处理约 1200 万笔交易，使用 MySQL 分库、Kafka、Redis', confirmed: true, where: '简历第 1 页 项目' },
    { id: 'F4', text: '本科，计算机科学与技术，2022 年毕业', confirmed: true, where: '简历第 2 页 教育' },
    { id: 'F5', text: '用 gRPC 拆分出 3 个内部服务，写过服务间的超时和重试规范', confirmed: true, where: '简历第 1 页 项目' },
    { id: 'F6', text: '业余做过一个用 LLM 汇总工单的内部小工具（Python）', confirmed: true, where: '简历第 2 页 其他' },
    { id: 'F7', text: '2021 年在合成电商公司实习 3 个月，做数据报表', confirmed: false, where: '简历第 2 页 实习' },
    { id: 'F8', text: '持有软考中级证书', confirmed: false, where: '简历第 2 页 证书' },
  ];

  // sighting.state：verified 已核验在招 / listed 列表里出现、未逐条核验 / failed 抓取失败 / gone 来源里已找不到 / unknown 来源没给状态
  // fresh：new 新发布 / week 本周 / open 仍在招 / stale 可能已下线 / unconfirmed 在招待确认 / unknown 不知道发布时间
  const jobs = [
    {
      id: 'j1', title: 'Go 后端工程师（支付清结算）', company: '澄湖科技', city: '上海', area: '徐汇', direction: 'backend',
      salary: '30–45K·15 薪', years: '3–5 年', fresh: 'new', posted: '2026-10-31', triage: null,
      digest: '清结算核心链路，Go + MySQL + Kafka，要做对账和资金差错处理。',
      sightings: [
        { source: 'official', state: 'verified', first: '2026-10-31', checked: '2026-11-02', note: '' },
        { source: 'moka', state: 'listed', first: '2026-10-31', checked: '2026-11-02', note: '完整表单需要登录核验' },
        { source: 'sitemap', state: 'listed', first: '2026-11-01', checked: '2026-11-02', note: '' },
      ],
      detailed: true,
    },
    {
      id: 'j2', title: '大模型应用后端工程师', company: '零点九智能', city: '杭州', area: '余杭', direction: 'ai-app',
      salary: '35–55K', years: '3 年以上', fresh: 'new', posted: '2026-11-01', triage: null,
      digest: '给 RAG 检索和 Agent 编排写服务端，Python / Go 均可，要求有线上 LLM 项目。',
      sightings: [
        { source: 'feishu', state: 'verified', first: '2026-11-01', checked: '2026-11-02', note: '' },
        { source: 'official', state: 'listed', first: '2026-11-01', checked: '2026-11-02', note: '' },
      ],
    },
    {
      id: 'j3', title: '高级后端开发（交易中台）', company: '北岸数据', city: '上海', area: '浦东', direction: 'backend',
      salary: '40–60K·14 薪', years: '5–10 年', fresh: 'open', posted: '2026-09-18', triage: 'later',
      digest: '交易中台订单与库存服务，Java 为主，可接受 Go 背景转 Java。',
      sightings: [
        { source: 'official', state: 'verified', first: '2026-09-18', checked: '2026-11-02', note: '45 天前发布，今天官网仍在招' },
        { source: 'beisen', state: 'failed', first: '2026-09-20', checked: '2026-11-02', note: '返回 429，没拿到最新状态' },
      ],
    },
    {
      id: 'j4', title: '数据开发工程师（实时数仓）', company: '青柚出行', city: '杭州', area: '滨江', direction: 'data-eng',
      salary: '25–40K', years: '3–5 年', fresh: 'week', posted: '2026-10-28', triage: null,
      digest: 'Flink 实时数仓与指标平台，需要 Kafka 和 SQL 调优经验。',
      sightings: [
        { source: 'feishu', state: 'verified', first: '2026-10-28', checked: '2026-11-02', note: '' },
      ],
    },
    {
      id: 'j5', title: '后端工程师（风控引擎）', company: '澄湖科技', city: '上海', area: '徐汇', direction: 'backend',
      salary: '30–50K·15 薪', years: '3 年以上', fresh: 'stale', posted: '2026-09-02', triage: null,
      digest: '规则引擎与特征服务，Go 优先，有风控经验加分。',
      sightings: [
        { source: 'official', state: 'gone', first: '2026-09-02', checked: '2026-11-02', note: '官网列表 16 天没出现这条' },
        { source: 'moka', state: 'listed', first: '2026-09-03', checked: '2026-10-17', note: '最近一次见到是 10-17' },
      ],
    },
    {
      id: 'j6', title: 'Backend Engineer, Payments', company: 'Tidewater Labs（合成）', city: '远程', area: '亚太时区', direction: 'backend',
      salary: '未写', years: '4+ 年', fresh: 'week', posted: '2026-10-27', triage: 'interested',
      digest: '海外支付团队，英文工作环境，Go / PostgreSQL，需要和新加坡时区重叠 4 小时。',
      sightings: [
        { source: 'greenhouse', state: 'verified', first: '2026-10-27', checked: '2026-11-02', note: '' },
      ],
    },
    {
      id: 'j7', title: 'AI 应用开发工程师', company: '南枝网络', city: '上海', area: '闵行', direction: 'ai-app',
      salary: '28–42K', years: '2–5 年', fresh: 'unconfirmed', posted: null, triage: null,
      digest: '站点地图里有这条地址，打开后只有标题和地点。',
      sightings: [
        { source: 'sitemap', state: 'unknown', first: '2026-11-01', checked: '2026-11-02', note: '只在站点地图出现，官网列表里找不到' },
      ],
    },
    {
      id: 'j8', title: '服务端开发工程师（基础架构）', company: '白塔云', city: '杭州', area: '西湖', direction: 'backend',
      salary: '30–45K', years: '3–5 年', fresh: 'unknown', posted: null, triage: null,
      digest: '服务治理和 RPC 框架，Go / C++，参与 Service Mesh 落地。',
      sightings: [
        { source: 'moka', state: 'listed', first: '2026-10-30', checked: '2026-11-02', note: '来源没有发布日期' },
      ],
    },
    {
      id: 'j9', title: '后端开发（跨境结算）', company: '北岸数据', city: '上海', area: '浦东', direction: 'backend',
      salary: '35–50K·14 薪', years: '3–5 年', fresh: 'new', posted: '2026-11-02', triage: null,
      digest: '多币种清算与汇率服务，要熟悉对账和资金流，英语读写。',
      sightings: [
        { source: 'official', state: 'verified', first: '2026-11-02', checked: '2026-11-02', note: '' },
        { source: 'beisen', state: 'failed', first: null, checked: '2026-11-02', note: '返回 429' },
      ],
    },
    {
      id: 'j10', title: 'LLM 平台工程师', company: '零点九智能', city: '杭州', area: '余杭', direction: 'ai-app',
      salary: '40–65K', years: '3 年以上', fresh: 'open', posted: '2026-10-09', triage: 'skipped',
      digest: '训练与推理平台，要求 K8s 和 GPU 调度经验。',
      sightings: [
        { source: 'feishu', state: 'verified', first: '2026-10-09', checked: '2026-11-01', note: '' },
      ],
    },
    {
      id: 'j11', title: '数据平台后端工程师', company: '青柚出行', city: '杭州', area: '滨江', direction: 'data-eng',
      salary: '28–40K', years: '3–5 年', fresh: 'week', posted: '2026-10-29', triage: null,
      digest: '数据服务化与查询网关，Go / Java 均可。',
      sightings: [
        { source: 'feishu', state: 'verified', first: '2026-10-29', checked: '2026-11-02', note: '' },
        { source: 'official', state: 'verified', first: '2026-10-29', checked: '2026-11-02', note: '' },
      ],
    },
    {
      id: 'j12', title: 'Go 开发工程师（营销中台）', company: '栖木零售', city: '上海', area: '长宁', direction: 'backend',
      salary: '25–35K', years: '2–4 年', fresh: 'week', posted: '2026-10-27', triage: 'later',
      digest: '优惠券与活动配置服务，日活高峰时要扛住大促流量。',
      sightings: [
        { source: 'official', state: 'verified', first: '2026-10-27', checked: '2026-11-02', note: '' },
      ],
    },
  ];

  // j1 的完整 JD、结构化结果和匹配解释。evidence 必须是 jd 原文里的片段，界面靠它高亮。
  const jd = {
    j1: [
      { h: '岗位职责', p: [
        '负责支付清结算核心链路的设计与开发，包括对账、轧差、资金差错处理。',
        '参与分布式事务方案落地，保证资金流水在高并发下的一致性。',
        '与风控、财务团队协作，按监管要求输出清算报表。',
      ] },
      { h: '任职要求', p: [
        '本科及以上学历，计算机相关专业，3–5 年后端开发经验。',
        '熟练使用 Go，熟悉 MySQL、Redis、Kafka，有 gRPC 服务拆分经验。',
        '熟悉 Kubernetes，能独立排查线上容器问题。',
        '有支付、清结算或风控系统经验者优先。',
        '良好的沟通能力，能读写英文技术文档。',
      ] },
      { h: '工作地点', p: ['上海市徐汇区，每周可远程 1 天。'] },
    ],
  };

  const structure = {
    j1: {
      by: 'ai', digest: '清结算核心链路，Go 为主，要对账与资金差错经验。',
      years: { value: { min: 3, max: 5 }, evidence: '3–5 年后端开发经验' },
      education: { value: '本科', evidence: '本科及以上学历' },
      remote: { value: false, evidence: '每周可远程 1 天' },
      hard_skills: [
        { value: 'Go', evidence: '熟练使用 Go' },
        { value: 'MySQL', evidence: 'MySQL' },
        { value: 'Redis', evidence: 'Redis' },
        { value: 'Kafka', evidence: 'Kafka' },
        { value: 'gRPC', evidence: 'gRPC 服务拆分经验' },
        { value: 'Kubernetes', evidence: '熟悉 Kubernetes' },
      ],
      soft_skills: [
        { value: '沟通', evidence: '良好的沟通能力' },
        { value: '英文读写', evidence: '能读写英文技术文档' },
      ],
      bonus: [
        { value: '支付 / 清结算', evidence: '有支付、清结算或风控系统经验者优先' },
        { value: '风控', evidence: '风控系统经验' },
      ],
      location: [{ value: '上海 徐汇', evidence: '上海市徐汇区' }],
    },
  };

  // 招聘方 ATS 的顺序：先筛硬条件，再看关键词覆盖，最后才读事实证据。
  const match = {
    j1: {
      by: 'ai', model: 'deepseek-chat（合成）',
      hard: [
        { requirement: '3–5 年后端经验', status: 'matched', evidence: '3–5 年后端开发经验', fact_ids: ['F1'], why: '4 年 4 个月 Go 服务端，在区间内' },
        { requirement: '本科及以上，计算机相关', status: 'matched', evidence: '本科及以上学历', fact_ids: ['F4'], why: '计算机科学与技术本科' },
        { requirement: '上海徐汇，每周远程 1 天', status: 'matched', evidence: '上海市徐汇区', fact_ids: [], why: '在你选的城市里' },
        { requirement: '能读写英文技术文档', status: 'unknown', evidence: '能读写英文技术文档', fact_ids: [], why: '简历里没有能证明英文水平的事实。不是不符合，是不知道' },
      ],
      keywords: [
        { k: 'Go', status: 'matched', fact_ids: ['F1', 'F2'] },
        { k: 'MySQL', status: 'matched', fact_ids: ['F3'] },
        { k: 'Redis', status: 'matched', fact_ids: ['F3'] },
        { k: 'Kafka', status: 'matched', fact_ids: ['F3'] },
        { k: 'gRPC', status: 'matched', fact_ids: ['F5'] },
        { k: '对账', status: 'matched', fact_ids: ['F2', 'F3'] },
        { k: '清结算', status: 'unknown', fact_ids: [], why: '简历写的是"对账"，意思相近，但 ATS 按字面匹配时可能不算' },
        { k: '分布式事务', status: 'unknown', fact_ids: [], why: '没有直接写到；F3 的分库场景可能涉及，要你确认' },
        { k: 'Kubernetes', status: 'missing', fact_ids: [], why: '事实里没有容器或 K8s 经历' },
        { k: '风控', status: 'missing', fact_ids: [], why: '加分项，事实里没有' },
      ],
      evidence: [
        { requirement: '支付清结算核心链路开发', status: 'matched', evidence: '负责支付清结算核心链路的设计与开发', fact_ids: ['F2', 'F3'], why: '对账服务重构，日处理约 1200 万笔，直接对口' },
        { requirement: '高并发下资金流水一致性', status: 'matched', evidence: '保证资金流水在高并发下的一致性', fact_ids: ['F3'], why: '分库 + Kafka 的对账链路，量级接近' },
        { requirement: 'gRPC 服务拆分', status: 'matched', evidence: 'gRPC 服务拆分经验', fact_ids: ['F5'], why: '拆过 3 个内部服务，写过超时和重试规范' },
        { requirement: '独立排查线上容器问题', status: 'missing', evidence: '能独立排查线上容器问题', fact_ids: [], why: '没有相关事实。面试前可以准备一个 K8s 排障的小例子' },
        { requirement: '良好的沟通能力', status: 'unknown', evidence: '良好的沟通能力', fact_ids: [], why: '软技能没法用简历事实证明，不计入' },
      ],
      notice: '匹配解释只引用已确认的事实。F7、F8 还没确认，没有使用。',
    },
  };

  const orient = {
    by: 'ai', model: 'deepseek-chat（合成）', updated: '2026-11-02T09:40:00+08:00',
    answered: [
      { q: '想找哪些行业的工作？', a: '技术研发、数据与算法' },
      { q: '想在哪些城市工作？', a: '上海、杭州' },
      { q: '多少年相关经验？', a: '3–5 年' },
      { q: '是否接受远程？', a: '可以接受混合办公' },
      { q: '要排除的行业', a: '博彩、催收' },
      { q: '是否考虑转方向？', a: '可以考虑相近方向' },
    ],
    followups: [
      { id: 'f1', q: '对账服务重构，你是负责人，还是核心参与者？', why: '决定后端方向的优势里能不能写"主导"。', options: ['负责人', '核心参与', '参与其中一部分'], answer: null },
      { id: 'f2', q: 'LLM 工单汇总工具有没有能公开的代码或演示？', why: 'AI 应用开发方向目前只有 F6 一条事实支撑。', options: ['有，可以给链接', '有，但不能公开', '没有'], answer: null },
    ],
    suggested: [
      {
        id: 'backend', name: '后端开发：支付与清结算', fit: '首选',
        why: '4 年 Go 服务端都在支付公司，对账链路是最硬的一段经历。上海、杭州这类岗位本周新增 9 个。',
        strengths: [{ t: '对账服务日处理约 1200 万笔', f: 'F3' }, { t: '重构后 P99 从 820ms 降到 140ms', f: 'F2' }, { t: 'gRPC 服务拆分和超时规范', f: 'F5' }],
        gaps: [{ t: '没有 Kubernetes 或容器经历' }, { t: '没有风控系统经历，部分岗位列为加分项' }],
        risks: [{ t: '交易中台类岗位多以 Java 为主，Go 背景要准备转语言的说法' }],
        terms: [{ t: 'Go 后端', on: true }, { t: '支付 后端', on: true }, { t: '清结算', on: true }, { t: '对账 开发', on: true }, { t: '交易系统', on: false, why: '本轮不搜：合并后只保留 8 个词' }],
      },
      {
        id: 'ai-app', name: 'AI 应用开发（偏后端）', fit: '可以试',
        why: '后端功底能直接用在 RAG 和 Agent 服务上，但 LLM 经历只有一条业余项目。',
        strengths: [{ t: '做过 LLM 工单汇总工具', f: 'F6' }, { t: '有生产级服务端经验', f: 'F1' }],
        gaps: [{ t: '没有线上 LLM 项目，很多 JD 明确要求' }, { t: '没有向量检索、评测相关事实' }],
        risks: [{ t: '这个方向岗位标题很杂，"AI 应用"里混着前端和产品岗，结果噪音会大' }],
        terms: [{ t: '大模型 应用 后端', on: true }, { t: 'RAG 工程师', on: true }, { t: 'Agent 开发', on: false, why: '本轮不搜：合并后只保留 8 个词' }],
      },
      {
        id: 'data-eng', name: '数据开发（实时链路）', fit: '备选',
        why: 'Kafka 和 MySQL 分库经验能迁移，但没写过 Flink 或数仓。',
        strengths: [{ t: 'Kafka 消费链路', f: 'F3' }],
        gaps: [{ t: '没有 Flink、Spark 或数仓建模经历' }],
        risks: [{ t: '实习的数据报表经历（F7）还没确认，不能算进来' }],
        terms: [{ t: '实时数仓', on: true }, { t: '数据平台 后端', on: true }],
      },
    ],
    not_now: [
      { name: '算法工程师 / 研究员', why: '没有模型训练或论文相关事实；这类 JD 大多要求硕士以上。' },
      { name: '前端开发', why: '简历里没有前端项目。你选了"技术研发"，但事实撑不起这个方向。' },
    ],
    today: [
      { t: '确认 2 条待确认事实', detail: 'F7 实习经历、F8 软考证书。确认后数据开发方向能多一条依据。', done: false },
      { t: '回答 2 个追问', detail: '大约 1 分钟，会改写后端和 AI 应用两个方向的优势。', done: false },
      { t: '用这组词跑一轮搜索', detail: '上海、杭州，8 个词，只读搜索，不会投递。', done: false },
      { t: '分拣今天的新岗位', detail: '待选里有 9 个，按 1、2、3 分到 感兴趣、稍后、跳过。', done: false },
    ],
  };

  const ai = {
    host: 'api.deepseek.com', model: 'deepseek-chat', key_hint: '尾号 3f9c', key_saved: true,
    budget: { month: 20, spent: 3.42 },
    consent: { granted_at: '2026-10-30T21:14:00+08:00', host: 'api.deepseek.com', model: 'deepseek-chat',
      kinds: { resume_redacted: true, resume_full: false, job_text: true, search_query: false } },
    kinds: [
      { id: 'resume_redacted', name: '脱敏简历', note: '姓名、电话、邮箱、住址替换成占位符后发送' },
      { id: 'resume_full', name: '完整简历', note: '不脱敏，姓名和联系方式会原样发送' },
      { id: 'job_text', name: '岗位原文', note: '用于 JD 结构化和匹配解释' },
      { id: 'search_query', name: '搜索需求', note: '你用一句话描述想找的岗位时，发送这句话' },
    ],
  };

  const run = { state: 'done', at: '2026-11-02T09:15:00+08:00', found: 85, merged: 12, failed: ['beisen'], login: ['moka'] };

  return { NOW, synthetic: true, directions, sources, facts, jobs, jd, structure, match, orient, ai, run,
    query: { q: '', city: ['上海', '杭州'], direction: ['backend', 'ai-app'], source: 'all', fresh: 7 } };
})();
