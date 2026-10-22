---
name: github-projects
description: 使用 GitHub Projects 与 Issues 规划、拆分和跟踪软件项目，建立或沿用 Issue、PR 和看板标准。用于用户要求项目管理、任务拆分或进度同步时；不因普通代码修改自动创建远程事项。
---

# GitHub 项目管理

先读取仓库已有的 Issue/PR 模板、项目规则和关联 Projects，沿用已有语义。默认规范见 [项目管理标准](references/project-management.md)，不要用默认规范覆盖用户已确认的流程。

Projects 是组织层：条目可以引用 Issue、PR，也可以是 draft issue。Issue 是可执行工作及验收的事实来源；PR 是实现变更。小步骤用 checklist，需独立负责人、状态或讨论的子工作用 sub-issue；不为每个代码动作创建 Issue。

开始前明确仓库 owner/name 和 Project 所属用户或组织及编号，不能从同名仓库猜 Project。优先通过已连接的 GitHub 工具或 gh 读取；命令语法以当前 gh help 为准。只有实际需要写入时才检查对应权限，不请求无关 token scope。

准备任务时记录问题与用户价值、范围和非目标、验收标准、关键失败路径、验证方式及依赖。标题表达结果，避免“优化一下”。先搜索同类 Issue 和 Project item，防止重复。Issue 表单正文不自动映射为 Project 自定义字段，状态和优先级需要另行设置或使用已配置自动化。

Issue/PR 模板由 luigi-starters 仓库维护，通过 `lt add preset github-projects --cwd .` 安装；保留已有自定义模板，不直接覆盖同名目标。模板里不假定仓库已存在特定标签。

远程操作依照用户本次授权：只要求规划时输出可审查的任务；明确要求创建或同步时，在已确认范围内执行，不重复索要相同授权。创建后记录真实 URL，更新 Project 字段时使用实际查询到的 ID/选项；失败保留已完成的链接，不盲目重试重复创建。不要自动关闭 Issue、合并 PR 或修改账号权限。

完成状态必须有证据：实现完成、验收与必要检查通过后才能标记 Done。PR 已打开但尚未合并通常处于 In review；若已有流程不同，按项目约定。阻塞时标记原因、依赖和解除条件，不用 Done 掩盖阻塞。

官方依据：[Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)、[Issue 表单](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)、[gh project](https://cli.github.com/manual/gh_project)。远程创建不属于安装此 Skill 的隐含授权。
