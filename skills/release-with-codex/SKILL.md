---
name: release-with-codex
description: 发布前通过 Codex CLI 的 GPT-6 Luna 审查 diff 与 Conventional Commits 语义，检查 main 分支和待推送状态，执行仓库验证并沿用现有 CI 发布。用于用户要求审查发布、提交并发布时；普通代码修改不自动提交或发布。
---

# 审查提交并发布

为个人维护的 main 分支发布减少提交分类错误。版本计算、tag 和 npm 发布由已有流水线负责，不再实现发布引擎。依赖 Node.js 24+、Git、已登录的 Codex CLI；GitHub 流水线还需 gh。模型固定为 `gpt-6-luna`，不可用时显性停止，不静默换模型。AI 审查是辅助判断，不保证理解全部兼容性影响。

用户明确调用本 Skill 要求“发布/提交并发布”，即授权对当前仓库中已明确的变更执行检查、提交和普通 push；只要求“检查/预览”时不提交、推送或发布。创建、安装或自动匹配本 Skill 本身不授予发布权限。已有授权有效时不重复确认。默认将当前目标仓库中所有未忽略的改动纳入本次发布，包括已暂存、未暂存、部分暂存和未跟踪文件；自动完成全量审查、暂存和提交，不因已有暂存边界再次询问。用户明确限定路径或只要求检查时遵循其限定；真实凭据、未知敏感文件、冲突或无法审查的内容仍须显性停止，不为了工作区干净而删除、隐藏或提交这些内容。

## 统一发布边界

本次发布以目标仓库的全部未忽略改动及已有未推送提交为整体，文档、测试、配置和源码一视同仁。原有暂存区不是边界；部分暂存文件的剩余内容、新文件和删除文件均须覆盖。用户明确限定范围时才缩小。

可以按意图拆成多个本地提交，但不能分批 push：先审查、验证并提交整批改动，确认暂存区、未暂存区和未跟踪列表全部为空，再用一次普通 push 推送所有未推送提交。文档或测试不单独触发版本，也不能因此留在本地；由现有 CI 依据整批提交的最高影响决定统一版本或本次不发新版本。不为强行发版伪造 fix、空提交或手动改版本。

提交或 Hook 产生的新改动也纳入同一批次，审查并提交后再推送；不得只完成首个提交、留下收尾文档，或先推送代码再补推测试。推送后绑定最终 HEAD 核验一次完整流水线及发布结果。

## 1. 判定是否有工作

读取目标仓库的 AGENTS.md、提交规范、发布文档和实际 CI。将 `SKILL_DIR` 设为本 Skill 的绝对路径，`REPO` 设为目标仓库根目录：

```bash
node "$SKILL_DIR/scripts/release-state.ts" "$REPO"
```

脚本只读取文件并 fetch 上游 main 和发布标签，不修改工作区、暂存区或本地分支，不 pull 或覆盖已有标签。退出码 0 且 `status=ready` 才继续；2 表示停止并解释 `reason`，1 表示工具或网络失败，不能猜测状态：

- 非 main（含 detached HEAD）、没有明确的远端 main 上游：停止，不自动切换或设置上游。
- 合并/变基未完成、冲突、上游领先或分叉：停止，不自动 rebase、reset 或强推。
- 无工作区改动且没有未推送提交：停止，告知“没有待提交或待推送内容”。**干净但 ahead > 0 仍需审查并推送。**

保存输出中的 HEAD、upstream SHA、fingerprint、pendingCommits 和 changedPaths。核对 remote 与发布仓库一致。现有 CI 已负责版本/tag/发布时复用；缺失时报告“未配置自动发布”并停止，不临时 npm publish 或自动搭建新流水线。存在运行中的发布或此前未完成发布时先报告状态，按仓库恢复文档单独处理，不删除标签。

## 2. 用 Luna 审查真实改动

调用前查看 diff stat、暂存状态及未跟踪文件名。发现疑似凭据、个人数据、二进制或无法审查的大文件时先排除或澄清，不能静默忽略后声称全量审查通过。

使用 [审查提示词](references/review-prompt.md) 和 [输出契约](references/review.schema.json)，临时保存输出：

```bash
REVIEW_DIR=$(mktemp -d)
codex exec --ignore-user-config --ephemeral \
  --sandbox read-only --model gpt-6-luna \
  -c 'approval_policy="never"' -c 'model_reasoning_effort="medium"' \
  --cd "$REPO" \
  --output-schema "$SKILL_DIR/references/review.schema.json" \
  --output-last-message "$REVIEW_DIR/review.json" \
  - < "$SKILL_DIR/references/review-prompt.md"
```

子进程只审查，不调用本 Skill、commit、push、改文件或操作远程服务。读取 JSON，核对 reviewedHead、reviewedUpstream、reviewedPaths 以及 pendingCommits 的 SHA 集合与状态脚本一致。输出缺失、非法或有遗漏时停止并说明证据，不执行提交或推送。decision=blocked 或 blockers 非空时，若只是提交范围混杂，自动按明确意图拆分后分别重新审查；可确定且在授权范围内的本地问题先修复再审查，不把这些可处理问题变成再次确认。无法解决的真实阻塞才交还用户。任何范围必须 decision=ready 且 blockers 为空才能提交；未推送提交的 messageMatchesDiff 为 false 时停止，不改写已存在的提交。不要自动改写已有提交、squash 历史或新增空 fix 提交掩盖错误。

多项独立意图应主动规划多个清晰提交，覆盖全部已授权改动，不把拆分提交变成再次确认发布范围的理由。每个提交范围分别审查，推送前必须覆盖整次发布的所有改动及未推送提交。

向用户简述实际行为变化、建议完整提交消息、预计版本级别及原因。遵循仓库 commitlint；fix 修复已有行为，feat 新增能力，破坏兼容性必须写 `!` 和 `BREAKING CHANGE:` 页脚，说明受影响用法与迁移方式；纯文档/测试/维护不伪装成 fix 强行发包。根据整个待发布范围判断版本影响，不漏掉此前未发布的提交。

Release Notes 继续由已有生成插件从提交消息生成。luigi-tools 的 conventionalcommits 预设将 feat、fix 和 BREAKING CHANGE 分别整理为 Features、Bug Fixes、不兼容变更说明；不另用模型重写已生成的 Release。提交标题写具体用户行为，页脚写清影响，避免只有“优化”“更新”。

## 3. 验证、提交与推送

用 `release-state.ts "$REPO" --expect "<保存的 fingerprint>"` 确认状态未变，再运行仓库规定的检查；luigi-tools 为 `pnpm check`，涉及安装/分发逻辑时补充 `pnpm smoke`。检查失败停止，不跳过 Hook 或降低断言；检查生成新改动时重新审查。只预览时在此报告建议并结束。

默认不保留原有暂存边界：以已审查的全部 changedPaths 为清单，使用 `git add -- <路径...>` 纳入所有改动，包括部分暂存文件剩余内容、新文件和删除文件，不用 `git add .`。用户明确指定子集时只暂存该子集。多个提交可以按审查通过的计划分批暂存，但本次发布结束前必须全部提交，不能只提交旧暂存区后留下其余改动。

暂存前再次核对 fingerprint；暂存后检查 cached diff 与审查内容一致，使用消息文件配合 `git commit -F`，不把模型输出拼接成 shell 命令。保留正常 Hook；Hook 修改内容后复核实际提交的 diff，必要时重新审查和验证。只有 ahead 提交时跳过创建提交。提交后检查 `git status --porcelain=v1 --untracked-files=all`，必须为空；若 Hook 产生新增内容，先审查并提交，再继续。不可用 stash、reset、忽略规则或删除文件制造工作区干净。

推送前重新运行状态脚本，确认仍在 main、HEAD/remote 与预期一致，stagedPaths、unstagedPaths、untrackedPaths 全为空，所有待推送提交均已审查并覆盖整批发布范围；只进行一次普通 `git push <核对后的remote> HEAD:refs/heads/main`。禁止 force push。上游在此期间变化时停止，普通 push 的失败不能用强推解决。

## 4. 核验发布结果

按本次 push 的 SHA 定位流水线，不把旧的绿色运行当作本次结果。等待检查与发布完成；失败报告阶段、错误以及是否已产生 tag/npm 版本/Release，不循环重试。

无发布变更时报告“已提交/推送，本次无需新版本”，这不是失败。需要发布时核对 npm 精确版本、预期 dist-tag、GitHub Release 和仓库外运行 CLI 的结果；公开元数据延迟时短暂等待并重新读取，不重复上传或删除标签。长时间无法验证时如实报告剩余状态。

最后报告提交 SHA、推送目标、检查结果、版本或不发布原因、Release 链接和未处理内容。普通发布不手改 package.json 版本，不手动打 tag，不新增 npm token。

CLI 参数依据：[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。
