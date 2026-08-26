(() => {
  const source = document.getElementById("dashboard-data");
  if (!source || !window.echarts) return;
  const data = JSON.parse(source.textContent);
  const typeLabels = { DOMESTIC: "内销", EXPORT: "外销", FOREIGN: "国外采购" };

  const numeric = (value) => Number(value || 0);
  const compactNumber = (value) => {
    const number = numeric(value);
    if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
    if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)}万`;
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  };
  const fullNumber = (value) =>
    numeric(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // 主题色不写死，从 CSS 变量读：明暗切换时只要重算一遍就能跟上，
  // 不需要在 JS 里再维护第二份调色板。
  const token = (name, fallback) => {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  };
  const palette = () => {
    const dark = document.documentElement.dataset.theme !== "light";
    return {
      brand: token("--brand-hi", "#818cf8"),
      cyan: token("--cyan", "#22d3ee"),
      violet: token("--violet", "#a855f7"),
      ok: token("--ok", "#34d399"),
      warn: token("--warn", "#fbbf24"),
      label: token("--text-mute", "#667487"),
      // 网格线要比标签更淡，否则图上全是横线，数据反而看不清
      split: dark ? "rgba(255,255,255,0.06)" : "rgba(15,23,42,0.07)",
      axis: dark ? "rgba(255,255,255,0.12)" : "rgba(15,23,42,0.14)",
      tipBg: dark ? "rgba(9,14,24,0.94)" : "rgba(255,255,255,0.97)",
      tipText: token("--text", dark ? "#e6edf7" : "#0f1729"),
    };
  };

  // 每张图记下自己的绘制函数，主题一换就整批重画。
  const registry = [];
  const mount = (id, build) => {
    const node = document.getElementById(id);
    if (!node) return;
    const chart = window.echarts.init(node, null, { renderer: "canvas" });
    const paint = () => chart.setOption(build(palette()), true);
    paint();
    registry.push({ chart, paint });
  };

  const baseGrid = { left: 56, right: 20, top: 22, bottom: 34, containLabel: true };
  const tooltip = (colors, extra = {}) => ({
    backgroundColor: colors.tipBg,
    borderColor: colors.axis,
    borderWidth: 1,
    textStyle: { color: colors.tipText, fontSize: 12 },
    valueFormatter: fullNumber,
    ...extra,
  });
  const valueAxis = (colors) => ({
    type: "value",
    axisLabel: { formatter: compactNumber, color: colors.label, fontSize: 11 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: colors.split } },
  });
  const categoryAxis = (colors, items, extra = {}) => ({
    type: "category",
    data: items,
    axisLine: { lineStyle: { color: colors.axis } },
    axisTick: { show: false },
    axisLabel: { color: colors.label, fontSize: 11, ...(extra.axisLabel || {}) },
    boundaryGap: extra.boundaryGap !== undefined ? extra.boundaryGap : true,
  });
  // CSS 变量里是 #818cf8 这种十六进制，ECharts 的渐变要能带透明度，
  // 所以自己转一次。写死一份 rgba 调色板就没法跟着主题变量走了。
  const alpha = (color, opacity) => {
    const value = String(color).trim();
    if (value.startsWith("#")) {
      const hex = value.length === 4 ? `#${[...value.slice(1)].map((c) => c + c).join("")}` : value;
      const number = parseInt(hex.slice(1), 16);
      return `rgba(${(number >> 16) & 255}, ${(number >> 8) & 255}, ${number & 255}, ${opacity})`;
    }
    const parts = value.replace(/^rgba?\(|\)$/g, "").split(",").slice(0, 3).map((part) => part.trim());
    return parts.length === 3 ? `rgba(${parts.join(", ")}, ${opacity})` : value;
  };
  // 面积渐变：顶部有色、底部透明，暗色底上折线才有「发光」的层次
  const fade = (color) =>
    new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
      { offset: 0, color: alpha(color, 0.34) },
      { offset: 1, color: alpha(color, 0) },
    ]);

  const trend = (id, items, color) =>
    mount(id, (colors) => ({
      backgroundColor: "transparent",
      grid: baseGrid,
      tooltip: tooltip(colors, { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: colors.axis } } }),
      xAxis: categoryAxis(colors, items.map((item) => item.period), { boundaryGap: items.length < 3 }),
      yAxis: valueAxis(colors),
      series: [
        // 一两个点画折线只会得到一个悬在半空的孤点，看着像图表坏了
        // （筛到「本月」时月趋势就只有一个点）。少于三点改画柱子。
        items.length < 3
          ? {
              type: "bar",
              barMaxWidth: 46,
              data: items.map((item) => numeric(item.amount_cny)),
              itemStyle: {
                borderRadius: [5, 5, 0, 0],
                color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: colors[color] },
                  { offset: 1, color: alpha(colors[color], 0.12) },
                ]),
              },
            }
          : {
              type: "line",
              smooth: true,
              symbol: "circle",
              symbolSize: 5,
              showSymbol: items.length <= 40,
              data: items.map((item) => numeric(item.amount_cny)),
              lineStyle: { color: colors[color], width: 2, shadowBlur: 12, shadowColor: colors[color] },
              itemStyle: { color: colors[color] },
              areaStyle: { color: fade(colors[color]) },
            },
      ],
    }));

  trend("daily-trend", data.daily_trend || [], "cyan");
  trend("monthly-trend", data.monthly_trend || [], "brand");

  mount("type-share", (colors) => ({
    backgroundColor: "transparent",
    tooltip: tooltip(colors, {
      trigger: "item",
      formatter: (params) => `${params.name}<br/>折算人民币：${fullNumber(params.value)}（${params.percent}%）`,
    }),
    legend: { bottom: 6, left: "center", textStyle: { color: colors.label, fontSize: 11 }, icon: "circle" },
    color: [colors.cyan, colors.violet, colors.brand, colors.ok, colors.warn],
    series: [
      {
        type: "pie",
        radius: ["46%", "70%"],
        center: ["50%", "44%"],
        // 扇区之间留缝：暗色底上贴在一起会糊成一整圈
        itemStyle: { borderColor: "rgba(0,0,0,0)", borderWidth: 2 },
        label: { color: colors.label, fontSize: 11, formatter: "{b} {d}%" },
        labelLine: { lineStyle: { color: colors.axis } },
        data: (data.type_share || []).map((item) => ({
          name: typeLabels[item.label] || item.label,
          value: numeric(item.amount_cny),
        })),
      },
    ],
  }));

  const rank = (id, items, color) =>
    mount(id, (colors) => ({
      backgroundColor: "transparent",
      grid: { ...baseGrid, bottom: 74 },
      tooltip: tooltip(colors, {
        trigger: "axis",
        axisPointer: { type: "shadow", shadowStyle: { color: colors.split } },
        formatter: (params) => `${params[0].name}<br/>折算人民币：${fullNumber(params[0].value)}`,
      }),
      xAxis: categoryAxis(colors, items.map((item) => item.label), {
        axisLabel: { interval: 0, rotate: 32, width: 92, overflow: "truncate" },
      }),
      yAxis: valueAxis(colors),
      series: [
        {
          type: "bar",
          barMaxWidth: 26,
          data: items.map((item) => numeric(item.amount_cny)),
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: colors[color] },
              { offset: 1, color: alpha(colors[color], 0.12) },
            ]),
          },
        },
      ],
    }));

  rank("counterpart-rank", data.counterpart_rank || [], "brand");
  // owner_rank 后端一直在算但从来没画过。按人看业绩是月度复盘最常用的一刀。
  rank("owner-rank", data.owner_rank || [], "cyan");

  const resize = () => registry.forEach((item) => item.chart.resize());
  window.addEventListener("resize", resize);
  // 明暗切换是 base.html 里的 store 派发的事件：坐标轴和文字色是初始化时算好的，
  // 不重画的话切到亮色会剩一堆看不见的灰字。
  window.addEventListener("fns-theme-change", () => registry.forEach((item) => item.paint()));
})();
