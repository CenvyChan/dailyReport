class MissingExchangeRate(Exception):
    """外币日报找不到当前公司该月份的汇率。汇率按公司分别维护，所以换公司也会触发。"""

    def __init__(self, company, month):
        self.company = company
        self.month = month
        super().__init__(f"{company.name}缺少 {month:%Y年%m月} 的美元兑人民币汇率，请先在汇率维护中补录")


class ImportFileError(Exception):
    """上传的文件本身读不了或列名对不上——不是某一行的数据问题。

    消息会原样显示给业务人员，所以必须写成可执行的中文提示，
    别把 pandas/xlrd 的英文异常透出去。
    """


class UnresolvedImportPeople(ValueError):
    """源表里的姓名在当前系统里找不到唯一账号。

    不能默认按姓名建号：系统的登录名通常是拼音或工号，中文姓名只存在
    first_name 里，按姓名建号会造出永远无法登录的重复账号（2026-10-30
    的重复账号事故就是这么来的）。必须由管理员先用正确登录名建号，
    或通过 people 映射显式指定。
    """

    def __init__(self, unmatched=(), ambiguous=None):
        self.unmatched = list(unmatched or [])
        self.ambiguous = dict(ambiguous or {})
        parts = []
        if self.unmatched:
            parts.append("以下姓名在系统中没有账号：" + "、".join(self.unmatched))
        for name, candidates in self.ambiguous.items():
            parts.append(f"姓名「{name}」匹配到多个账号：{'、'.join(candidates)}")
        parts.append(
            "请先在「用户管理」为这些人员创建账号并填写姓名，或补充姓名映射后再导入。"
        )
        super().__init__("；".join(parts))
