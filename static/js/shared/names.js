// Display names for source kinds and direction ids, shared by the new pages.
import { items } from "./dom.js";
import { state } from "./state.js";

const SOURCE_NAMES = {
  website: "公司官网",
  websearch: "扩展网页搜索",
  boss: "BOSS 直聘",
  liepin: "猎聘",
  lagou: "拉勾",
  anker: "安克官网",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  feishu: "飞书招聘",
  moka: "Moka",
  mokahr: "Moka",
  beisen: "北森",
  tencent: "腾讯招聘",
  alibaba: "阿里招聘",
  meituan: "美团招聘",
  jd: "京东招聘",
  didi: "滴滴招聘",
  netease: "网易招聘",
  xiaohongshu: "小红书招聘",
  dayee: "大易",
  inbox: "岗位书签",
  import: "手工导入",
  fixture: "合成验收",
};

export function sourceName(kind) {
  return SOURCE_NAMES[kind] || kind || "来源未记录";
}

export function directionName(id) {
  if (!id) return "未归类";
  const table = items(state?.direction_table).find((d) => d.id === id);
  const chosen = items(state?.orientation?.directions).find((d) => d.id === id);
  return table?.name || chosen?.name || id;
}

export function factById(id) {
  return items(state?.candidate?.facts).find((f) => f.id === id) || null;
}
