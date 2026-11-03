// How old a job is, in words the local library can back up: first seen, last seen, still in the list.
// The library knows first_seen / last_seen / status only, so nothing here says 发布 or 在招.
const TZ = "Asia/Shanghai";
const DAY = 864e5;

const dayKey = (iso) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));

// Whole calendar days between iso and now, counted in Beijing time.
export function daysAgo(iso, now = Date.now()) {
  return Math.round((new Date(dayKey(now)) - new Date(dayKey(iso))) / DAY);
}

export function monthDay(iso) {
  const s = dayKey(iso);
  return `${Number(s.slice(5, 7))} 月 ${Number(s.slice(8))} 日`;
}

export function clock(iso) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

// Within a week: 今天 / 昨天 / N 天前; older: the date.
export function relative(iso, now = Date.now()) {
  const d = daysAgo(iso, now);
  return d <= 0 ? "今天" : d === 1 ? "昨天" : d <= 7 ? `${d} 天前` : monthDay(iso);
}

const valid = (iso) => !!iso && !Number.isNaN(new Date(iso).getTime());

// DESIGN.md §4: tone picks the shape (st-fresh/ok = filled dot, warn = half dot, off = ✕).
export function freshness(g, now = Date.now()) {
  if (!valid(g?.first_seen) || !valid(g?.last_seen))
    return { tone: "muted", label: "搜到时间不明", detail: "本机库没有这条记录的搜到时间" };
  if (g.status === "closed")
    return {
      tone: "off",
      label: "已不在列表",
      detail: `最近一次搜到是 ${monthDay(g.last_seen)}，之后连续两轮没再出现`,
    };
  const first = daysAgo(g.first_seen, now);
  const last = daysAgo(g.last_seen, now);
  const lastText = last <= 0 ? "今天还搜得到" : `${relative(g.last_seen, now)}最近一次搜到`;
  const detail = `${relative(g.first_seen, now)}首次搜到，${lastText}`;
  if (last >= 3) return { tone: "warn", label: "近几天没搜到", detail };
  return first <= 2
    ? { tone: "fresh", label: "新搜到", detail }
    : { tone: "ok", label: "仍在列表", detail };
}

export function sourceState(s) {
  return s.status === "closed"
    ? { tone: "off", label: "已不在列表" }
    : { tone: "ok", label: "在列表" };
}
