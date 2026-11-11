# 本机正式启动位置

程序统一保存在 `D:\Tax-return-tracker`，双击其中的 `scripts/windows/run_windows.bat` 或桌面 `Tax Return Tracker` 快捷方式。

现有客户资料继续保存在 `%LOCALAPPDATA%\TaxPrepLocal`，与程序目录分开；迁移程序不新建空数据库、不重置员工密码。目录包括客户数据库、上传原件、页面图片和审核记录。

重复双击启动时，第二个进程先检测数据目录锁，再用实例标识验证本机已运行的工作台；验证成功后只打开浏览器，不重复启动、不重置会话。未能确认实例时显示提示并停止，不删除或绕过数据锁。

`server-instance.json` 为临时运行标识，不是客户资料或登录凭据；过期标识不会当成运行中的服务。健康检查仅允许本机连接，且仍检查允许的 Host。

本机已配置Windows登录自动启动及后台守护；关闭桌面启动窗口不停止服务。服务退出后自动恢复。需要手动停止时使用任务计划停止对应TaxReturnTracker-Local任务。Tesseract 位于 `C:\Program Files\Tesseract-OCR`，程序会自动检测。

`.venv` 中的 `python.exe`、`pip.exe` 等是运行依赖，并非旧版报税 EXE，不要删除。
