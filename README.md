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

MIT License。
