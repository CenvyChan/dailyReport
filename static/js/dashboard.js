(() => {
  const source = document.getElementById("dashboard-data");
  if (!source || !window.echarts) return;
  const data = JSON.parse(source.textContent);
  const charts = [];
  const typeLabels = { DOMESTIC: "内销", EXPORT: "外销", FOREIGN: "国外采购" };

  const numeric = (value) => Number(value || 0);
  const compactNumber = (value) => {
    const number = numeric(value);
    if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
    if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)}万`;
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  };
  const fullNumber = (value) => numeric(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const axisOptions = { type: "value", axisLabel: { formatter: compactNumber } };

  const drawTrend = (id, items, title) => {
    const node = document.getElementById(id);
    if (!node) return;
    const chart = window.echarts.init(node);
    chart.setOption({
      title: { text: title, left: 14, top: 12, textStyle: { fontSize: 14, fontWeight: 600 } },
      tooltip: { trigger: "axis", valueFormatter: fullNumber },
      grid: { left: 58, right: 18, top: 54, bottom: 42 },
      xAxis: { type: "category", data: items.map((item) => item.period), boundaryGap: false },
      yAxis: axisOptions,
      series: [{ type: "line", data: items.map((item) => numeric(item.amount_cny)), smooth: true, symbolSize: 6, lineStyle: { color: "#1769aa", width: 2 }, itemStyle: { color: "#1769aa" } }],
    });
    charts.push(chart);
  };

  const drawTypeDonut = (items) => {
    const node = document.getElementById("type-share");
    if (!node) return;
    const chart = window.echarts.init(node);
    chart.setOption({
      title: { text: "业务类型结构", left: 14, top: 12, textStyle: { fontSize: 14, fontWeight: 600 } },
      tooltip: { trigger: "item", formatter: (params) => `${params.name}<br/>折算人民币：${fullNumber(params.value)}（${params.percent}%）` },
      legend: { bottom: 8, left: "center" },
      series: [{ type: "pie", radius: ["42%", "68%"], center: ["50%", "52%"], label: { formatter: "{b}: {d}%" }, data: items.map((item) => ({ name: typeLabels[item.label] || item.label, value: numeric(item.amount_cny) })) }],
    });
    charts.push(chart);
  };

  const drawCounterpartRank = (items) => {
    const node = document.getElementById("counterpart-rank");
    if (!node) return;
    const chart = window.echarts.init(node);
    chart.setOption({
      title: { text: "往来单位排行", left: 14, top: 12, textStyle: { fontSize: 14, fontWeight: 600 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (params) => `${params[0].name}<br/>折算人民币：${fullNumber(params[0].value)}` },
      grid: { left: 58, right: 18, top: 54, bottom: 105 },
      xAxis: { type: "category", data: items.map((item) => item.label), axisLabel: { interval: 0, rotate: 30, width: 100, overflow: "break" } },
      yAxis: axisOptions,
      series: [{ type: "bar", data: items.map((item) => numeric(item.amount_cny)), itemStyle: { color: "#147a8a" } }],
    });
    charts.push(chart);
  };

  drawTrend("daily-trend", data.daily_trend, "日趋势（折算人民币）");
  drawTrend("monthly-trend", data.monthly_trend, "月趋势（折算人民币）");
  drawTypeDonut(data.type_share);
  drawCounterpartRank(data.counterpart_rank);
  window.addEventListener("resize", () => charts.forEach((chart) => chart.resize()));
})();
