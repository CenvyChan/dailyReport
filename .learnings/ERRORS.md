# Errors 

- 2026-10-26: PowerShell startup failed in this environment and invoking the configured Git Bash executable routed to WSL; use cmd.exe as a fallback when both fail. 

## [ERR-20261027-CET] Windows command execution

- Status: resolved with workaround
- PowerShell startup failed with "Your Windows does not fully support CET". The exec command path also returned an incorrect Bash-existence result.
- Verified C:/Program Files/Git/bin/bash.exe with node:fs access and successfully ran it with node:child_process execFile, --noprofile --norc -c. Use that verified path without the default shell.
- Existing local test dependencies are in .tmp/payment-test-deps; use PYTHONPATH with C:/Python313/python.exe.
- Browser inventory failed with "Codex auth token is unavailable"; this does not establish the website login state.
- Pattern-Key: shell.nonzero-exit

## [ERR-20261027-RECONCILE] Organization reconciliation regression

- Status: resolved
- Replacing reconciliation validation inadvertently removed the existing `backup_dir = Path(options["backup_dir"])` assignment while preserving `backup_dir.mkdir`; the affected tests exposed the `NameError` immediately.
- Restore the assignment before creating the backup directory, then rerun all payment organization and delivery tests.
- Pattern-Key: reconcile.preserve-backup-setup


## [ERR-20261028-RESYNC-ARGS] 一次性审批同步脚本参数顺序

- Logged: 2026-10-28 (Asia/Shanghai)
- Status: resolved
- Area: operations
- Summary: 隔离刷新脚本错误地调用 save_approval(app, process, instance_id, raw)。生产接口实际为 save_approval(app, process, raw, instance_id, run=None, repair=False)，导致 raw.get 报错。
- Resolution: 通过生产镜像 inspect.signature 与现有命令确认接口，只修正一次性运维脚本；保留已完成的 K3Cloud 隔离结果，从审批阶段恢复，新增按月 ID 与详情缓存。失败路径恢复后台容器，线上数据库未切换、未推送。
- Related: .tmp/two-company-resync-20261028-1038/resume_staging.py
- Pattern-Key: operations.confirm-runtime-call-signature

- Follow-up for ERR-20261028-RESYNC-ARGS: 报表重算接口参数也需按生产签名使用 `force_regenerate`，不是 `force`；运行前集中核对所有运维调用的实际签名。恢复后台后若产生新自动同步，必须重建自最新线上库的隔离副本，不能仅改基线指纹后强行覆盖。


## [ERR-20261028-SUMMARY-QA] 采销汇总改版验证环境

- Logged: 2026-10-28 (Asia/Shanghai)
- Status: resolved
- Summary: 本地子进程测试须继承临时依赖 PYTHONPATH；复制旧验证脚本时应同步其快照结构（sections → charts），不能把过期测试夹具当作运行时缺陷。
- PDF QA: Chromium 的中文提取可能使用 CJK 兼容部首，按 NFKC 规范化后核对文字；Windows 默认 GBK 不足以打印这些字符，输出验证 JSON 文件。首版 PDF 口径说明溢出为孤立第二页，收紧打印图表高度与间距后重新渲染、逐页复核。
- Related: integrations/tests/test_operations_summary.py; .tmp/operations-summary-20261028-1205/inspect_pdf.py


## [ERR-20261028-SUMMARY-MOUNT] 非 root 验收容器读取受限目录失败

**Logged**: 2026-10-28T12:27:00+08:00
**Priority**: low
**Status**: resolved
**Area**: infra

### Summary
将 0700 发布目录整体挂载给 app 用户后，读取 0600 验收脚本报 PermissionError；验收尚未执行，未改动快照或发送消息。

### Resolution
保留发布目录 0700 和敏感 env 权限，只将不含凭据的脚本改为 0644 并单文件只读挂载至 /tmp/final_probe.py。修正后线上验收通过，投递账本不变且发送数为 0。以后优先使用单文件只读挂载，不扩大含敏感配置目录的权限。

### Metadata
- Reproducible: yes
- Related Files: .tmp/operations-summary-20261028-1205/final_probe.py
- Pattern-Key: docker.nonroot-restricted-mount

## [ERR-20261104-SHELL] Windows CET / Git Bash unavailable

**Logged**: 2026-11-04
**Priority**: low
**Status**: resolved
**Area**: infra

PowerShell startup failed with a Windows CET error. CMD confirmed the requested C:\Program Files\Git\bin\bash.exe does not exist. Use explicit CMD for simple execution and Node filesystem APIs; do not guess another Bash path.

## [ERR-20261104-ERP-NORMALIZE] ERP migration null header and test fixture

**Logged**: 2026-11-04
**Priority**: medium
**Status**: resolved
**Area**: tests

The new regression test caught None becoming the nonempty string "None", blocking purchase merged-header forward fill. Normalize null before testing emptiness. Two notification test fixtures omitted the existing mandatory send_at field; include it rather than changing the existing model.

## [ERR-20261104-ERP-STICKY] Scoped table header offset

**Logged**: 2026-11-04
**Priority**: medium
**Status**: resolved
**Area**: frontend

Browser QA measured the global sticky th top=58px inside the new horizontal overflow container, placing headers over the first task row. Override position:static only on .ea-history th. Verify header bottom is no lower than the first data row top at desktop width; do not alter global table styles.

## [ERR-20261104-ERP-ADMIN-FIXTURE] Admin test staff flag

**Logged**: 2026-11-04
**Priority**: low
**Status**: resolved
**Area**: tests

The new admin form test redirected because its create_user fixture set is_superuser but not Django admin required is_staff. Mark the administrator fixture as staff; do not relax application admin authentication.

## [ERR-20261104-ERP-CUMULATIVE-CAP] Bill query cumulative cap

**Logged**: 2026-11-04
**Priority**: high
**Status**: resolved
**Area**: backend

The source documentation states StartRow cannot bypass the bill-query 10000-row cap, while checking only an individual page misses five 2000-row pages followed by a truncated empty page. A regression reproduced that false completeness. Fail at the cumulative cap as well, requiring finer date/bill slices; report pagination remains independent.

## [ERR-20261104-SHELL-EXEC] Shell wrapper selected WSL

**Logged**: 2026-11-04
**Priority**: low
**Status**: resolved
**Area**: infra

Git Bash exists and direct execFile of the explicit bash.exe works; the PTY shell wrapper unexpectedly launched WSL. Use Node execFile for the verified Git Bash/SSH executables, without PowerShell shell forwarding.

## [ERR-20261104-DEPLOY-ENV-ORDER] Docker environment list ordering

**Logged**: 2026-11-04
**Priority**: low
**Status**: resolved
**Area**: infra

After incremental image recreation Docker reordered Config.Env, triggering a list-order assertion despite identical key/value pairs. Verify the environment mapping, not positional ordering. Read-only follow-up confirmed zero changed keys, identical original mounts/ports/commands and six running containers; no redeployment or rollback was necessary.
