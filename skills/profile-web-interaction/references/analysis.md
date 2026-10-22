# 指标解释与判断边界

- `recording.status` 必须为 passed，步骤结果和预期一致，才可作为正常场景样本。失败录制只用于排障。
- `automation_interval_ms` 是带标记的自动化步骤区间，包含定位等待和浏览器通信，不是 INP。异步工作可能发生在步骤区间之后；用原始时间线核对，不能强行归因。
- CPU `self_ms` 是采样估计的函数自身耗时；`inclusive_ms` 包含后代，禁止父子相加。采样次数不是调用次数或组件渲染次数。出现乱序采样时间时按累计时间排序计算区间，并在摘要提示；约 1 ms 的采样可能遗漏很短的函数。
- `long_tasks` 统计由步骤标记识别出的目标渲染主线程中至少 50 ms 的任务，不合计所有进程，也不重复累计外层 ThreadController 和内层 RunTask。没有主线程标记时，统计不可用，不等于没有长任务。
- Layout、UpdateLayoutTree、Paint 各自计算区间并集，三类指标可能嵌套，不能直接相加当成总成本。
- React Components 轨道的 span 包含后代成本，可能受记录阈值、构建模式与 React 版本影响。span_count 不是 commit 数，也不保证记录每一次组件调用；同名组件可能是不同实例。Changed Props 是线索，不是必须 memo 的判决。
- 源码位置从 CPU 调用帧通过当前 source map 转换；行列在摘要中均为 1 起始。未映射时明确标注 generated 位置，不把 URL 自动猜成用户本地绝对路径。URL 无源码映射也可能以 .tsx 结尾，不能据此当作原始行号。map 为录制后保存，避免录制期间热更新，确保对应版本一致。
- 开发构建、Strict Mode、自动化驱动和录制都有开销。记录浏览器版本、构建标签和视口；比较时固定设备、场景、数据规模和构建方式。场景少时报告样本量，不凭少量点击给出有统计意义的 p95。

先检查状态归属和无关昂贵子树，再考虑缓存。少量简单按键随父组件更新，不单独构成性能缺陷。引入 memo、回调缓存或额外组件结构前，要说明实际成本与收益；优化后用同一场景复测。正式性能结论需要合适的生产/profiling 构建，不能直接外推开发模式耗时。

## 官方参考

- [Playwright Python CDPSession](https://playwright.dev/python/docs/api/class-cdpsession)：性能采集使用 CDP，非 Playwright Trace Viewer 录制。
- [React Performance tracks](https://react.dev/reference/dev-tools/react-performance-tracks)：组件和调度轨道的可用性与开销。
- [React Profiler](https://react.dev/reference/react/Profiler)：子树渲染耗时与 profiling 构建。
