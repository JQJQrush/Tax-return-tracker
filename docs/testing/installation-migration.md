# 安装目录统一记录

日期：2026-11-10。

最新版已统一到 `D:\Tax-return-tracker`；桌面 Tax Return Tracker 快捷方式指向该目录的 run_windows.bat。客户资料仍在 `%LOCALAPPDATA%\TaxPrepLocal`。

目标目录65项测试通过；重复启动批处理退出码0，已核验复用同一实例。客户表数量、原件SHA256和数据库完整性检查通过。

备份位置：`D:\Backups\TaxReturnTracker\2026-11-10-unify`，包含客户完整备份、旧桌面报税项目完整ZIP及旧安装代码。

旧桌面报税项目内容已清理，但根文件夹被进程占用，尚未成功删除根目录；重启后检查并完成删除。其他三个兄弟项目保留。用户要求先结束以便重启，稍后继续。
