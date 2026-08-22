"""导入接口的上传处理：大小/类型校验，以及把异常翻译成业务人员能看懂的 JSON。

三个 app（core 基础资料、sales、purchase）的导入视图都走这里，避免各写一遍
兜底逻辑而漏掉某一处。
"""

import logging
from io import BytesIO

from django.http import JsonResponse

from core.errors import ImportFileError, MissingExchangeRate


logger = logging.getLogger(__name__)

# 日报表一次导入通常是几百到几千行，10MB 足够。放开会让低配服务器上的
# waitress（8 线程）被一个大文件拖死，其他人页面全部卡住。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = (".xls", ".xlsx")


class UploadRejected(Exception):
    """上传的文件不满足前置条件，message 直接给用户看。"""


def read_upload(request):
    """取出上传文件并做前置校验，返回 (可重复读取的 BytesIO, 原始文件名)。

    返回 BytesIO 而不是直接给 UploadedFile：预览和正式导入都要解析一遍，
    而 UploadedFile 读过一次就到末尾了。
    """
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise UploadRejected("请选择要上传的 Excel 文件")
    name = (uploaded.name or "").lower()
    if not name.endswith(ALLOWED_SUFFIXES):
        raise UploadRejected("只支持 .xls 和 .xlsx 格式，请另存为 Excel 文件后再上传")
    if uploaded.size > MAX_UPLOAD_BYTES:
        actual = uploaded.size / 1024 / 1024
        limit = MAX_UPLOAD_BYTES // 1024 // 1024
        raise UploadRejected(
            f"文件有 {actual:.1f}MB，超过 {limit}MB 上限。"
            "请删掉无关的工作表或分批导入。"
        )
    return BytesIO(uploaded.read()), uploaded.name


def import_response(handler):
    """执行导入逻辑，把各类异常转成带中文说明的 JSON。

    没有这层时任何异常都会冒泡成 Django 错误页，而前端 fetch 拿 HTML 去
    response.json() 会抛 SyntaxError，界面上表现为「点了没反应」。
    """
    try:
        return handler()
    except UploadRejected as error:
        return JsonResponse({"error": str(error)}, status=400)
    except ImportFileError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except MissingExchangeRate as error:
        return JsonResponse({"error": str(error)}, status=400)
    except PermissionError as error:
        return JsonResponse({"error": str(error) or "没有执行该操作的权限"}, status=403)
    except Exception:
        # 兜底：写日志留栈，只给用户一句可行动的话。
        logger.exception("导入失败")
        return JsonResponse(
            {"error": "导入过程出错，数据未写入。请联系管理员查看日志。"}, status=500
        )
