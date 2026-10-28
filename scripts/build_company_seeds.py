"""Build hunt/data/companies.cn.json from hunt/catalog.py and career-ops-china's portals template.

The upstream template lives under private/research/upstream (git-ignored), so the committed JSON is the
artifact; rerun this script only when the pinned upstream changes. Seed data is derived from
https://github.com/shuheng-mo/career-ops-china (MIT), templates/portals-china.example.yml.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UPSTREAM_REPO = 'shuheng-mo/career-ops-china'
TEMPLATE = 'templates/portals-china.example.yml'
DEFAULT_UPSTREAM = ROOT / 'private' / 'research' / 'upstream'
OUT = ROOT / 'hunt' / 'data' / 'companies.cn.json'
FIXED = [dict(id='tencent', name='腾讯', careers_url='https://careers.tencent.com/', provider='tencent', tags=['大厂', '互联网', 'AI', '数据']),
         dict(id='alibaba', name='阿里巴巴', careers_url='https://talent.alibaba.com/', provider='alibaba', tags=['大厂', '互联网', 'AI', '数据', '云']),
         dict(id='meituan', name='美团', careers_url='https://zhaopin.meituan.com/', provider='meituan', tags=['大厂', '互联网', '数据', '算法', '广告']),
         dict(id='bytedance', name='字节跳动', careers_url='https://jobs.bytedance.com', provider='feishu', tags=['大厂', '互联网', 'AI', '数据', '推荐'])]
# The upstream template tracks only ~44 companies, so these well-known employers are added by hand. Each URL
# answered HTTP 200 (after redirects) on the generation date; whether a page lists open roles was not checked.
EXTRA = [('huawei', '华为', 'https://career.huawei.com/reccampportal/portal5/index.html', ['大厂', '硬件', 'AI', '云']),
         ('xiaomi', '小米', 'https://hr.xiaomi.com/', ['大厂', '硬件', 'AI', '汽车']),
         ('antgroup', '蚂蚁集团', 'https://talent.antgroup.com/', ['大厂', '金融科技', 'AI', '数据']),
         ('ctrip', '携程', 'https://job.ctrip.com/', ['互联网', '旅游', '数据']),
         ('mihoyo', '米哈游', 'https://jobs.mihoyo.com/', ['游戏', 'AI']),
         ('dji', '大疆', 'https://careers.dji.com/zh-CN/', ['硬件', '机器人', '算法']),
         ('lixiang', '理想汽车', 'https://www.lixiang.com/employ.html', ['汽车', '智能驾驶', '算法']),
         ('xiaopeng', '小鹏汽车', 'https://xiaopeng.jobs.feishu.cn/', ['汽车', '智能驾驶', '算法', 'AI']),
         ('nio', '蔚来', 'https://nio.jobs.feishu.cn/', ['汽车', '智能驾驶', '算法', 'AI']),
         ('oppo', 'OPPO', 'https://careers.oppo.com/', ['硬件', '终端', 'AI']),
         ('pony-ai', '小马智行', 'https://pony.ai/careers', ['智能驾驶', '算法', 'AI']),
         ('weride', '文远知行', 'https://www.weride.ai/careers', ['智能驾驶', '算法', 'AI']),
         ('zhihu', '知乎', 'https://app.mokahr.com/apply/zhihu/78336', ['互联网', '内容', '社区'])]
# Live reader checks and rejected candidates are recorded privately; append these after upstream rows.
NONTECH = [
    {'id': 'bayer', 'name': '拜耳中国', 'careers_url': 'https://app.mokahr.com/social-recruitment/bayer/148387', 'provider': 'mokahr', 'tags': ['医疗健康', '销售与商务', '医药'], 'source': 'curated'},
    {'id': 'ey', 'name': '安永', 'careers_url': 'https://app.mokahr.com/social-recruitment/ey/102474', 'provider': 'mokahr', 'tags': ['咨询', '人力行政财务法务'], 'source': 'curated'},
    {'id': 'marriott', 'name': '万豪国际', 'careers_url': 'https://app.mokahr.com/social-recruitment/marriott/141002', 'provider': 'mokahr', 'tags': ['酒店餐饮旅游', '客户服务'], 'source': 'curated'},
    {'id': 'prada', 'name': '普拉达', 'careers_url': 'https://app.mokahr.com/social-recruitment/pradagroup/151069', 'provider': 'mokahr', 'tags': ['销售与商务', '客户服务', '消费零售'], 'source': 'curated'},
    {'id': 'schneider-electric', 'name': '施耐德电气', 'careers_url': 'https://app.mokahr.com/social-recruitment/se/98712', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '电气制造'], 'source': 'curated'},
    {'id': 'bosch-cn', 'name': '博世中国', 'careers_url': 'https://app.mokahr.com/social-recruitment/bosch/73873', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'volvo-cars', 'name': '沃尔沃汽车', 'careers_url': 'https://app.mokahr.com/social-recruitment/volvocars/56034', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'nestle-cn', 'name': '雀巢大中华', 'careers_url': 'https://app.mokahr.com/social-recruitment/nestlezgc/91898', 'provider': 'mokahr', 'tags': ['销售与商务', '市场与品牌', '供应链与生产制造', '食品'], 'source': 'curated'},
    {'id': 'carlsberg', 'name': '嘉士伯', 'careers_url': 'https://app.mokahr.com/social-recruitment/carlsberg/37541', 'provider': 'mokahr', 'tags': ['销售与商务', '供应链与生产制造', '食品'], 'source': 'curated'},
    {'id': 'voyah', 'name': '岚图汽车', 'careers_url': 'https://app.mokahr.com/social-recruitment/voyah/146292', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'geely', 'name': '吉利汽车', 'careers_url': 'https://app.mokahr.com/social-recruitment/geely/102042', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'yanfeng', 'name': '延锋', 'careers_url': 'https://app.mokahr.com/social-recruitment/yanfeng/45086', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'joyson', 'name': '均胜集团', 'careers_url': 'https://app.mokahr.com/social-recruitment/joyson/94310', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'envision-energy', 'name': '远景能源', 'careers_url': 'https://app.mokahr.com/social-recruitment/envisiongroup/43123', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '能源'], 'source': 'curated'},
    {'id': 'solaxpower', 'name': '艾罗能源', 'careers_url': 'https://app.mokahr.com/social-recruitment/solaxpower/151400', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '能源'], 'source': 'curated'},
    {'id': 'trinasolar', 'name': '天合光能', 'careers_url': 'https://app.mokahr.com/social-recruitment/trinasolar/39871', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '能源'], 'source': 'curated'},
    {'id': 'sanhua', 'name': '三花智控', 'careers_url': 'https://app.mokahr.com/social-recruitment/zjshc/56208', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '汽车'], 'source': 'curated'},
    {'id': 'synland', 'name': '时代新安', 'careers_url': 'https://app.mokahr.com/social-recruitment/synland/58041', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '汽车'], 'source': 'curated'},
    {'id': 'anta', 'name': '安踏集团', 'careers_url': 'https://app.mokahr.com/social-recruitment/antahr/142914', 'provider': 'mokahr', 'tags': ['销售与商务', '运营', '市场与品牌', '消费零售'], 'source': 'curated'},
    {'id': 'wantai-bio', 'name': '万泰生物', 'careers_url': 'https://app.mokahr.com/social-recruitment/ystwt/97880', 'provider': 'mokahr', 'tags': ['医疗健康', '供应链与生产制造', '医药'], 'source': 'curated'},
    {'id': 'zuoyebang-edu', 'name': '作业帮', 'careers_url': 'https://app.mokahr.com/social-recruitment/zuoyebang/41328', 'provider': 'mokahr', 'tags': ['教育培训', '运营'], 'source': 'curated'},
    {'id': 'zijin-mining', 'name': '紫金矿业', 'careers_url': 'https://app.mokahr.com/social-recruitment/zijinmining/140688', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '矿业'], 'source': 'curated'},
    {'id': 'westlake-university', 'name': '西湖大学', 'careers_url': 'https://app.mokahr.com/social-recruitment/westlake/43525', 'provider': 'mokahr', 'tags': ['教育培训', '人力行政财务法务'], 'source': 'curated'},
    {'id': 'pharmaron', 'name': '康龙化成', 'careers_url': 'https://app.mokahr.com/campus-recruitment/pharmaron/44352', 'provider': 'mokahr', 'tags': ['医疗健康', '供应链与生产制造', '医药'], 'source': 'curated'},
    {'id': 'hengrui', 'name': '恒瑞医药', 'careers_url': 'https://app.mokahr.com/campus-recruitment/hengrui/145997', 'provider': 'mokahr', 'tags': ['医疗健康', '销售与商务', '医药'], 'source': 'curated'},
    {'id': 'yusen-logistics', 'name': '日邮物流', 'careers_url': 'https://app.mokahr.com/campus-recruitment/yusen/73956', 'provider': 'mokahr', 'tags': ['交通运输与生活服务', '客户服务', '物流'], 'source': 'curated'},
    {'id': 'canmax', 'name': '天华新能', 'careers_url': 'https://app.mokahr.com/apply/canmax/140245', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '能源'], 'source': 'curated'},
    {'id': 'bsh', 'name': '博西家电', 'careers_url': 'https://app.mokahr.com/apply/bshg/28741', 'provider': 'mokahr', 'tags': ['供应链与生产制造', '销售与商务', '客户服务', '制造'], 'source': 'curated'},
    {'id': 'sushang-bank', 'name': '苏商银行', 'careers_url': 'https://app.mokahr.com/social-recruitment/snb/45591', 'provider': 'mokahr', 'tags': ['金融专业', '客户服务'], 'source': 'curated'},
    {'id': 'luckin-coffee', 'name': '瑞幸咖啡', 'careers_url': 'https://app.mokahr.com/campus-recruitment/lkcoffee/45257', 'provider': 'mokahr', 'tags': ['酒店餐饮旅游', '运营', '市场与品牌', '餐饮连锁'], 'source': 'curated'},
    {'id': 'tal-education', 'name': '好未来', 'careers_url': 'https://app.mokahr.com/campus-recruitment/tal/95443', 'provider': 'mokahr', 'tags': ['教育培训', '运营'], 'source': 'curated'},
    {'id': 'muyuan-food', 'name': '牧原食品', 'careers_url': 'https://app.mokahr.com/campus-recruitment/muyuan/70116', 'provider': 'mokahr', 'tags': ['公共事业·农业·能源', '供应链与生产制造', '农业'], 'source': 'curated'},
    {'id': 'avatr', 'name': '阿维塔', 'careers_url': 'https://xcn5vbnquq58.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'zeron', 'name': '零一汽车', 'careers_url': 'https://zeron.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'desay-sv', 'name': '德赛西威', 'careers_url': 'https://yesv-desaysv.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['供应链与生产制造', '汽车'], 'source': 'curated'},
    {'id': 'hete', 'name': '和而泰', 'careers_url': 'https://salcje7shg.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['供应链与生产制造', '制造'], 'source': 'curated'},
    {'id': 'breo', 'name': '倍轻松', 'careers_url': 'https://e0cmewvq7v7.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['销售与商务', '市场与品牌', '消费零售'], 'source': 'curated'},
    {'id': 'genki-forest', 'name': '元气森林', 'careers_url': 'https://k11pnjpvz1.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['销售与商务', '市场与品牌', '食品'], 'source': 'curated'},
    {'id': 'babycare', 'name': 'Babycare', 'careers_url': 'https://babycare.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['销售与商务', '运营', '市场与品牌', '消费零售'], 'source': 'curated'},
    {'id': 'leoao', 'name': '乐刻运动', 'careers_url': 'https://leoao-inc.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['运营', '客户服务', '交通运输与生活服务', '健身'], 'source': 'curated'},
    {'id': 'mediastorm', 'name': '影视飓风', 'careers_url': 'https://mediastorm.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['内容与传媒', '市场与品牌'], 'source': 'curated'},
    {'id': 'bluefocus', 'name': '蓝色光标', 'careers_url': 'https://bluefocus.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['市场与品牌', '内容与传媒'], 'source': 'curated'},
    {'id': 'molbreeding', 'name': '博瑞迪', 'careers_url': 'https://molbreeding.jobs.feishu.cn/', 'provider': 'feishu', 'tags': ['公共事业·农业·能源', '农业'], 'source': 'curated'},
# 北森 tenants (2026-10-28): banks, brokerages, insurers and others the beisen reader read live.
    {'id': 'beisen-njzq', 'name': '南京证券', 'careers_url': 'https://njzq.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '证券'], 'source': 'curated'},
    {'id': 'beisen-chinalife', 'name': '中国人寿', 'careers_url': 'https://chinalife.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '客户服务', '保险'], 'source': 'curated'},
    {'id': 'beisen-bosc', 'name': '上海银行', 'careers_url': 'https://bosc.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '人力行政财务法务', '银行'], 'source': 'curated'},
    {'id': 'beisen-bankofbeijing', 'name': '北京银行', 'careers_url': 'https://bankofbeijing.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '银行'], 'source': 'curated'},
    {'id': 'beisen-chinastock', 'name': '中国银河证券', 'careers_url': 'https://chinastock.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '证券'], 'source': 'curated'},
    {'id': 'beisen-sinotrans', 'name': '中国外运', 'careers_url': 'https://sinotrans.zhiye.com/social', 'provider': 'beisen', 'tags': ['交通运输与生活服务', '供应链与生产制造', '销售与商务', '物流'], 'source': 'curated'},
    {'id': 'beisen-bdochina', 'name': '立信会计师事务所', 'careers_url': 'https://bdochina.zhiye.com/social', 'provider': 'beisen', 'tags': ['人力行政财务法务', '咨询', '会计'], 'source': 'curated'},
    {'id': 'beisen-csc108', 'name': '中信建投证券', 'careers_url': 'https://csc108.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '证券'], 'source': 'curated'},
    {'id': 'beisen-guominpension', 'name': '国民养老保险', 'careers_url': 'https://guominpension.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '保险'], 'source': 'curated'},
    {'id': 'beisen-cxmt', 'name': '长鑫存储', 'careers_url': 'https://cxmt.zhiye.com/social', 'provider': 'beisen', 'tags': ['供应链与生产制造', '技术研发', '半导体'], 'source': 'curated'},
# 大易 tenants (2026-10-28): property, finance and other groups the dayee reader read live.
    {'id': 'dayee-cifi', 'name': '旭辉', 'careers_url': 'https://hotjob.cn/wt/cifi/web/index/social?brandCode=1', 'provider': 'dayee', 'tags': ['建筑工程与房地产', '销售与商务', '地产'], 'source': 'curated'},
    {'id': 'dayee-crcbank', 'name': '华润银行', 'careers_url': 'https://crc.wintalent.cn/wt/crcbank/web/index?brandCode=1', 'provider': 'dayee', 'tags': ['金融专业', '销售与商务', '银行'], 'source': 'curated'},
    {'id': 'dayee-xyzq', 'name': '兴业证券', 'careers_url': 'https://email.wintalent.cn/wt/xyzq/web/index?brandCode=1', 'provider': 'dayee', 'tags': ['金融专业', '证券'], 'source': 'curated'},
    {'id': 'dayee-wanda', 'name': '万达', 'careers_url': 'https://wanda.hotjob.cn/wt/wanda/web/index', 'provider': 'dayee', 'tags': ['建筑工程与房地产', '运营', '商业地产'], 'source': 'curated'},
    {'id': 'dayee-ct', 'name': '财通证券', 'careers_url': 'https://www.hotjob.cn/wt/CT/web/index', 'provider': 'dayee', 'tags': ['金融专业', '销售与商务', '证券'], 'source': 'curated'},
    {'id': 'dayee-timesgroup', 'name': '时代中国', 'careers_url': 'https://www.hotjob.cn/wt/timesgroup/web/index', 'provider': 'dayee', 'tags': ['建筑工程与房地产', '地产'], 'source': 'curated'},
    {'id': 'dayee-rrd', 'name': '当纳利中国', 'careers_url': 'https://www.hotjob.cn/wt/rrd/web/index?brandCode=1', 'provider': 'dayee', 'tags': ['供应链与生产制造', '销售与商务', '印刷'], 'source': 'curated'},
    {'id': 'dayee-263group', 'name': '263', 'careers_url': 'https://www.hotjob.cn/wt/263group/web/index/social', 'provider': 'dayee', 'tags': ['销售与商务', '客户服务', '通信'], 'source': 'curated'},
# Second batch (2026-10-28): 北森 and 大易 tenants found by search and read live.
    {'id': 'beisen-gtfund', 'name': '国泰基金', 'careers_url': 'https://gtfund.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '基金'], 'source': 'curated'},
    {'id': 'beisen-cicc', 'name': '中金公司', 'careers_url': 'https://cicc.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '咨询', '证券'], 'source': 'curated'},
    {'id': 'beisen-guosen', 'name': '国信证券', 'careers_url': 'https://guosen.zhiye.com/social', 'provider': 'beisen', 'tags': ['金融专业', '销售与商务', '证券'], 'source': 'curated'},
    {'id': 'beisen-chery', 'name': '奇瑞汽车', 'careers_url': 'https://chery.zhiye.com/social', 'provider': 'beisen', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'beisen-changan', 'name': '长安汽车', 'careers_url': 'https://changan.zhiye.com/social', 'provider': 'beisen', 'tags': ['供应链与生产制造', '销售与商务', '汽车'], 'source': 'curated'},
    {'id': 'beisen-siic', 'name': '上海实业', 'careers_url': 'https://siic.zhiye.com/social', 'provider': 'beisen', 'tags': ['供应链与生产制造', '医疗健康', '销售与商务', '综合管理'], 'source': 'curated'},
    {'id': 'beisen-grainrain', 'name': '谷雨', 'careers_url': 'https://grainrain.zhiye.com/social', 'provider': 'beisen', 'tags': ['市场与品牌', '销售与商务', '运营', '消费品'], 'source': 'curated'},
    {'id': 'beisen-yealink', 'name': '亿联网络', 'careers_url': 'https://yealink.zhiye.com/social', 'provider': 'beisen', 'tags': ['销售与商务', '技术研发', '通信'], 'source': 'curated'},
    {'id': 'dayee-lczq', 'name': '联储证券', 'careers_url': 'https://www.hotjob.cn/wt/lczq/web/index', 'provider': 'dayee', 'tags': ['金融专业', '证券'], 'source': 'curated'},
    {'id': 'dayee-essence', 'name': '安信证券', 'careers_url': 'https://sc.hotjob.cn/wt/Essence/web/index', 'provider': 'dayee', 'tags': ['金融专业', '销售与商务', '证券'], 'source': 'curated'},
]
# Result of the first real sweep (2026-10-26, keyword 'AI 产品经理'): `dead` answered HTTP 404, `needs_adapter`
# gave the generic website reader a parse_error. Sweeps skip both unless asked; the rows stay for a later recheck.
STATUS = dict.fromkeys((
    'baichuan-ai-com-careers',
    'modelbest-cn-careers',
    'manus-im-careers',
    'luchentech-com-joinus',
    'sensetime-com-cn-career',
    'langboat-com-careers',
    'talent-baidu-com-external-baidu-social-h',
    'starrocks-io-careers',
    'sensorsdata-cn-about-job-html',
), 'dead') | dict.fromkeys((
    'huawei',
    'xiaomi',
    'antgroup',
    'mihoyo',
    'oppo',
    'pony-ai',
    'zhaopin-kuaishou-cn-recruit-e',
    'jobs-bilibili-com-campus-positions',
    'siliconflow-cn-zh-cn-about',
    'infini-ai-com-careers',
    '4paradigm-com-about-jobs-html',
    'ctrip',
    'dji',
    'lixiang',
    'pingcap-com-careers',
    'deepexi-com-about-us',
    'doris-apache-org',
    'apply-workable-com-huggingface',
), 'needs_adapter')
# 2026-10-27 benchmark: these seeds pointed at marketing pages while the jobs sit on a Moka or Feishu tenant the
# readers already support (found from each official careers page). Applied to seed rows only; hunt/catalog.py keeps its URLs.
# 京东使用其公开社招列表，由专用 API 读取器承接。
SEED_URLS = {
    'join-jd-com-home': 'https://zhaopin.jd.com/web/job/job_info_list/3',
    'kimi': 'https://app.mokahr.com/apply/moonshot/148506',
    'minimax': 'https://vrfi1sk8a0.jobs.feishu.cn/379481',
    'stepfun': 'https://app.mokahr.com/social-recruitment/step/94904',
    'zhipuai-cn-joinus': 'https://zhipu-ai.jobs.feishu.cn/',
    '01-ai-careers': 'https://01ai.jobs.feishu.cn/index/',
    'megvii-com-join-us': 'https://app.mokahr.com/social-recruitment/megviihr/38641',
}
# Upstream rows for companies that already have a dedicated reader in hunt/catalog.py.
CATALOG_COVERS = ('DeepSeek', '月之暗面', 'MiniMax', '阶跃星辰')
SECTION_TAGS = (('大厂', ['大厂', '互联网']), ('大模型', ['AI', '大模型']), ('AI 应用', ['AI', '应用']),
                ('数据 &', ['数据', '数据库']), ('AI Infra', ['AI', 'Infra', '推理']), ('远程', ['远程', '海外']))
NOTE_TAGS = ('数据', '大模型', 'AI', 'Agent', '推理', '搜索', '推荐', '广告', '算法', '数据库', '云', '安全', '游戏', '多模态', 'NLP', 'OLAP')


def _value(raw):
    raw = raw.strip()
    if raw[:1] in '"\'' and raw.count(raw[0]) >= 2:
        return raw[1:raw.index(raw[0], 1)]
    return re.split(r'\s+#', raw, maxsplit=1)[0].strip()


def read_tracked_companies(text):
    """The flat `tracked_companies:` list of the upstream template; no general YAML support."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.rstrip() == 'tracked_companies:'), None)
    if start is None: raise ValueError('没有找到 tracked_companies 段')
    rule = re.compile(r'\s*#\s*=+\s*$')
    rows, section = [], ''
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if re.match(r'[A-Za-z_]\w*:', line): break
        if line.startswith('  # ') and not rule.match(line) and i + 1 < len(lines) and rule.match(lines[i - 1]) and rule.match(lines[i + 1]):
            section = line.strip().lstrip('#').strip()
        item = re.match(r'  - name:\s*(.+)$', line)
        field = re.match(r'    (\w+):\s*(.*)$', line)
        if item:
            rows.append(dict(name=_value(item.group(1)), section=section, enabled=True))
        elif field and rows:
            value = _value(field.group(2))
            rows[-1][field.group(1)] = (value == 'true') if field.group(1) == 'enabled' else value
    return rows


def _tags(section, name, notes):
    tags = [t for key, found in SECTION_TAGS if key in section for t in found]
    haystack = (name + ' ' + notes).lower()
    tags += [t for t in NOTE_TAGS if t.lower() in haystack]
    return list(dict.fromkeys(tags))


def _slug(url, taken):
    parts = urlsplit(url)
    base = re.sub(r'[^a-z0-9]+', '-', (re.sub(r'^www\.', '', parts.hostname or '') + parts.path).lower()).strip('-')[:40] or 'company'
    ident, n = base, 2
    while ident in taken:
        ident, n = '%s-%d' % (base, n), n + 1
    return ident


def _key(url):
    parts = urlsplit(url)
    return (parts.hostname or '').lower(), parts.path.rstrip('/')


def build(rows):
    from hunt.catalog import CATALOG
    from hunt.providers import route
    def provider_of(url):
        found = route(dict(careers_url=url))
        return found.id if found else None
    seeds = [dict(s, source='career-ops-china') for s in FIXED]
    for r in CATALOG:
        seeds.append(dict(id=r['id'], name=r['company'], careers_url=r['url'], provider=provider_of(r['url']),
                          tags=[t.strip() for t in re.split(r'/', r['category'])], source='catalog'))
    for ident, name, url, tags in EXTRA:
        seeds.append(dict(id=ident, name=name, careers_url=url, provider=provider_of(url), tags=tags, source='curated'))
    seen = {_key(s['careers_url']) for s in seeds}
    taken = {s['id'] for s in seeds}
    for row in rows:
        url = row.get('careers_url', '')
        if not row.get('enabled') or not url or any(row['name'].startswith(n) for n in CATALOG_COVERS): continue
        provider = provider_of(url)
        # The fixed rows cover these hosts; their providers search by keyword and ignore the URL path.
        if provider in ('tencent', 'alibaba', 'meituan', 'feishu') or _key(url) in seen: continue
        seen.add(_key(url))
        ident = _slug(url, taken); taken.add(ident)
        seeds.append(dict(id=ident, name=row['name'], careers_url=url, provider=provider,
                          tags=_tags(row['section'], row['name'], row.get('notes', '')), source='career-ops-china'))
    seeds.extend(dict(s) for s in NONTECH)
    seeds = [dict(s, careers_url=SEED_URLS[s['id']], provider=provider_of(SEED_URLS[s['id']])) if s['id'] in SEED_URLS else s for s in seeds]
    return [dict(s, status=STATUS[s['id']]) if s['id'] in STATUS else s for s in seeds]


def pinned_commit(pins):
    for line in pins.read_text(encoding='utf-8').splitlines():
        fields = line.split()
        if fields[:1] == [UPSTREAM_REPO]: return fields[1]
    raise ValueError(str(pins) + ' 中没有 ' + UPSTREAM_REPO)


def main(argv=None):
    parser = argparse.ArgumentParser(description='从上游模板和内置目录生成公司种子 JSON')
    parser.add_argument('--upstream', type=Path, default=DEFAULT_UPSTREAM, help='含 pins.txt 与 coc/ 的目录')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args(argv)
    template = args.upstream / 'coc' / TEMPLATE
    try:
        if not template.is_file():
            raise FileNotFoundError('找不到上游模板 %s；它在 git 忽略的 private/research/upstream 下，需先取得 %s 的该文件' % (template, UPSTREAM_REPO))
        commit = pinned_commit(args.upstream / 'pins.txt')
        rows = read_tracked_companies(template.read_text(encoding='utf-8'))
        seeds = build(rows)
    except (OSError, ValueError) as error:
        print('错误：' + str(error), file=sys.stderr)
        return 1
    data = dict(schema_version=1, generated_from=dict(repo=UPSTREAM_REPO, commit=commit, file=TEMPLATE, license='MIT'), companies=seeds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = {}
    for s in seeds: counts[s['provider'] or 'website'] = counts.get(s['provider'] or 'website', 0) + 1
    skipped = sum(not r.get('careers_url') for r in rows)
    print('已写入 %s：%d 家 %s；跳过 %d 行（没有 careers_url）' % (args.out, len(seeds), counts, skipped))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
