# Tax Return Tracker — 多人服务器版 v0.7

## CRM 首页更新（2026-11-10）

登录后先进入客户总表，可按税年、工作阶段和关键词筛选；资料摘要可展开为项目列表。进入客户年度后管理概况、资料、文件路径、收费和历史，并通过“进入表格核对”打开原有核对工作台。已有客户新增年度时使用“新增年度”，保持长期客户档案关联。

原始资料文件夹、税表文件夹、ProSeries 客户报税文件路径分别登记；外部路径不会自动复制或备份，自动读取仍以已上传 PDF 为准。框架说明见上级目录 `CRM_FRAMEWORK.md`，实施验证见 `testing/CRM-framework-implementation.md`（上级目录）。旧客户资料兼容保留，同名客户不会自动合并。

服务器统一运行程序、OCR、原件存储和数据库；员工使用浏览器登录，无需安装 Python 或复制程序。程序更新只在服务器执行，员工重新载入网页即可。

## 先在目前这台电脑测试

双击 `run_windows.bat`（原桌面快捷方式继续可用）。第一次会在命令行提示创建 `admin` 密码，至少 12 个字符，输入时不显示字符；确认后自动打开登录网页。若旧版仍在运行，请先关闭旧窗口。

默认沿用 `%LOCALAPPDATA%\TaxPrepLocal` 的资料，并做增量升级。测试已有真实资料前先用旧版备份。可以设置 `TAXPREP_DATA_DIR` 指向程序目录之外的新资料目录来隔离测试。

1. 用 `admin` 登录，在“员工与服务器管理”新建 `editor` 和 `viewer` 账号。
2. 载入合成演示资料，用两个浏览器或一个普通窗口加一个无痕窗口分别登录。
3. 验证共享资料、只读权限、修改冲突和服务器备份。

## 部署到 Windows Server

完整步骤、HTTPS、开机启动、资料迁移、更新与恢复见 [SERVER_GUIDE.md](SERVER_GUIDE.md)。例如，管理员 PowerShell 中执行：

```powershell
.\setup_server.ps1 -DataDir D:\TaxTrackerData -ListenAddress 0.0.0.0 -HostName taxserver.office.example -Certificate D:\TrackerTLS\server-chain.pem -PrivateKey D:\TrackerTLS\server-key.pem -InstallStartupTask
```

例子中的服务器名称、目录和证书需要替换成实际值。安装脚本只在你运行时创建配置和可选启动任务；仓库本身不包含密码、证书或客户资料。

## 权限和共享范围

| 账号 | 权限 |
|---|---|
| 管理员 admin | 全部客户、编辑、员工管理、操作记录、全部资料备份 |
| 编辑员工 editor | 查看和编辑全部客户、上传资料、运行识别、导出 |
| 只读员工 viewer | 查看全部客户、查看历史、下载客户导出；不能修改或上传 |

目前所有启用员工共享所有客户，不包含按客户分配权限。导出/打印由用户主动下载，会在员工电脑产生文件；程序不把数据库或原件目录同步到员工电脑，也不使用浏览器 localStorage 保存资料。

## 已实现

- 密码哈希、员工账号创建/重置/停用，保护最后一位管理员。
- HttpOnly / SameSite 会话 Cookie；HTTPS 下使用 Secure Cookie；CSRF、Host 和 Origin 检查。
- 登录失败限流；30 分钟没有提交操作或最长 12 小时后重新登录；后台读取刷新不延长会话。
- 退出、改密、账号权限修改/停用后会话失效；服务器重启后所有员工重新登录。
- 记录、资料待办和页面用途的修订冲突检查，阻止旧页面覆盖其他员工保存结果。
- 审核人和测试人由真实登录账号写入；管理页可查看最近 500 条登录与成功写入事件。
- 管理员可将完整备份直接保存在服务器资料目录的 `backups` 子目录。
- 保留现有本机 PDF、OCR、核对、交接、底稿和恢复功能。业务使用说明见 [LOCAL_GUIDE.md](LOCAL_GUIDE.md)、[TESTER_GUIDE.md](TESTER_GUIDE.md)。

## 验证与边界

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

验证记录见 [TESTING.md](TESTING.md)。这是一台服务器、一个程序进程的小团队内网版本；OCR 队列按顺序处理，不是多节点/高可用平台。不要使用共享盘承载 SQLite，也不要启动多个服务实例访问同一资料目录。真实员工并发数量、Windows Server 开机任务和正式证书需在目标服务器验收。

该工具整理和核对资料，不计算税额、不直接录入 ProSeries，也不电子申报。
