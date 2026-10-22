# luigi-skills

维护Skills、附属资源和脚本，通过 [Luigi CLI](https://github.com/shaojie-li/luigi-tools) 按需安装。与其他资产仓库独立维护、构建、检查和发布。

```bash
pnpm install --frozen-lockfile
pnpm build
pnpm check
```

修改源码后提升 catalog.json 中对应资产的版本，再运行 build。构建拒绝覆盖已有同名同版本内容；registry/index.json 保留历史版本，registry/items 使用 SHA-256 命名正文。分发文件与源码、锁文件一起提交。check 只读检查分发产物与源码是否一致，不自动修复过期文件。

无需安装或导入 CLI 的源码；构建脚本直接输出 v2 索引与单资产快照。requires 使用 type/name 与精确版本；修改依赖也要提升当前资产版本。各仓库自己的工具依赖仅供开发，不复制到消费者项目。

公开下载地址将在分发文件推送后可用。仓库创建和本地构建不等于已经发布。CLI 的 --source 可以直接指向本仓库 registry/index.json；模板跨仓依赖需要组合来源配置，见 [来源协议](https://github.com/shaojie-li/luigi-tools/blob/main/docs/cli.md)。

check 包含 profile-web-interaction 的 Python 回归测试。

## UI 资产与 Skill 的关系

UI 组件在 luigi-ui 维护，本仓库不保存可安装组件清单。使用组件前通过配置来源的 `lt list` 或 registry 索引确认可用资产，不能从历史示例推断它仍可安装。

`web-ui` 指导组件发现、主题、组合和交互实现；`forms` 与 `tables` 分别指导采用 React Hook Form、TanStack Table 的项目。它们不依赖某个同名 UI 资产，撤回 UI 组件不意味着删除对应领域的 Skill，也不授权删除消费项目已有源码。

## 代码规范与检查工具

规范、Agent 指导和自动检查分工如下：

| 入口                                                                                                                                | 职责                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 目标项目的 `AGENTS.md`、`docs/coding-standards.md`                                                                                  | 项目实际采用的编码约束，执行任务时先读取                                                      |
| [`web-ui`](skills/web-ui/SKILL.md)                                                                                                  | React 命名、组件拆分、状态归属、主题和交互约束                                                |
| [`forms`](skills/forms/SKILL.md)、[`tables`](skills/tables/SKILL.md)                                                                | 对应技术栈的状态管理、错误处理和验证规则                                                      |
| [code-quality 预设的编码规范](https://github.com/shaojie-li/luigi-starters/blob/main/presets/code-quality/docs/coding-standards.md) | 完整规范来源，覆盖 TypeScript、模块边界、React、可访问性、性能和提交约定                      |
| [code-quality 预设](https://github.com/shaojie-li/luigi-starters/tree/main/presets/code-quality)                                    | 分发 ESLint、Prettier 和提交检查配置；`tooling/react-naming.ts` 只是其中的 React 命名检查规则 |

安装 Skill 不等于安装 ESLint 或启用质量检查。既有项目可按需通过 `lt add preset code-quality --cwd /path/to/project` 接入预设，遵循其安装说明和已有文件冲突保护；本仓库不复制维护另一份完整规范或检查配置。

luigi-skills 自身使用 TypeScript strict、ESM 和 pnpm；当前 `pnpm check` 包含 Prettier、根目录 scripts 的 TypeScript 检查、分发一致性、TypeScript 测试和 Python 回归测试，尚未接入 ESLint。Skill 中的设计与行为约束由 Agent 执行和评审核对，不能用静态检查通过代替实际行为验证。

## 发布前审查

[`release-with-codex`](skills/release-with-codex/SKILL.md) 使用 Codex CLI 的 `gpt-6-luna` 只读检查真实 diff 和未推送提交，提出 Conventional Commit 消息；执行仓库检查后，由调用 Skill 的 Agent 在用户授权范围内提交、普通 push 并核验已有 CI 的发布结果。它不重复计算版本、打 tag 或 npm publish，也不改写已有提交。

需要 Node.js 24+、Git、已登录且可使用该模型的 Codex CLI，以及用于 GitHub 状态检查的 gh。非 main、上游分叉、没有待提交/推送内容时停止；干净但有未推送提交时继续审查。分发索引推送后，可通过 `lt add skill release-with-codex --agent codex --cwd /path/to/project` 安装；尚未推送时添加 `--source /path/to/luigi-skills/registry/index.json` 使用本地索引。

安装后调用：`使用 $release-with-codex 检查并发布当前项目`。只需建议时说“使用 $release-with-codex 预览提交和发布影响，不提交或推送”。维护此 Skill 的仓库只分发资产，没有 npm 自动发布流水线；不要在本仓库调用它来强行发 npm 包。

状态检查脚本的回归测试已纳入 `pnpm check`，覆盖分支、上游、部分暂存、未跟踪文件变化、发布标签同步和失败停止。Luna 的判断仍需要结合具体证据核对，不能把格式检查或模型建议当作提交语义必然正确的证明。

2026-10-22 使用 Codex CLI 0.160.0、gpt-6-luna 实测：当前 CLI 文档改动建议 docs 类型且版本影响为 none；隔离仓库中将新增 multiply 公开函数写成 docs 提交时，审查指出应为 feat 并返回 blocked。测试没有对真实仓库提交、推送或发布。

MIT License。
