# -*- coding: utf-8 -*-
"""
直接二进制 patch: 把 采购入库模板.xls 里所有 CALCMODE(0x000D) 记录
改成自动计算(0x0001), 解决 spinner 改 LinkedCell 后下方公式不重算的问题。
olefile 不支持覆写流, 这里用 win32com 的 Storage+Stream API 重写。
"""
import os, sys, struct, pathlib
sys.stdout.reconfigure(encoding='utf-8')
import olefile

ROOT = pathlib.Path(__file__).parent.parent.parent
DST = str(ROOT / 'data' / 'source' / '采购入库模板.xls')

# 1) 读 Workbook 流
ole = olefile.OleFileIO(DST)
wb_bytes = bytearray(ole.openstream('Workbook').read())
ole.close()

# 2) 遍历记录, 把 CALCMODE(0x000D) 的 value 改成 0x0001 (fAutoCal=1)
i = 0
patched = 0
while i + 4 <= len(wb_bytes):
    rt = struct.unpack('<H', wb_bytes[i:i+2])[0]
    ln = struct.unpack('<H', wb_bytes[i+2:i+4])[0]
    if i + 4 + ln > len(wb_bytes):
        break
    if rt == 0x000D and ln >= 2:
        wb_bytes[i+4] = 0x01
        wb_bytes[i+5] = 0x00
        patched += 1
    i += 4 + ln

print(f'Patched {patched} CALCMODE records to auto (0x0001)')

# 3) 用 win32com 的 IStorage 重写 Workbook 流
import win32com.client
import pythoncom
from win32com.storagecon import STGM_READWRITE, STGM_SHARE_EXCLUSIVE, STGM_DIRECT
import pywintypes

stg = pythoncom.StgOpenStorage(DST, None, STGM_READWRITE | STGM_SHARE_EXCLUSIVE | STGM_DIRECT, None, 0)
stm = stg.OpenStream('Workbook', None, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, 0)
stat = stm.Stat()
print('stream size:', stat[0])
stm.Seek(0, 0)
written = 0
chunk = 4096
while written < len(wb_bytes):
    end = min(written + chunk, len(wb_bytes))
    stm.Write(bytes(wb_bytes[written:end]))
    written = end
print(f'wrote {written} bytes back to Workbook stream')
try:
    stm.SetSize(written)
except Exception as e:
    print('SetSize err (可能不需要):', e)
stm.Commit(0)
stm = None
stg.Commit(0)
stg = None

print('Done. size =', os.path.getsize(DST))
