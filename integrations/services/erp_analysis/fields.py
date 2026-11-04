"""从移植包 Normalizer 原样提取的金蝶 FormId / FieldKeys / FilterString。"""

PURCHASEREPORTNORMALIZER = {
    "FORM_ID": "PUR_PurchaseOrderDetailRpt",
    "FIELD_KEYS": "FPurchaseOrgId,FBillNo,FDate,FSUPPLIERNAME,FMATERIALNAME,FDELIVERYDATE,FCurrencyId,FOrderQty,FOrderAmount,FReceiveQty,FReceiveAmount,FImportQty,FImportAmount,FReturnQty,FReturnAmount,FPAYQTY,FPAYAMOUNT,FPREINVOICEQTY,FPREINVOICEAMOUNT,FINVOICEQTY,FINVOICEAMOUNT,FRECPAYBILLAMOUNT,FPAYBILLAMOUNT,FSETADJAMOUNT,FPAYWRITOFFAMOUNT,FSPEWOFFAMOUNT",
}

PURCHASEENTRYNORMALIZER = {
    "FORM_ID": "PUR_PurchaseOrder",
    "FIELD_KEYS": "FBillNo,FPOOrderEntry_FEntryID,FDate,FSupplierId.FName,FMaterialId.FName,FQty,FRemainReceiveQty,FDeliveryDate",
    "FILTER_TEMPLATE": "FDate >= '%s' AND FDate < '%s' AND FDocumentStatus = 'C' AND FPurchaseOrgId.FNumber = '%s'",
}

RECEIVABLENORMALIZER = {
    "FORM_ID": "AR_receivable",
    "HEAD_FIELD_KEYS": "FBillNo,FDATE,FCUSTOMERID.FName,FALLAMOUNTFOR",
    "PLAN_FIELD_KEYS": "FBillNo,FRECEIVEAMOUNT,FNORECEIVEAMOUNT",
    "FILTER_TEMPLATE": "FDATE >= '%s' and FDATE <= '%s' and FSALEORGID.FNumber = '%s'",
}

INVENTORYREPORTNORMALIZER = {
    "FORM_ID": "HS_INOUTSTOCKSUMMARYRPT",
    "FIELD_KEYS": "FMATERIALBASEID,FMATERIALNAME,FMATERIALGROUP,FSTOCKId,FINITQty,FINITPrice,FINITAMOUNT,FRECEIVEQty,FRECEIVEPrice,FRECEIVEAmount,FSENDQty,FSENDPrice,FSENDAmount,FENDQty,FENDPrice,FENDAmount",
    "ACCT_SYSTEM_NUMBER": "KJHSTX01_SYS",
    "ACCT_POLICY_NUMBER": "KJZC01_SYS",
}

SALESREPORTNORMALIZER = {
    "FORM_ID": "SAL_OutStockInvoiceRpt",
    "FIELD_KEYS": "FSALEORGNAME,FBILLNO,FBILLTYPENAME,FDate,FSALESNAME,FCUSTOMERNAME,FMATERIALNAME,FREALQTY,FPrice,FALLAMOUNT,FISFREE,FRECQTY,FRECAMOUNT,FWriteOffAmount,FINVOECEQTY,FINVOECEAMOUNT,FRECEIPTAMOUNT,FJSWRITEOFFAMOUNT,FChargeOffAmount",
}

PRODUCTIONNORMALIZER = {
    "ORDER_FORM_ID": "PRD_MO",
    "REPORT_FORM_ID": "PRD_MORPT",
    "ORDER_FIELD_KEYS": "FBillNo,FTreeEntity_FEntryID,FDate,FStatus,FBillType.FName,FMaterialId.FName,FWorkShopID.FName,FQty,FStockInQuaSelQty,FNoStockInQty,FPlanStartDate,FPlanFinishDate,FStartDate,FFinishDate",
    "ORDER_FILTER_TEMPLATE": "FDate BETWEEN '%s' AND '%s' AND FPrdOrgId.FNumber = '%s'",
    "REPORT_FIELD_KEYS": "FBillNo,FDate,FMoBillNo,FMoEntrySeq,FMaterialId.FName,FInspectQty,FQuaQty,FFailQty,FScrapQty,FReworkQty",
    "REPORT_FILTER_TEMPLATE": "FDate BETWEEN '%s' AND '%s' AND FDocumentStatus = 'C' AND FPrdOrgId.FNumber = '%s'",
}

SUBCONTRACTNORMALIZER = {
    "ORDER_FORM_ID": "SUB_SUBREQORDER",
    "PICK_FORM_ID": "SUB_PickMtrl",
    "WIP_FORM_ID": "SUB_PPBOM",
    "ORDER_FIELD_KEYS": "FBillNo,FTreeEntity_FEntryID,FDate,FStatus,FBillType.FName,FSupplierId.FName,FMaterialId.FName,FQty,FStockInQty,FNoStockInQty,FPlanStartDate,FPlanFinishDate,FFinishDate",
    "ORDER_FILTER_TEMPLATE": "FDate BETWEEN '%s' AND '%s' AND FSubOrgId.FNumber = '%s'",
    "PICK_FIELD_KEYS": "FBillNo,FEntity_FEntryID,FDate,FSupplierId.FName,FMaterialId.FName,FParentMaterialId.FName,FSubReqBillNo,FAppQty,FActualQty,FSelPrcdReturnQty",
    "PICK_FILTER_TEMPLATE": "FDate BETWEEN '%s' AND '%s' AND FDocumentStatus = 'C' AND FSubOrgId.FNumber = '%s'",
    "WIP_FIELD_KEYS": "FBillNo,FEntity_FEntryID,FSupplierId.FName,FMaterialID.FName,FMaterialID2.FName,FSubReqBillNO,FMustQty,FPickedQty,FConsumeQty,FINCDefectReturnQty,FGoodReturnQty,FWipQty,FNoPickedQty",
    "WIP_FILTER_TEMPLATE": "FDocumentStatus = 'C' AND FSubOrgId.FNumber = '%s'",
}
