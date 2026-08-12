Attribute VB_Name = "模块3"
' 两个选项按钮宏:把基础信息表中内销/外销客户粘到"新增订单查询表"F5
' 注意:目标表"新增订单查询表"在当前文件里已不存在,要让宏生效需建该表或改字符串
Sub OptionButton4_Click()
    Dim srcSheet As Worksheet, destSheet As Worksheet, srcRange As Range
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="内销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub

Sub OptionButton6_Click()
    Dim srcSheet As Worksheet, destSheet As Worksheet, srcRange As Range
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="外销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub
