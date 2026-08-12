Attribute VB_Name = "模块1"
' Button1_Click: 把基础信息表中"内销"客户筛选后粘到 数据表(Sheet1)A1
' 注意:原文件目标表名写的是"Sheet1"(指数据表);若当前数据表名是中文"数据表",请改下面的字符串
Sub Button1_Click()
    Dim srcSheet As Worksheet, destSheet As Worksheet, srcRange As Range
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("Sheet1")          ' 如需指数据表,改 "数据表"
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="内销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("A1").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub
