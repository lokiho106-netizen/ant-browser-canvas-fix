# Ant Browser Canvas 崩溃修复

[English](README.en.md)

针对 **Windows x64 fingerprint-chromium 150.0.7871.186** 的一个已验证二进制版本，提供可检查、可备份、可回退的本地修复工具。

适用于 Ant Browser 中开启指纹模拟后，部分页面触发 Canvas 像素读取，导致标签页崩溃的情况。崩溃页可能显示 `Crashpad_NotConnectedToHandler`，但这个错误本身并不能确定最初的崩溃原因。

**这是社区问题报告基础上的本地临时修复，不是 Ant Browser 或 Chromium 的官方发行版。** 项目不包含浏览器二进制文件，也不自动下载或上传文件。

## 修复范围

| 项目 | 支持范围 |
|---|---|
| 系统 / 文件 | Windows x64 / `chrome.dll` |
| 内核版本 | `150.0.7871.186` 的下列精确构建 |
| 文件大小 | `315028992` 字节 |
| 原始 SHA-256 | `6464a50a8f8eae824f85733b52bc42912405390ac7dcb2a7fda7228ea51cbbac` |
| 修复 SHA-256 | `2a2ca874e7944c9496888b07d56c8dd1ed76bf0a2b87c005874fe0a2729bbeed` |
| 指令文件偏移 | `0xC392046` |
| 指令修改 | `49 01 C0` → `49 89 D0`，三字节指令中实际改变两个字节 |

**版本号相同不代表文件相同。** 完整哈希或指令不匹配时，工具拒绝修复；没有强制绕过校验的参数。Linux、macOS、其他版本和其他构建不在本工具支持范围内。

## 快速开始

需要 Python 3.10 或更高版本，无需安装第三方 Python 包。下面的目录是示例，请改成实际安装位置。

### 1. 只读检查

```powershell
python canvas_fix.py inspect --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll"
```

`state` 的含义：

- `original`：精确匹配受支持的原始文件，可以修复。
- `patched`：已经修复，无需重复操作。
- `unsupported`：不支持的文件，不要套用此偏移。

### 2. 修复共享内核

先在 Ant Browser 中停止所有使用这份内核的实例。无需退出使用其他内核的实例。然后执行：

```powershell
python canvas_fix.py apply --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll" --backup-dir "D:\Ant-core-backups\canvas-150"
```

脚本先验证原文件、备份并核验备份，再修改指令，最后核验修复后的完整哈希。若安装目录需要管理员写权限，请使用有相应权限的终端。脚本不会自动结束浏览器进程。

成功后重新启动实例。**所有绑定到同一个内核目录的现有实例和新实例都会使用修复后的文件，无需逐个修改指纹参数。** 当实例引用其他目录里的内核副本时，需要单独检查那份文件。

修复不修改实例数据库、代理、Cookie、登录信息或指纹参数，也不关闭 Canvas 模拟、沙箱或证书校验。

### 3. 验证 Canvas

```powershell
python verify_canvas.py --chrome "D:\Apps\Ant Browser\chrome\chrome-150\chrome.exe"
```

验证页在本地运行。工具为两个示例种子分别新建独立配置，各进行 250 轮像素读取及 PNG 导出，检查页面完成、同种子结果稳定、不同种子输出不同。结果和诊断文件保存在被 Git 忽略的 `artifacts/` 目录；不会使用现有浏览器配置。

### 4. 回退

先停止使用该内核的实例，再使用 `apply` 输出的原始备份路径：

```powershell
python canvas_fix.py restore --dll "D:\Apps\Ant Browser\chrome\chrome-150\chrome.dll" --backup "D:\Ant-core-backups\canvas-150\chrome.dll.6464a50a8f8e.original"
```

回退同时校验当前文件和原始备份。回退后会重新引入原 Canvas 缺陷。重新下载或覆盖安装内核也会替换本地修复，届时应重新检查哈希，或使用上游正式修复版本。

## 问题说明与来源

根因、排查步骤和经过脱敏的验证记录见 [docs/findings.md](docs/findings.md)。指针计算缺陷和临时指令修复来自上游社区报告，本项目负责将其整理为带严格文件校验、备份、回退及测试的工具。

- [fingerprint-chromium 上游问题 #94](https://github.com/adryfish/fingerprint-chromium/issues/94)
- [同版 Windows Canvas 崩溃报告 #95](https://github.com/adryfish/fingerprint-chromium/issues/95)
- [Ant Browser 项目](https://github.com/black-ant/Ant-Browser)

`ERR_CONNECTION_CLOSED`、代理 TLS 握手失败、网站出口 IP 限制属于另外的排查方向，不能靠这个 Canvas 补丁一并解决。新增的[代理与 TLS 排查记录](docs/network-troubleshooting.md)提供了域名/真实地址对照、结论边界，以及切换代理后确认重启生效的方法。

## 测试与目录

```powershell
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -v
```

单元测试使用合成小文件，不分发或修改真实浏览器 DLL。关键校验没有使用会被 `python -O` 去掉的 `assert`。

```text
canvas_fix.py             精确构建检查、修复、回退
verify_canvas.py          独立配置下的本地 Canvas 验证
fixtures/canvas_probe.html
tests/                   完整性、备份、回退和拒绝误用测试
docs/findings.md          根因、证据和适用边界
```

MIT 许可证仅适用于本仓库新增的脚本和文档。Chromium、fingerprint-chromium、Ant Browser 保留各自的许可证和权利。
