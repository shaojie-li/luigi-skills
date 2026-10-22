# GitHub 项目管理标准

这是新项目的默认流程；已经明确的仓库约定优先。Projects 管理视图和工作状态，Issue 承载需求与验收，PR 承载实现。Projects 支持 Issue、PR 和草稿事项，草稿进入实际开发前建议转为仓库 Issue。

## 最小工作流程

1. 收集想法，先搜索已有事项；不确定的想法可以留在 Backlog。
2. 可执行工作建立 Issue，包含问题、目标、范围、验收标准、验证方法和依赖。
3. 加入用户指定的 Project，按实际字段配置状态和优先级。
4. 开始实施时进入 In progress；创建关联 PR 后进入 In review。
5. 验收通过且达到仓库约定的交付条件后进入 Done。未合并的 PR 不自动视为交付。

## 默认字段与视图

- Status：Backlog、Ready、In progress、In review、Done。仅在没有既有标准时采用。
- Priority：P0（阻断/紧急）、P1（当前核心）、P2（正常）、P3（候选）。避免所有任务都是最高优先级。
- Assignee、Labels、Milestone 使用 GitHub 原生字段；日期、迭代和复杂度按需要添加。
- 初期用一个按 Status 分组的看板和一个待办表格即可。阻塞原因写在 Issue，必要时复用 blocked 标签，不为它额外造一套状态机。

Issue 的表单字段是正文内容，不会自动变成 Project 字段。项目字段、视图及自动化需要在目标 Project 单独配置。模板不会创建标签、Project、Issue 或远程自动化。

## 拆分与完成标准

- 一个 Issue 对应一个可验收结果。实现中的小步骤使用 checklist。
- 需要独立负责人、状态或讨论的子工作使用 sub-issue，并记录依赖；不要把 checklist 当成独立 Issue 的完整替代品。
- PR 描述关联 Issue，说明行为变化和实际验证。仅在合并确实完成整个 Issue 时使用关闭关键词。
- 交付包含必要文档和失败路径；没有执行的验证明确列出，不伪造成功。

## 使用 GitHub CLI

先用 gh auth status 核对当前身份，使用 gh repo view、gh project list、gh project field-list 和 gh project item-list 读取目标。具体参数以当前版本的 --help 为准。写入 Projects 需要适用的项目权限；缺权限时说明最小需要的权限，不输出 token。

创建 Issue 或 PR 的多行正文使用临时文件和 --body-file。授权创建后保存真实 URL，再把 Issue 添加到对应 Project。更新字段前查实际 ID 与选项，不硬编码其他项目的 ID。操作部分成功时先回读状态，再决定是否重试。
