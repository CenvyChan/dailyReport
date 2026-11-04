"""前端、调度与任务执行共用的唯一报告目录。"""

from datetime import time


REPORT_KINDS = {
    "purchase": {
        "name": "采购执行分析",
        "description": "订单执行、结算、交付分布与供应商集中度",
        "icon": "shopping-cart",
    },
    "receivable": {"name": "应收欠款分析", "description": "客户欠款、结算计划与月度应收趋势", "icon": "wallet"},
    "inventory": {"name": "库存健康度分析", "description": "滞压、直发、覆盖月数与库存数据质量", "icon": "boxes"},
    "sales": {"name": "销售漏斗分析", "description": "出库—应收—收款漏斗与客户、业务员排行", "icon": "trending-up"},
    "production": {"name": "生产执行分析", "description": "完工、积压、车间执行与生产质量", "icon": "factory"},
    "subcontract": {"name": "委外经营分析", "description": "委外交付、领料执行与当前在制快照", "icon": "truck"},
}


def default_kinds():
    return list(REPORT_KINDS)


def validate_kinds(value):
    if not isinstance(value, list) or not value or len(value) != len(set(value)):
        raise ValueError("请至少选择一类分析，不允许重复选择")
    if any(kind not in REPORT_KINDS for kind in value):
        raise ValueError("存在未知的分析种类")
    return value


def default_analysis_start_time():
    return time(8)


def default_analysis_send_time():
    return time(9)
