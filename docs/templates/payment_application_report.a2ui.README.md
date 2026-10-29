# 付款申请报表 A2UI 接入

正式报表以当前企业应用的机器人身份，直接调用钉钉原生 A2UI 接口。不需要 dws、个人 OAuth 登录、互动卡片模板或 card_template_id。

## 配置与范围

- 企业应用须配置 AppKey、AppSecret、robot_code，机器人须能访问目标群。
- 群配置中的“推送公司”支持多选；同一个群可以接收多家公司的独立报表。来源应用只需配置一次，并通过申请公司映射复用。
- 同步保持全量；付款报表只允许 FNS（慈溪飞诺斯电子科技有限公司）与 NBHH（宁波汇慧电子有限公司）。
- “本期发起流程数”按创建时间统计期间内所有流程，不限制审批状态及结果；不代表实际付款。

## 部署验收（不发送消息）

```bash
python manage.py send_payment_report week --company FNS --dry-run
python manage.py send_payment_report week --company NBHH --dry-run
python manage.py send_scheduled_payment_reports --dry-run
```

默认输出 /app/data/payment_reports 中的独立 Excel 与 .a2ui.json；Excel 汇总和明细均区分申请公司。

## 发送与回执

发送先预检机器人配置，再上传 Excel，随后单次 POST /v1.0/card/ai/instances/createAndDeliver，以 FINISH 创建完整静态卡片，最后发送机器人 Excel 附件。

使用当前应用 token 和明确的 robotCode；a2uiMessages 逐帧编码为 JSON 字符串。不自动退回 dws 或文本，只有显式 --no-card 才使用文本。

请求前写入 .a2ui.receipt.json 的 outTrackId；成功必须同时满足顶层成功、追踪 ID 一致、唯一目标群投递成功。回执保存原始响应与完结状态。网络异常、超时、缺失或错误投递回执均报错且不自动重试。

结果未知时先核对群消息和 outTrackId。卡片成功但附件失败也不能盲目重跑，避免重复卡片。定时投递另有按群、周期和发送日的去重记录。

## 模板

payment_application_report.a2ui.json 为三帧原生协议模板，包含图表和收款人汇总；正式命令绑定实际数据、生成独立 surfaceId。send-content 示例只是预览，不是生产业务数据。
