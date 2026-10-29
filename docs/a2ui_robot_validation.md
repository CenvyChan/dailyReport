# 原生 A2UI 机器人通道验证记录

验证日期：2026-10-27。目标：保留现有 A2UI JSON 卡片，由现有应用机器人发送，不依赖个人 dws 登录，不改为模板互动卡片。

## 结论及完成边界

已找到官方原生 AI 卡片 OpenAPI，并用部署环境当前应用的 access_token 收到该接口的必填参数校验响应。此前“只能走 dws”的判断不成立。

用户授权后，已通过当前应用 access_token 和 robotCode 向唯一已配置 FNS 群提交一张明确标注“测试”、不含业务数据的原生 A2UI 卡片。完整创建请求使用 flowStatus=FINISH，服务端返回 HTTP 200、整体 success=true，并且唯一 IM_GROUP 投递结果 success=true。由此确认当前应用可以不经 dws 直接投递原生 A2UI。群内实际显示的名称/头像及客户端渲染尚待用户确认；本次没有切换默认发送路径或部署生产代码。

## 官方接口证据

官方 Python SDK：alibabacloud-dingtalk 2.2.65，发布于 2026-10-15。

- 官方发行页：https://pypi.org/project/alibabacloud-dingtalk/2.2.65/
- 源码发行包 SHA-256：28e3ff2836c632db66f8cc7d4085b9434e186e8cae23ad56817057c55ad824cf
- 创建接口：POST /v1.0/card/ai/instances/createAndDeliver。
- 更新接口：PUT /v1.0/card/ai/instances/update。
- 请求头：x-acs-dingtalk-access-token。
- CreateAndDeliverAICardRequest 支持 a2uiMessages、protocolVersion、flowStatus、outTrackId、openSpaceId。
- 群投递模型 CreateAndDeliverAICardRequestImGroupOpenDeliverModel 明确包含 robotCode。
- a2uiMessages 为 JSON 字符串数组；原卡片的三条 JSON 消息序列化后传入，无需转换为 cardTemplateId 模板。

本地 SDK 证据位置（工作区相对路径，便于跨主机定位）：

- .tmp/dingtalk-sdk/alibabacloud_dingtalk/card_1_0/client.py：create_and_deliver_aicard_with_options、update_aicard_with_options。
- .tmp/dingtalk-sdk/alibabacloud_dingtalk/card_1_0/models.py：CreateAndDeliverAICardRequest、CreateAndDeliverAICardRequestImGroupOpenDeliverModel。

## 实际应用凭据探测

在 mesdevserver 的 daily-report-web 容器内，使用已配置的应用 #1 获取应用 access_token；令牌未输出、未保存到工作区。

只向官方创建接口提交一次空对象，未提交群 ID、卡片内容或 outTrackId，不进行消息投递，也不重试。

结果：

- 应用凭据获取 Token：成功。
- HTTP 400。
- code：MissingoutTrackId。
- message：outTrackId mandatory for this action.

这证明当前应用凭据发起的请求已到达原生 AI 卡片接口并触发参数校验，但服务端可能在参数校验之后检查权限，因此不能据此断言应用已拥有发卡权限。

探测原始脱敏结果：.tmp/robot-a2ui-permission-probe.json。

## 离线请求验证

使用官方 SDK 对包含现有三条 A2UI 消息、robotCode、protocolVersion 的候选创建请求执行 from_map / validate / to_map 往返：通过。解码后的 a2uiMessages 与当前卡片完全一致，不包含 cardTemplateId。

脚本：.tmp/verify_robot_a2ui_contract.py。
结果：.tmp/robot-a2ui-contract-validation.json。

SDK 模型的 validate 并不是服务端完整验证；离线通过不代表群投递、flowStatus 或客户端显示已通过。

## 用户授权后的真实群投递（已成功）

- 时间：2026-10-27 21:11:19（Asia/Shanghai）。
- 授权范围：当前已配置的 FNS 群，一张标注“测试”、不含业务数据的原生 A2UI 卡片。
- 实际目标：群配置 #1、应用 #1；发送前确认 FNS 仅有一条启用的群配置。
- 标题：【测试】机器人原生 A2UI 通道。
- 数据模式：test；全部金额和笔数为零，未读取业务审批数据。
- 内容：复用现有三帧 A2UI 布局，未转换为 cardTemplateId 模板。
- 认证：当前应用 access_token；投递身份字段为其 robotCode，没有使用 dws 或个人登录。
- flowStatus：FINISH；初次创建即完结，没有追加更新请求。
- 请求次数：1；重试：0。
- HTTP：200。
- 整体响应：success=true。
- 群投递：deliverResults 恰好一条，spaceType=IM_GROUP、success=true。
- outTrackId：payment-robot-a2ui-test-20261027-5f75d6af8368421c868fa647d076878d。
- 本地完整回执：.tmp/payment-robot-a2ui-test-20261027-5f75d6af8368421c868fa647d076878d.receipt.json。
- 服务端请求、尝试标记和回执：/app/data/payment_reports/payment-robot-a2ui-test-20261027-5f75d6af8368421c868fa647d076878d.{request,attempt,receipt}.json。
- 未验证项：群内实际机器人名称/头像、客户端渲染和交互；仍需用户在钉钉客户端确认。

## 两家公司报表事项的实际状态

代码范围：仅对以下付款申请公司的报表生成和调度增加限制；同步没有增加这两家公司白名单，其他申请公司的审批仍同步和保存。

| 表单申请公司 | 项目公司代码 | 项目公司原名称 |
| --- | --- | --- |
| 慈溪飞诺斯电子科技有限公司 | FNS | 飞诺斯电子科技有限公司 |
| 宁波汇慧电子有限公司 | NBHH | 宁波汇慧有限公司 |

卡片及 Excel 按公司分别生成，显示法定申请公司名。总笔数按创建时间统计本期全部流程，不按当前状态或审批结果排除；新增回归测试涵盖新建、审批中、完成、终止、驳回及期间外记录。

本次付款相关 65 项测试通过，Django check、git diff --check 通过。

只读检查部署环境的结果：

- 当前已执行到 integrations.0015，尚未执行组织路由迁移 0016。
- 目标公司的群配置目前只有 FNS；没有 NBHH 的独立群配置。
- 本次没有部署、迁移、修改映射或重启服务；仅在用户明确授权后投递上述一张测试卡片。

因此该事项是“工作区代码完成并验证”，不是“线上两家公司推送已生效”。上线还需部署代码、执行迁移、备份后修复组织映射，并配置 NBHH 接收群。

## 下一步

等待用户核对 FNS 群里的测试卡片是否显示为预期机器人，以及原有 A2UI 版式是否正常。服务端投递已确认成功，不再重复发送同一测试卡片。客户端确认后，再将机器人原生 OpenAPI 接入默认付款报表链路并做回归验证；两家公司数据路由的生产部署、迁移及 NBHH 接收群配置仍单独待办。
