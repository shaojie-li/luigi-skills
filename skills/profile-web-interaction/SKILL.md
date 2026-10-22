---
name: profile-web-interaction
description: 录制 Web 交互的 Chromium 性能数据，用 Python 提炼 CPU 热点、React 轨道和可用的源码位置，辅助判断是否值得优化。适用于交互卡顿、状态更新影响范围和优化前后比较；普通 UI 实现或仅检查功能正确性时不触发。
---

# Web 交互性能录制

使用本 Skill 的 Python 脚本完成采集和摘要，不临时重写录制器，不把完整 trace 加载到模型上下文。先明确目标 URL、需要复现的交互和成功结果。脚本仅支持 Chromium；产物是浏览器 Performance trace 和 CPU 采样，不是 React DevTools Profiler 导出。React 轨道取决于目标 React 版本和构建模式，缺失时明确报告。

## 首次使用与依赖

目标项目只需启动网站，不需要添加 Playwright、Python 包或修改 package.json、锁文件。要求本机 Python 3.10+。此 Skill 的 Python 实现是为独立分发选择的例外，不改变目标项目的语言约定。

先确定本 Skill 的绝对路径 `<skill>`。虚拟环境 `<venv>` 放在 Skill 和目标项目之外，例如用户缓存目录下的 `agent-base/profile-web-interaction/venv`，可跨项目复用。所有脚本路径相对于本 Skill，不依赖执行时的工作目录。

首次使用执行：

```text
python3 <skill>/scripts/setup.py --venv <venv>
```

该命令创建独立虚拟环境，安装 requirements.txt 中的 Python Playwright 和该环境自己的 Chromium（`<venv>/browsers`），不使用用户项目的 node_modules，不要求系统安装 Node.js，也不创建 sh 入口。Python Playwright 自带运行所需驱动。首次安装需要网络和磁盘空间，成功后可复用；安装失败显性退出并保留环境，修复网络等原因后用同一命令重试。Linux 缺少浏览器系统库时报告具体缺失，不擅自执行需要管理员权限的系统安装。

后续命令中的 `<python>` 是 `<venv>/bin/python`，Windows 为 `<venv>/Scripts/python.exe`。只做已有录制的摘要时，系统 Python 即可，不需要 Playwright 或浏览器。录制器不自动安装依赖：缺少 Playwright 或浏览器会给出提示并非零退出。

## 场景与录制

根据实际页面语义编写场景 JSON；不要从示例猜测页面一定有某个控件。只执行用户授权范围内的交互；例如验证充值入口不等于授权真实付款。必要时使用测试环境。

```json
{
  "steps": [
    {
      "id": "open-dialog",
      "action": "click",
      "role": "button",
      "name": "新建任务"
    },
    {
      "id": "fill-title",
      "action": "fill",
      "scope": { "role": "dialog", "name": "新建任务" },
      "role": "textbox",
      "name": "任务名称",
      "value": "性能验证"
    }
  ]
}
```

支持 `click`、`fill`、`press`、`expect_text`，后三种需要字符串 `value`；均通过精确的 role/name 定位，可用 scope 限定区域。id 必须唯一。用 `expect_text` 验证操作结果；复杂流程可以分成多个明确场景，不执行场景文件中的任意代码。

```text
<python> <skill>/scripts/record.py --url http://localhost:5173/ --scenario <scenario.json> --output <new-output-dir> --seconds 10 --build-label development
<python> <skill>/scripts/summarize.py <new-output-dir> --top 5
```

- 页面加载后默认预热 1000 ms，再开始录制。`--seconds` 默认 10，上限 120；按场景顺序执行一次，完成后录到窗口结束，不自动重复有副作用的步骤。场景超时即失败，不能把未执行的步骤当成成功。可用 `--warmup-ms` 调整预热、`--headed` 显示专用浏览器。
- 启动的是新浏览器上下文，不继承用户登录态；当前场景不支持跨导航页面或 iframe，登录/导航应在支持的测试页面准备好后录制。不支持的场景明确报告，不降低断言或忽略找不到的控件。
- 输出目录必须尚不存在，不覆盖已有录制。失败时保留已有原始数据和 recording.json 中的错误，返回非零状态；缺少原始文件的失败录制可能无法提炼摘要。
- source map 仅获取 CPU profile 涉及脚本的内联 map 或同来源 map，支持普通 v3；不抓取外部来源、indexed map 或不可用 map 时保留原始位置与限制说明。位置不保证一定指向根因。

## 分析与交付

先读取 `summary.md`，需要关键统计、React 轨道或证据索引时读取 `summary.json`。默认仅保留 5 个 CPU 热点及最多 5 个应用热点（节点去重）、3 个最慢步骤和 3 个最慢 React span；保留总数和样本量，不复制全部步骤、重复属性和 generated 调用帧。完整步骤在 recording.json，详细帧按索引读取原始文件。按 [分析边界](references/analysis.md) 解释数据；有疑点时用 JSON 工具只提取对应事件或调用帧，不读取整份录制给模型。

原始产物包括 `trace.json`、`cpu-profile.json`、`source-maps.json`、`scenario.json`、`recording.json` 和最终截图。原始文件保留在输出目录，可能包含页面 URL 和调试信息，不自动上传或提交。摘要已存在时拒绝覆盖。

结论给出场景是否成功、热点证据、是否值得优化、最小建议及未验证项；没有明显成本时允许明确“不建议优化”。单次录制不能证明生产性能，决定改代码时应对相同环境和场景复测。分析请求不自动授权重构业务代码。
