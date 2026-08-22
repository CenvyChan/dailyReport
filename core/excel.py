import pandas as pd

from core.errors import ImportFileError


def read_sheet(path, sheet_name=0):
    """同时支持 .xls 和 .xlsx。

    不能写死 engine="xlrd"：xlrd 2.x 只认 BIFF 格式，遇到 .xlsx 会直接抛
    「Excel xlsx file; not supported」。上传框允许两种格式，所以先按 xlrd 试
    （历史数据都是 .xls），失败再交给 openpyxl。

    两个引擎都失败时抛 ImportFileError：pandas/xlrd 的原文是英文技术信息，
    直接透给业务人员看不懂，而且会被上层当成 500。
    """
    try:
        return pd.read_excel(path, sheet_name=sheet_name, engine="xlrd")
    except Exception as xlrd_error:
        if hasattr(path, "seek"):
            path.seek(0)
        try:
            return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
        except Exception as openpyxl_error:
            raise ImportFileError(_explain(sheet_name, xlrd_error, openpyxl_error)) from None


def _explain(sheet_name, xlrd_error, openpyxl_error):
    """把两个引擎的失败归纳成一句业务人员能照着做的提示。"""
    combined = f"{xlrd_error} {openpyxl_error}"
    if "Worksheet" in combined and "not found" in combined:
        return f"文件里找不到名为「{sheet_name}」的工作表，请用下载的导入模板重新填写。"
    if "No sheet named" in combined:
        return f"文件里找不到名为「{sheet_name}」的工作表，请用下载的导入模板重新填写。"
    if "Excel file format cannot be determined" in combined or "not supported" in combined:
        return "这个文件不是有效的 Excel 文件。请另存为 .xls 或 .xlsx 后重新上传（不要上传 CSV 或改了扩展名的文件）。"
    if "password" in combined.lower() or "encrypted" in combined.lower():
        return "这个 Excel 文件有打开口令，请去掉口令后再上传。"
    return "无法读取这个 Excel 文件，可能已损坏或格式不受支持。请用下载的导入模板重新填写后上传。"


def read_rows(path, sheet_name=0):
    return read_sheet(path, sheet_name).to_dict("records")


def require_columns(rows, columns, *, sheet_label="首个工作表"):
    """校验表头是否含有需要的列，缺列就抛 ImportFileError 说明缺哪些、现有哪些。

    columns 里每项可以是列名字符串，也可以是别名元组（任一命中即算存在）。

    没有这层校验时，缺列会让逐行校验的 row.get(列名) 全部返回 None，
    于是每一行都报「不能为空」——用户明明填了内容，却被告知为空。
    """
    if not rows:
        return
    present = {str(key).strip() for key in rows[0].keys()}
    missing = []
    for column in columns:
        aliases = (column,) if isinstance(column, str) else tuple(column)
        if not any(alias in present for alias in aliases):
            missing.append(aliases[0])
    if missing:
        raise ImportFileError(
            f"{sheet_label}缺少必需的列：{'、'.join(missing)}。"
            f"当前表头是：{'、'.join(sorted(present)) or '（空）'}。"
            "请下载导入模板，按模板的列名填写后重新上传。"
        )
