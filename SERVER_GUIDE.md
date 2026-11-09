# Windows Server 部署与测试

本版本用于一台服务器上的小团队办公室内网。服务器承担全部识别、保存、数据库更新和程序更新；员工通过浏览器使用同一个地址。只运行一个 `server.py` 进程。请勿把 8765 端口转发到公网；异地访问应先接入办公室 VPN。

## 1. 本机快速验收

1. 关闭旧程序，双击 `run_windows.bat`。沿用 `%LOCALAPPDATA%\TaxPrepLocal`，或事先用 `TAXPREP_DATA_DIR` 指定程序目录之外的新测试目录。
2. 首次启动提示创建应用管理员 `admin`，输入并确认至少 12 字符的密码。密码不回显，也没有预设密码。
3. 网页打开后登录，进入“员工与服务器管理”，新建 `editor` 和 `viewer` 员工。
4. 使用普通/无痕窗口分别登录，用“载入合成演示资料”测试。不同窗口用相同浏览器配置会共享登录 Cookie；请使用独立配置或无痕窗口来区分员工。
5. 在两个编辑账号中打开同一条记录。甲保存后，乙从旧表单保存应收到冲突提示；乙需重新选择原页或刷新网页，核对最新内容后再编辑。仅后台轮询不会改写未保存表单。
6. 同样验证页面用途和应交资料项目的冲突。只读账号不能上传、保存、运行识别或管理员工，直接调用接口也会被拒绝。

`run_windows.bat` 是本机验收入口。正式服务器使用下述 `setup_server.ps1` / `start_server.ps1`，员工电脑只需保存网页快捷方式。

## 2. 服务器目录和迁移

建议目录（盘符按实际机器调整）：

| 内容 | 例子 |
|---|---|
| Git 程序仓库 | `D:\Tax-return-tracker` |
| 数据库、原件、识别结果 | `D:\TaxTrackerData` |
| TLS 证书和私钥 | `D:\TrackerTLS` |
| 程序生成的备份 | `D:\TaxTrackerData\backups` |

资料目录必须在服务器本机磁盘，并位于 Git 仓库之外。不要使用 SMB 共享、映射网络盘、OneDrive/Dropbox 同步目录来承载运行中的数据库。员工通过网页访问，不要给员工共享数据库文件夹。

迁移旧版资料：先停止上传/编辑并等 OCR 完成，下载旧版“备份全部工作资料”。在服务器恢复至**新的空目录**：

```powershell
.\.venv\Scripts\python.exe restore_backup.py --backup D:\Transfer\backup.zip --destination D:\TaxTrackerData
```

然后以此目录运行服务器安装。首次启动会补充账号及页面修订字段，保留客户资料和原有核对结果。旧版填写的审核人文本作为历史保留；服务器版新修改的审核人使用真实登录账号。升级前保留原备份和旧程序，不要同时运行两套程序访问同一目录。

## 3. 正式内网 HTTPS

准备 Python 3.10+、Git、可选的 Tesseract OCR（英文 `eng` 和方向 `osd`）。服务器应有固定内网地址和可解析的名称，例如 `taxserver.office.example`。

请由管理员提供与实际访问名称匹配、员工电脑信任的 TLS 证书链及 PEM 私钥；企业 CA 或受信任 CA 均可。私钥保存在服务器，不能提交到 Git。程序直接提供 HTTPS，至少 TLS 1.2，不依赖反向代理或浏览器忽略证书错误。

在服务器管理员 PowerShell 中，从仓库执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_server.ps1 -DataDir D:\TaxTrackerData -ListenAddress 0.0.0.0 -HostName taxserver.office.example -Port 8765 -Certificate D:\TrackerTLS\server-chain.pem -PrivateKey D:\TrackerTLS\server-key.pem -InstallStartupTask
```

脚本安装 Python 依赖，提示设置应用 `admin` 密码，生成本机 `server-settings.json`，并在指定时创建 `TaxReturnTracker` 开机任务。重复执行会重置应用 `admin` 密码并替换同名任务，须先停止运行中的程序。

创建开机任务时提示输入的是**专用 Windows 服务账号**的凭据，与网页员工账号分开。此账号须有“作为批处理作业登录”权限、读取程序/证书私钥及修改资料/日志目录的权限。建议使用普通专用账号；不需要以 SYSTEM 或管理员运行程序。由 Windows 管理开机任务凭据，配置文件不保存密码。

Windows 文件权限由服务器管理员设置：仅服务账号、受信任的备份账号和管理员可访问资料目录/私钥。备份包含财务资料、密码哈希与操作记录，同样需要限制访问并使用磁盘/备份加密。RAID 1 不替代独立备份。

手动启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_server.ps1
```

或使用已安装的开机任务：

```powershell
Start-ScheduledTask -TaskName TaxReturnTracker
Get-ScheduledTaskInfo -TaskName TaxReturnTracker
```

日志写入资料目录 `logs`，每次进程启动按日期选择日志文件。HTTP 日志不记录客户文件名、识别文字或请求内容。若任务启动失败，检查日志、任务结果、目录权限、证书有效性和账号的批处理登录权限。

防火墙只允许办公室需要访问的内网网段进入该端口。例如（用实际网段替换）：

```powershell
New-NetFirewallRule -DisplayName 'Tax Return Tracker LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress 192.168.1.0/24 -Profile Domain,Private
```

员工打开 `https://taxserver.office.example:8765`。浏览器出现证书错误时应修复名称/证书信任，不要忽略错误。`--allowed-host` 必须与浏览器地址中的名称和端口完全一致；直接使用 `server.py` 可重复传入多个允许地址。安装脚本配置单一主地址。

## 4. 没有证书时的合成数据内网测试

仅为联通性测试，可以显式允许明文 HTTP，并且只使用合成资料和测试密码：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_server.ps1 -DataDir D:\TaxTrackerTestData -ListenAddress 0.0.0.0 -HostName 192.168.1.20 -InsecureTestHttp
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_server.ps1
```

访问 `http://192.168.1.20:8765`。真实客户资料使用正式 HTTPS 配置。HTTP 测试不设置 Secure Cookie；HTTPS 自动设置，不能通过伪造转发头开启或关闭。

## 5. 员工账号和操作记录

- 管理员在网页新建、重置密码、调整权限或停用员工。密码至少 12 字符，使用独立盐值的 PBKDF2-SHA256（600,000 次），数据库不保存明文密码。
- 员工可自行改密、退出。改密/重置/权限修改/停用会撤销该账号所有会话。应用启动后所有人需要重新登录。
- 30 分钟没有提交操作或会话达到 12 小时后失效；后台数据轮询不会维持永久登录。未保存的输入只在当前页面内存中；过期后应重新登录再核对。
- 连续失败按用户名与连接 IP 限流，15 分钟窗口后可重试。错误信息不区分账号不存在或密码错误。
- 所有员工目前共享全部客户。只读账号可以查看和主动导出客户资料，不是禁止复制/截屏的权限模型。
- 管理页展示最近 500 条登录和成功写入事件；完整事件保存在数据库。历史金额修改沿用记录历史，可看到写入的真实审核账号。管理员的“读取全部备份”包含所有账号哈希；只有管理员可操作。

忘记管理员密码：在服务器停止程序后运行下述命令，以交互方式重置（不要把密码放在命令行或 Git 中）：

```powershell
.\.venv\Scripts\python.exe server.py --data-dir D:\TaxTrackerData --set-user admin --role admin
```

## 6. 备份、恢复和中央更新

管理员网页“员工与服务器管理 → 在服务器生成备份”把 ZIP 写到资料目录的 `backups`。备份含数据库、原始 PDF、预览、OCR 定位、员工账号/密码哈希、业务历史和服务器事件；不含程序、TLS 私钥、Windows 任务凭据及旧备份文件。识别过程中拒绝备份。客户端菜单仍提供管理员主动下载备份的入口。

另外定期复制完成的备份到另一设备/离线或受保护的备份目标；不要只在同一台服务器保留唯一副本。现有备份上限仍为 2GB、20,000 文件、单文件 128MB。

恢复时关闭程序，用 `restore_backup.py` 恢复到新目录，修改 `server-settings.json` 的 `DataDir` 后启动。恢复已有服务器备份会保留员工账号，启动时清除旧会话；恢复旧单机备份后需建立第一个管理员。可用 `--check-only` 先验证 ZIP。恢复不包含自动重建证书或 Windows 任务。

更新只在服务器执行：

1. 通知员工保存并退出，等待 OCR 完成，生成并验证完整备份。
2. 停止手动启动的程序（Ctrl+C），或 `Stop-ScheduledTask -TaskName TaxReturnTracker`。任务停止是进程终止，因此必须先等识别和编辑完成。
3. 在仓库执行 `git pull --ff-only`，再执行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。
4. 执行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`，通过后启动原任务。
5. 员工重新打开网页并登录，检查版本和客户资料。员工电脑无需 pull、安装依赖或升级程序。

升级失败时，先停止新程序，使用旧程序及升级前备份恢复到新资料目录，再修改配置指向恢复目录。不要把旧代码直接用于已经发生不兼容升级的数据库。

## 7. 本版验收边界

已提供单进程写入串行化和修订冲突检查，OCR 在服务器单队列运行；没有多服务器复制、高可用、按客户分配权限或互联网公开部署支持。浏览器会临时接收页面内容；主动下载/打印会在员工电脑留下文件，不能承诺终端零痕迹。

上线前在实际 Lenovo / Windows Server 2025 机器验证 HTTPS 信任、两台员工电脑访问、重启后自动运行、扫描件 OCR、备份恢复和实际并发性能。当前开发电脑测试不能替代这些目标环境验收。

参考：[Python TLS 文档](https://docs.python.org/3/library/ssl.html)、[OWASP 密码存储指南](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。
