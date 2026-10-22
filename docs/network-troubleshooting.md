# Canvas 修好后仍连接失败：代理与 TLS 排查

日期：2026-10-22。本文记录一组经过脱敏的本地对照实验，不修改 Canvas 修复工具的适用范围。

## 两类错误分别处理

| 表现 | 本案例中的证据 | 处理结果 |
|---|---|---|
| `Crashpad_NotConnectedToHandler` | 开启指纹模拟后页面异常，精确 DLL 与上游 Canvas 缺陷匹配，修补后回归测试通过 | 修复共享内核中的 Canvas 指令 |
| `ERR_CONNECTION_CLOSED` / TLS 握手失败 | 独立请求经过同一代理也失败，不能只归因于浏览器指纹 | 使用已验证的另一条同地区代理，重启实例后恢复访问 |

`Crashpad_NotConnectedToHandler` 本身描述的是崩溃报告处理程序连接异常，仍需其他证据确认最初的崩溃原因。Canvas 补丁解决的范围是已验证构建中的内核缺陷，不会自动修好代理线路。

## 域名与真实地址的对照

同一代理、同一目标 HTTPS 站点的本地实验结果：

| 请求方式 | 结果 |
|---|---|
| 通过原代理，正常以域名作为连接目标 | 本地代理接受 CONNECT，随后 TLS 握手失败，未取得目标 HTTP 响应 |
| 同一代理，将网络连接目标改为查询得到的真实 IPv4 地址 | 原 URL、SNI、Host 和证书校验保持，目标返回 HTTP 200 |
| 原代理，临时调整客户端加密 DNS 和解析触发规则 | 未稳定恢复目标域名连接；实验配置已撤销 |
| 另一条同地区代理，正常使用域名 | 官网、后台公开登录页均返回 HTTP 200 |
| 修复内核、原指纹参数、新代理，独立浏览器配置 | 官网正文和后台登录表单均完整加载 |

这说明原代理的**域名目标连接路径**与实际地址连接路径存在行为差异。没有代理服务端日志，不能进一步确认是服务端解析、转发策略、IPv4/IPv6 选择或其他链路处理造成；也不能据此认定网站识别并封禁了虚拟指纹。

本机系统 DNS 曾返回 `198.18.*` 地址。[Mihomo 的 fake-IP 配置](https://wiki.metacubex.one/config/dns/)可以使用这一地址范围，因此看到这个地址本身不等于 DNS 损坏。本案例中，单纯调整客户端 DNS 也没有解决全部问题。

### 可复用的只读检查

以下示例使用 PowerShell 7。替换为实际的本地代理端口；不要把代理用户名、密码或完整配置粘贴进公开问题。

```powershell
$proxyUrl = 'http://127.0.0.1:12345'
curl.exe -sS --proxy $proxyUrl --noproxy "" --connect-timeout 8 --max-time 15 -o NUL -w "HTTP=%{http_code}; CONNECT=%{http_connect}\n" https://app.partnerboost.com/
```

`CONNECT=200` 仅表示本地代理接受了隧道请求，不证明目标站点的 TLS 握手成功。`HTTP=000` 是 curl 未取得目标 HTTP 状态的表示，不是站点返回的 HTTP 错误码。

查询当前真实地址，再保持原域名和证书校验进行对照：

```powershell
$dnsAnswer = Invoke-RestMethod 'https://dns.google/resolve?name=app.partnerboost.com&type=A'
$targetIpv4 = @($dnsAnswer.Answer | Where-Object { $_.type -eq 1 })[0].data
curl.exe -sS --proxy $proxyUrl --noproxy "" --connect-to ("app.partnerboost.com:443:{0}:443" -f $targetIpv4) --connect-timeout 8 --max-time 15 -o NUL -w "HTTP=%{http_code}; CONNECT=%{http_connect}\n" https://app.partnerboost.com/
```

这是诊断对照，不是把 CDN 地址永久固定进 hosts 的修复方案。域名可有多个地址，解析结果也会变化；一次成功不能证明所有地址或所有请求都正常。

## 配置切换后，确认实际运行参数

本机观察到：在运行中的实例里选中新代理后，代理栏和保存的配置已经更新，但现有 Chromium 进程的 `--proxy-server` 参数仍是旧的本地入口。仅刷新网页仍经过旧代理。

实际执行并验证的步骤是：

1. 在独立请求和独立浏览器配置中验证候选代理，确认目标页面能加载。
2. 核对出口地区；同地区的不同节点仍可能改变出口 IP。
3. 保存代理选择，然后通过 Ant Browser 重启该实例。
4. 检查新进程的 `--proxy-server` 是否指向预期入口。端口可能复用，因此还应结合实际代理绑定核对，而非仅凭端口不同作判断。
5. 重新测试官网和后台公开登录页，并核对原指纹参数、内核及用户数据目录。

本案例完成以上检查后恢复访问。Canvas 修复继续有效，原代理仍保留，但**换用可用节点不等于修复了原节点的服务端问题**。如果必须保留原出口 IP，应继续由节点运营方核查服务端解析和转发，不能把本次换节点结果当成保持原 IP 的修复。

## English summary

The Canvas renderer defect and `ERR_CONNECTION_CLOSED` were independent failures. The exact-build DLL workaround passed its regression tests, while an independent HTTPS request through the original proxy still failed.

Keeping the proxy, URL, SNI, Host header, and certificate validation unchanged, connecting to a freshly resolved IPv4 address succeeded. Domain-targeted connections through that proxy failed. Client-side DNS experiments did not provide a stable repair. These observations narrow the issue to the original proxy's domain-target connection path; without server logs, they do not prove the exact server-side cause or website fingerprint blocking.

A different proxy in the same country passed HTTPS and complete browser-load checks. It changed the exit IP. Selecting it in the UI updated the saved configuration but did not change the already-running browser's proxy argument; restarting the instance made the new route effective. Fingerprint settings, the browser core, and the user-data directory were preserved.

The original proxy was retained, not repaired. No account login was performed, and no credentials, exit IPs, private profile names, cookies, databases, or raw browser logs are published in this record.
