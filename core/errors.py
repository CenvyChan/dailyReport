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
