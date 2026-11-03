// 合并原型的合成数据。公司、岗位、事实都是虚构的。
// 结构照抄后端（docs/agent-mode.md）：search 的分组、job_match 的 hard / keywords / evidence、state.orientation。
// 时间是 UTC；界面按 Asia/Shanghai 显示。"现在"固定为 2026-11-02 10:00（北京时间），截图才稳定。
window.DATA = (function () {
  const NOW = '2026-11-02T02:00:00+00:00';

  // 渠道名（search 里的 source 字段）到中文名。
  const SOURCE_NAMES = { website: '公司官网', moka: 'Moka', feishu: '飞书招聘', beisen: '北森', liepin: '猎聘', greenhouse: 'Greenhouse', lever: 'Lever' };

  const directionTable = [
    { id: 'backend', name: '后端开发', family: '技术研发' },
    { id: 'ai-application-dev', name: 'AI 应用开发', family: '技术研发' },
    { id: 'data-engineer', name: '数据开发 / 数据工程师', family: '数据与算法' },
  ];

  // 已确认事实（candidate.facts 里 status=confirmed 且有 source.reference 的）。
  const facts = [
    { id: 'f1', status: 'confirmed', version: 1, text: '2022 年 7 月至今，在合成支付公司做 Go 服务端开发，共 4 年 4 个月', source: { kind: 'resume', reference: '简历第 1 页 工作经历' } },
    { id: 'f2', status: 'confirmed', version: 1, text: '负责对账服务重构，从 PHP 迁到 Go，接口 P99 从 820ms 降到 140ms', source: { kind: 'resume', reference: '简历第 1 页 项目' } },
    { id: 'f3', status: 'confirmed', version: 1, text: '对账服务日处理约 1200 万笔交易，使用 MySQL 分库、Kafka、Redis', source: { kind: 'resume', reference: '简历第 1 页 项目' } },
    { id: 'f4', status: 'confirmed', version: 1, text: '本科，计算机科学与技术，2022 年毕业', source: { kind: 'resume', reference: '简历第 2 页 教育' } },
    { id: 'f5', status: 'confirmed', version: 1, text: '用 gRPC 拆分出 3 个内部服务，写过服务间的超时和重试规范', source: { kind: 'resume', reference: '简历第 1 页 项目' } },
    { id: 'f6', status: 'confirmed', version: 1, text: '业余做过一个用 LLM 汇总工单的内部小工具（Python）', source: { kind: 'resume', reference: '简历第 2 页 其他' } },
    { id: 'f7', status: 'unconfirmed', version: 1, text: '2021 年在合成电商公司实习 3 个月，做数据报表', source: { kind: 'resume', reference: '简历第 2 页 实习' } },
    { id: 'f8', status: 'unconfirmed', version: 1, text: '英语六级 520 分', source: { kind: 'resume', reference: '简历第 2 页 证书' } },
  ];

  const src = (o) => Object.assign({ matched: true, status: 'open', salary: null, url: 'https://jobs.example.invalid/' + o.job_id, application_url: null }, o);

  // GET /api/search 不带条件时会返回的全部分组（这里一次性给出，前端按接口规则过滤）。
  // posted_at 不是现在接口里的字段：只有来源自己写了发布日期时才会有，界面要标明出处。原型里先预留。
  const groups = [
    { group: 'g01', title: 'Go 后端工程师（支付清结算）', company: '澄湖科技', city: '上海', status: 'open', direction: 'backend',
      first_seen: '2026-10-31T03:10:00+00:00', last_seen: '2026-11-02T01:20:00+00:00',
      sources: [
        src({ job_id: 'j01', source: 'website', source_id: 'website:careers.chenghu.example', platform_id: 'CH-2231', first_seen: '2026-10-31T03:10:00+00:00', last_seen: '2026-11-02T01:20:00+00:00', direction: 'backend', salary: '30–45K·15 薪', location: '上海·徐汇' }),
        src({ job_id: 'j02', source: 'moka', source_id: 'moka:app.mokahr.com/chenghu', platform_id: '88412', first_seen: '2026-10-31T03:14:00+00:00', last_seen: '2026-11-02T01:13:00+00:00', direction: 'backend', salary: null, location: '上海' }),
        src({ job_id: 'j03', source: 'liepin', source_id: 'liepin', platform_id: '5520193', first_seen: '2026-11-01T02:40:00+00:00', last_seen: '2026-11-01T02:40:00+00:00', direction: 'backend', salary: '30–45K', location: '上海-徐汇区' }),
      ] },
    { group: 'g02', title: '大模型应用后端工程师', company: '零点九智能', city: '杭州', status: 'open', direction: 'ai-application-dev',
      first_seen: '2026-11-01T06:20:00+00:00', last_seen: '2026-11-02T01:13:00+00:00',
      sources: [
        src({ job_id: 'j04', source: 'feishu', source_id: 'feishu:jobs.lingdian9.example', platform_id: '7301', first_seen: '2026-11-01T06:20:00+00:00', last_seen: '2026-11-02T01:13:00+00:00', direction: 'ai-application-dev', salary: '35–55K', location: '杭州·余杭' }),
        src({ job_id: 'j05', source: 'website', source_id: 'website:lingdian9.example', platform_id: 'LD-17', first_seen: '2026-11-01T06:25:00+00:00', last_seen: '2026-11-02T01:14:00+00:00', direction: 'ai-application-dev', location: '杭州' }),
      ] },
    { group: 'g03', title: '高级后端开发（交易中台）', company: '北岸数据', city: '上海', status: 'open', direction: 'backend',
      first_seen: '2026-09-18T02:00:00+00:00', last_seen: '2026-11-02T01:15:00+00:00',
      sources: [
        src({ job_id: 'j06', source: 'website', source_id: 'website:beian.example', platform_id: 'BA-301', first_seen: '2026-09-18T02:00:00+00:00', last_seen: '2026-11-02T01:15:00+00:00', direction: 'backend', salary: '40–60K·14 薪', location: '上海·浦东' }),
        src({ job_id: 'j07', source: 'beisen', source_id: 'beisen:beian.zhiye.example', platform_id: '9910', status: 'closed', first_seen: '2026-09-20T02:00:00+00:00', last_seen: '2026-10-24T02:00:00+00:00', direction: 'backend', location: '上海' }),
      ] },
    { group: 'g04', title: 'Backend Engineer, Payments', company: 'Tidewater Labs（合成）', city: '远程', status: 'open', direction: 'backend',
      first_seen: '2026-10-28T08:00:00+00:00', last_seen: '2026-11-02T01:16:00+00:00',
      sources: [
        src({ job_id: 'j08', source: 'greenhouse', source_id: 'greenhouse:tidewater', platform_id: '4410023', first_seen: '2026-10-28T08:00:00+00:00', last_seen: '2026-11-02T01:16:00+00:00', direction: 'backend', location: 'Remote (APAC)', posted_at: '2026-10-27' }),
      ] },
    { group: 'g05', title: '数据开发工程师（实时数仓）', company: '青柚出行', city: '杭州', status: 'open', direction: 'data-engineer',
      first_seen: '2026-10-28T03:00:00+00:00', last_seen: '2026-11-02T01:17:00+00:00',
      sources: [
        src({ job_id: 'j09', source: 'feishu', source_id: 'feishu:qingyou.example', platform_id: '5521', first_seen: '2026-10-28T03:00:00+00:00', last_seen: '2026-11-02T01:17:00+00:00', direction: 'data-engineer', salary: '25–40K', location: '杭州·滨江' }),
      ] },
    { group: 'g06', title: 'Go 开发工程师（营销中台）', company: '栖木零售', city: '上海', status: 'open', direction: 'backend',
      first_seen: '2026-10-27T05:00:00+00:00', last_seen: '2026-10-30T05:00:00+00:00',
      sources: [
        src({ job_id: 'j10', source: 'website', source_id: 'website:qimu.example', platform_id: 'QM-88', first_seen: '2026-10-27T05:00:00+00:00', last_seen: '2026-10-30T05:00:00+00:00', direction: 'backend', salary: '25–35K', location: '上海·长宁' }),
      ] },
    { group: 'g07', title: '服务端开发工程师（基础架构）', company: '白塔云', city: '杭州', status: 'open', direction: 'backend',
      first_seen: '2026-10-30T02:00:00+00:00', last_seen: '2026-11-02T01:18:00+00:00',
      sources: [
        src({ job_id: 'j11', source: 'moka', source_id: 'moka:app.mokahr.com/baita', platform_id: '77120', first_seen: '2026-10-30T02:00:00+00:00', last_seen: '2026-11-02T01:18:00+00:00', direction: 'backend', salary: '30–45K', location: '杭州·西湖' }),
      ] },
    { group: 'g08', title: '后端工程师（风控引擎）', company: '澄湖科技', city: '上海', status: 'closed', direction: 'backend',
      first_seen: '2026-09-02T02:00:00+00:00', last_seen: '2026-10-17T02:00:00+00:00',
      sources: [
        src({ job_id: 'j12', source: 'website', source_id: 'website:careers.chenghu.example', platform_id: 'CH-1980', status: 'closed', first_seen: '2026-09-02T02:00:00+00:00', last_seen: '2026-10-17T02:00:00+00:00', direction: 'backend', salary: '30–50K·15 薪', location: '上海·徐汇' }),
      ] },
    { group: 'g09', title: 'LLM 平台工程师', company: '零点九智能', city: '杭州', status: 'closed', direction: 'ai-application-dev',
      first_seen: '2026-10-09T02:00:00+00:00', last_seen: '2026-10-25T02:00:00+00:00',
      sources: [
        src({ job_id: 'j13', source: 'feishu', source_id: 'feishu:jobs.lingdian9.example', platform_id: '6620', status: 'closed', first_seen: '2026-10-09T02:00:00+00:00', last_seen: '2026-10-25T02:00:00+00:00', direction: 'ai-application-dev', salary: '40–65K', location: '杭州·余杭' }),
      ] },
  ];

  // 岗位记录（state 里每个 job 的一部分字段）。分组里的第一条记录代表这一组；triage 是卡片选择。
  const jobText = {
    j01: '岗位职责\n负责支付清结算核心链路的设计与开发，包括对账、轧差、资金差错处理。\n参与分布式事务方案落地，保证资金流水在高并发下的一致性。\n与风控、财务团队协作，按监管要求输出清算报表。\n任职要求\n本科及以上学历，计算机相关专业，3–5 年后端开发经验。\n熟练使用 Go，熟悉 MySQL、Redis、Kafka，有 gRPC 服务拆分经验。\n熟悉 Kubernetes，能独立排查线上容器问题。\n有支付、清结算或风控系统经验者优先。\n良好的沟通能力，英语六级，能读写英文技术文档。\n工作地点\n上海市徐汇区，每周可远程 1 天。',
    j04: '岗位职责\n给 RAG 检索和 Agent 编排写服务端，负责召回、重排和工具调用链路。\n任职要求\n3 年以上服务端经验，Python 或 Go。\n有线上 LLM 项目经验，熟悉向量检索。\n工作地点\n杭州余杭。',
    j06: '岗位职责\n交易中台订单与库存服务。\n任职要求\n5 年以上 Java 后端经验，可接受 Go 背景转 Java。\n工作地点\n上海浦东。',
  };
  const jobs = {};
  groups.forEach((g) => g.sources.forEach((s, i) => {
    jobs[s.job_id] = { id: s.job_id, group: g.group, title: g.title, company: g.company, location: s.location, salary: s.salary,
      jd: jobText[s.job_id] || null, status: s.status, first_seen: s.first_seen, last_seen: s.last_seen,
      triage: i === 0 ? ({ g03: 'later', g04: 'interested', g06: 'later', g09: 'skipped' }[g.group] || null) : null };
  }));

  // POST /api/action {"action":"job_match","job_id":"j01"} 的 result。
  const match = {
    j01: {
      schema_version: 1, job_id: 'j01', title: 'Go 后端工程师（支付清结算）', company: '澄湖科技', structure_by: 'ai',
      structure: {
        digest: '9f1c0d3a5b7e44c2a1d6e8f0b2c4d6e8', by: 'ai',
        years: { value: { min: 3, max: 5 }, evidence: '3–5 年后端开发经验' },
        education: { value: '本科', evidence: '本科及以上学历' },
        remote: { value: false, evidence: '每周可远程 1 天' },
        hard_skills: [{ value: 'Go', evidence: '熟练使用 Go' }, { value: 'MySQL', evidence: 'MySQL' }, { value: 'Redis', evidence: 'Redis' }, { value: 'Kafka', evidence: 'Kafka' }, { value: 'gRPC', evidence: 'gRPC 服务拆分经验' }, { value: 'Kubernetes', evidence: '熟悉 Kubernetes' }],
        soft_skills: [{ value: '沟通能力', evidence: '良好的沟通能力' }],
        bonus: [{ value: '支付 / 清结算经验', evidence: '有支付、清结算或风控系统经验者优先' }],
        location: [{ value: '上海', evidence: '上海市徐汇区' }],
      },
      hard: [
        { kind: 'education', requirement: '本科', jd_evidence: '本科及以上学历', status: 'met', fact_ids: ['f4'], basis: 'facts', why: '计算机科学与技术本科' },
        { kind: 'years', requirement: '3–5 年', jd_evidence: '3–5 年后端开发经验', status: 'met', fact_ids: ['f1'], basis: 'facts', why: '4 年 4 个月 Go 服务端，在区间内' },
        { kind: 'language', requirement: '英语六级', jd_evidence: '英语六级', status: 'unknown', fact_ids: [], basis: 'facts', why: '六级成绩在 f8 里，但 f8 还没确认，不能用' },
        { kind: 'location', requirement: '上海', jd_evidence: '上海市徐汇区', status: 'met', fact_ids: [], basis: 'conditions', why: null },
        { kind: 'remote', requirement: false, jd_evidence: '每周可远程 1 天', status: 'unknown', fact_ids: [], basis: 'conditions', why: '岗位不能全远程；只列出岗位的说法' },
      ],
      keywords: [
        { keyword: 'Go', source: 'hard_skill', jd_evidence: '熟练使用 Go', coverage: 'explicit', fact_ids: ['f1', 'f2'], related_fact_ids: [], related_terms: [], why: null },
        { keyword: 'MySQL', source: 'hard_skill', jd_evidence: 'MySQL', coverage: 'explicit', fact_ids: ['f3'], related_fact_ids: [], related_terms: [], why: null },
        { keyword: 'Redis', source: 'hard_skill', jd_evidence: 'Redis', coverage: 'explicit', fact_ids: ['f3'], related_fact_ids: [], related_terms: [], why: null },
        { keyword: 'Kafka', source: 'hard_skill', jd_evidence: 'Kafka', coverage: 'explicit', fact_ids: ['f3'], related_fact_ids: [], related_terms: [], why: null },
        { keyword: 'gRPC', source: 'hard_skill', jd_evidence: 'gRPC 服务拆分经验', coverage: 'explicit', fact_ids: ['f5'], related_fact_ids: [], related_terms: [], why: null },
        { keyword: 'Kubernetes', source: 'hard_skill', jd_evidence: '熟悉 Kubernetes', coverage: 'absent', fact_ids: [], related_fact_ids: [], related_terms: [], why: '事实里没有容器或 K8s 经历' },
        { keyword: '沟通能力', source: 'soft_skill', jd_evidence: '良好的沟通能力', coverage: 'absent', fact_ids: [], related_fact_ids: [], related_terms: [], why: '软技能很难用事实写出来，可以不补' },
        { keyword: '清结算', source: 'bonus', jd_evidence: '有支付、清结算或风控系统经验者优先', coverage: 'related', fact_ids: [], related_fact_ids: ['f2', 'f3'], related_terms: ['对账'], why: '事实写的是"对账"，关键词筛选可能认不出；确有这段经历可以改用岗位原词' },
      ],
      evidence: [
        { kind: 'hard_skill', requirement: '支付清结算核心链路', jd_evidence: '负责支付清结算核心链路的设计与开发', fact_ids: ['f2', 'f3'], related_fact_ids: [] },
        { kind: 'hard_skill', requirement: '高并发下资金流水一致性', jd_evidence: '保证资金流水在高并发下的一致性', fact_ids: ['f3'], related_fact_ids: [] },
        { kind: 'hard_skill', requirement: 'gRPC 服务拆分', jd_evidence: 'gRPC 服务拆分经验', fact_ids: ['f5'], related_fact_ids: [] },
        { kind: 'hard_skill', requirement: 'Kubernetes', jd_evidence: '能独立排查线上容器问题', fact_ids: [], related_fact_ids: [] },
        { kind: 'bonus', requirement: '清结算经验', jd_evidence: '有支付、清结算或风控系统经验者优先', fact_ids: [], related_fact_ids: ['f2'] },
      ],
      notice: '按招聘系统的筛选顺序对照已确认的简历事实；不打分、不排序，也不预测筛选结果',
      extract_note: '已用 AI 抽取 1 个岗位（deepseek-chat，合成）',
    },
  };

  // state.orientation（directions[i].terms 是 state() 为显示算出来的）。
  const orientation = {
    questions_by: 'ai', by: 'ai', updated_at: '2026-11-02T01:40:00+00:00', spent_cny: 0.18,
    questions: [
      { id: 'family', text: '你想找哪些行业的工作？（可多选）', kind: 'choice', options: ['技术研发', '数据与算法', '产品'] },
      { id: 'city', text: '想在哪些城市工作？用顿号或逗号隔开，没有限制可留空。', kind: 'text', options: [] },
      { id: 'years', text: '你有多少年相关工作经验？', kind: 'choice', options: ['1 年以下', '1–3 年', '3–5 年', '5–10 年', '10 年以上'] },
      { id: 'remote', text: '是否接受远程工作？', kind: 'choice', options: ['只要远程', '可以远程', '不要远程'] },
      { id: 'exclude', text: '有没有要排除的行业？用顿号或逗号隔开，没有可留空。', kind: 'text', options: [] },
      { id: 'english', text: '你的英语水平？', kind: 'choice', options: ['能读写文档', '能日常沟通', '能工作语言', '不确定'] },
      { id: 'q-lead', text: '对账服务重构，你是负责人，还是核心参与者？', kind: 'choice', options: ['负责人', '核心参与', '参与其中一部分'] },
      { id: 'q-llm', text: 'LLM 工单汇总工具有没有能公开的代码或演示？', kind: 'choice', options: ['有，可以给链接', '有，但不能公开', '没有'] },
    ],
    answers: { family: ['技术研发', '数据与算法'], city: '上海、杭州', years: '3–5 年', remote: '可以远程', exclude: '博彩、催收', english: '能读写文档' },
    conditions: { cities: ['上海', '杭州'], years: '3–5 年', remote: '可以远程', exclude_industries: ['博彩', '催收'] },
    terms: ['Go 后端', '支付 后端', '清结算', '对账 开发', '大模型 应用 后端', 'RAG 工程师', '实时数仓', '数据平台 后端'],
    directions: [
      { id: 'backend', name: '后端开发', why: '4 年 Go 服务端都在支付公司，对账链路是最硬的一段经历', fact_ids: ['f1', 'f2', 'f3'], source: 'ai',
        terms: ['Go 后端', '支付 后端', '清结算', '对账 开发', '交易系统'],
        strengths: [
          { text: '对账服务日处理约 1200 万笔，量级接近支付岗位的常见要求', fact_ids: ['f3'], jd: [{ job_id: 'j01', evidence: '保证资金流水在高并发下的一致性' }], requirement: null },
          { text: '重构后 P99 从 820ms 降到 140ms', fact_ids: ['f2'], jd: [], requirement: null },
          { text: '「gRPC」是这类岗位的常见要求（4 / 7），已确认事实写到了', fact_ids: ['f5'], jd: [{ job_id: 'j01', evidence: 'gRPC 服务拆分经验' }], requirement: 'gRPC' },
        ],
        gaps: [
          { text: '这类岗位常要求「Kubernetes」（5 / 7），已确认事实里没有写到', fact_ids: [], jd: [{ job_id: 'j01', evidence: '熟悉 Kubernetes' }, { job_id: 'j11', evidence: '熟悉 K8s' }], requirement: 'Kubernetes' },
        ],
        risks: [
          { text: '交易中台类岗位多以 Java 为主，Go 背景要准备转语言的说法', fact_ids: ['f1'], jd: [{ job_id: 'j06', evidence: '可接受 Go 背景转 Java' }], requirement: null },
        ] },
      { id: 'ai-application-dev', name: 'AI 应用开发', why: '后端功底能直接用在 RAG 和 Agent 服务上，但 LLM 经历只有一条业余项目', fact_ids: ['f6', 'f1'], source: 'ai',
        terms: ['大模型 应用 后端', 'RAG 工程师', 'Agent 开发'],
        strengths: [{ text: '做过 LLM 工单汇总工具', fact_ids: ['f6'], jd: [], requirement: null }],
        gaps: [
          { text: '这类岗位常要求「线上 LLM 项目经验」（3 / 4），已确认事实里没有写到', fact_ids: [], jd: [{ job_id: 'j04', evidence: '有线上 LLM 项目经验' }], requirement: '线上 LLM 项目经验' },
          { text: '这类岗位常要求「向量检索」（2 / 4），已确认事实里没有写到', fact_ids: [], jd: [{ job_id: 'j04', evidence: '熟悉向量检索' }], requirement: '向量检索' },
        ],
        risks: [{ text: '"AI 应用"岗位标题很杂，混着前端和产品岗，搜索结果噪音会大', fact_ids: ['f6'], jd: [], requirement: null }] },
      { id: 'data-engineer', name: '数据开发 / 数据工程师', why: 'Kafka 和 MySQL 分库经验能迁移，但没写过 Flink 或数仓', fact_ids: ['f3'], source: 'ai',
        terms: ['实时数仓', '数据平台 后端'],
        strengths: [{ text: 'Kafka 消费链路', fact_ids: ['f3'], jd: [], requirement: null }],
        gaps: [{ text: '这类岗位常要求「Flink」（1 / 1），已确认事实里没有写到', fact_ids: [], jd: [{ job_id: 'j09', evidence: 'Flink 实时数仓' }], requirement: 'Flink' }],
        risks: [] },
    ],
    not_recommended: [
      { id: 'llm-algorithm', name: '大模型算法工程师', why: '事实里没有模型训练或论文；这类岗位大多要求硕士以上', fact_ids: ['f4'], jd: [] },
      { id: 'frontend', name: '前端开发', why: '你选了"技术研发"，但简历里没有前端项目', fact_ids: [], jd: [] },
    ],
    next_actions: [
      { id: 'answer:q-lead', kind: 'answer_question', target: { question_id: 'q-lead' }, text: '回答追问「对账服务重构，你是负责人，还是核心参与者？」' },
      { id: 'confirm:f8', kind: 'confirm_fact', target: { fact_id: 'f8' }, text: '确认事实 f8，或补充它的依据' },
      { id: 'search:backend', kind: 'search', target: { direction_id: 'backend' }, text: '在方向「后端开发」下开始找岗位' },
      { id: 'add_fact:Kubernetes', kind: 'add_fact', target: { requirement: 'Kubernetes', direction_id: 'backend' }, text: '补充一条关于「Kubernetes」的事实（如果你确有这项经历）' },
      { id: 'match:j01', kind: 'job_match', target: { job_id: 'j01' }, text: '看「Go 后端工程师（支付清结算）」的匹配解释' },
    ],
    notes: [],
  };

  const ai = {
    settings: { base_url: 'https://api.deepseek.com', model: 'deepseek-chat', budget_cny: 20 }, key_hint: '3f9c', spent_cny: 3.42,
    consent: { host: 'api.deepseek.com', model: 'deepseek-chat', kinds: ['resume_redacted', 'job_text'], granted_at: '2026-10-30T13:14:00+00:00' },
    kinds: [
      { id: 'resume_redacted', name: '脱敏简历', note: '姓名、电话、邮箱、住址替换成占位符后发送' },
      { id: 'resume_full', name: '完整简历', note: '不脱敏，姓名和联系方式会原样发送' },
      { id: 'job_text', name: '岗位原文', note: '用于 JD 结构化和匹配解释' },
      { id: 'search_query', name: '搜索需求', note: '你用一句话描述想找的岗位时，发送这句话' },
    ],
  };

  // 上一轮搜索的运行报告（每个来源一行）。
  const run = { finished_at: '2026-11-02T01:15:00+00:00', sources: [
    { source_id: 'website', name: '公司官网', enabled: true, state: 'ok', found: 41, note: '' },
    { source_id: 'moka', name: 'Moka', enabled: true, state: 'login', found: 6, note: '列表可读；要看完整表单需要登录核验' },
    { source_id: 'feishu', name: '飞书招聘', enabled: true, state: 'ok', found: 17, note: '' },
    { source_id: 'beisen', name: '北森', enabled: true, state: 'failed', found: 0, note: '返回 429，访问太频繁；30 分钟后再试' },
    { source_id: 'liepin', name: '猎聘', enabled: true, state: 'truncated', found: 50, note: '结果到了单轮上限 50 条，后面的没取；这一轮不会把没取到的岗位标成已关闭' },
    { source_id: 'greenhouse', name: 'Greenhouse', enabled: true, state: 'ok', found: 9, note: '' },
    { source_id: 'lever', name: 'Lever', enabled: false, state: 'never', found: 0, note: '' },
  ] };

  return { NOW, SOURCE_NAMES, directionTable, facts, groups, jobs, match, orientation, ai, run,
    query: { q: '', city: null, direction: null, source: null, fresh: 7 } };
})();
