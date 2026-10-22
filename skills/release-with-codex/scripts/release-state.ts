import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readlinkSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export function inspectRelease(directory: string, expected?: string) {
  const git = (...args: string[]) =>
    execFileSync("git", args, {
      cwd: directory,
      encoding: "utf8",
      timeout: 30_000,
      maxBuffer: 20 * 1024 * 1024,
      env: { ...process.env, GIT_TERMINAL_PROMPT: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    });
  const stop = (reason: string) => ({ status: "stopped" as const, reason });
  const root = git("rev-parse", "--show-toplevel").trim();
  directory = root;
  if (git("rev-parse", "--is-shallow-repository").trim() === "true")
    return stop("浅克隆不能完整审查提交历史，请先补齐历史。");
  if (git("branch", "--show-current").trim() !== "main")
    return stop("当前不是 main 分支（或处于 detached HEAD），不执行发布。");
  for (const marker of [
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "rebase-merge",
    "rebase-apply",
    "sequencer",
  ]) {
    if (
      existsSync(resolve(root, git("rev-parse", "--git-path", marker).trim()))
    )
      return stop("存在未完成的合并、变基或提交恢复操作。");
  }
  if (git("ls-files", "--unmerged").length)
    return stop("存在未解决的文件冲突。");
  const [remote, merge] = git(
    "for-each-ref",
    "--format=%(upstream:remotename)%00%(upstream:remoteref)",
    "refs/heads/main",
  )
    .trim()
    .split("\0");
  if (
    !remote ||
    remote === "." ||
    remote.startsWith("-") ||
    merge !== "refs/heads/main"
  )
    return stop("main 必须有明确的远端 main 上游，不自动设置或猜测推送目标。");
  const upstreamRef = git(
    "rev-parse",
    "--symbolic-full-name",
    "@{upstream}",
  ).trim();
  if (!upstreamRef.startsWith("refs/remotes/"))
    return stop("上游不是远端跟踪分支。");
  git("fetch", "--tags", remote, `+refs/heads/main:${upstreamRef}`);
  const head = git("rev-parse", "HEAD").trim();
  const upstream = git("rev-parse", "@{upstream}").trim();
  const [behind, ahead] = git(
    "rev-list",
    "--left-right",
    "--count",
    `${upstream}...${head}`,
  )
    .trim()
    .split(/\s+/)
    .map(Number);
  if (
    behind === undefined ||
    ahead === undefined ||
    !Number.isInteger(behind) ||
    !Number.isInteger(ahead)
  )
    throw new Error("无法解析上游提交差异。");
  if (behind > 0)
    return stop(
      `上游领先 ${behind} 个提交，本地领先 ${ahead} 个提交；先处理同步或分叉，不自动 rebase 或强推。`,
    );
  const status = git("status", "--porcelain=v1", "-z", "--untracked-files=all");
  if (!status && ahead === 0) return stop("没有待提交或待推送内容。");
  const split = (value: string) => value.split("\0").filter(Boolean);
  const stagedPaths = split(
    git("diff", "--cached", "--name-only", "--no-renames", "-z"),
  );
  const unstagedPaths = split(git("diff", "--name-only", "--no-renames", "-z"));
  const untrackedPaths = split(
    git("ls-files", "--others", "--exclude-standard", "-z"),
  );
  const changedPaths = [
    ...new Set([...stagedPaths, ...unstagedPaths, ...untrackedPaths]),
  ].sort();
  const submodules = split(git("ls-files", "--stage", "-z"))
    .filter((entry) => entry.startsWith("160000 "))
    .map((entry) => entry.slice(entry.indexOf("\t") + 1));
  if (changedPaths.some((path) => submodules.includes(path)))
    return stop("包含子模块改动，需先独立审查并明确子模块发布范围。");
  const hash = createHash("sha256");
  const add = (value: string | Buffer) => {
    const data = Buffer.from(value);
    hash.update(`${data.length}:`).update(data);
  };
  for (const value of [
    root,
    remote,
    head,
    upstream,
    status,
    git("for-each-ref", "--format=%(refname) %(objectname)", "refs/tags"),
    git("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"),
    git("diff", "--binary", "--no-ext-diff", "--no-textconv"),
  ])
    add(value);
  for (const path of untrackedPaths) {
    const absolute = resolve(root, path);
    const stat = lstatSync(absolute);
    add(path);
    if (stat.isSymbolicLink()) add(`symlink:${readlinkSync(absolute)}`);
    else if (stat.isFile() && stat.size <= 2 * 1024 * 1024)
      add(readFileSync(absolute));
    else
      return stop(
        `未跟踪路径无法自动审查（目录、特殊文件或超过 2 MB）：${path}`,
      );
  }
  const fingerprint = hash.digest("hex");
  if (expected && fingerprint !== expected)
    return stop("审查后的 HEAD、上游、暂存区或工作区发生变化，必须重新审查。");
  return {
    status: "ready" as const,
    root,
    remote,
    head,
    upstream,
    ahead,
    behind,
    fingerprint,
    stagedPaths,
    unstagedPaths,
    untrackedPaths,
    changedPaths,
    pendingCommits: git("rev-list", "--reverse", `${upstream}..${head}`)
      .trim()
      .split("\n")
      .filter(Boolean),
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  try {
    const [directory, flag, expected, extra] = process.argv.slice(2);
    if (
      !directory ||
      (flag !== undefined && (flag !== "--expect" || !expected)) ||
      extra
    )
      throw new Error(
        "用法：node release-state.ts <仓库目录> [--expect <fingerprint>]",
      );
    const result = inspectRelease(resolve(directory), expected);
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.status === "ready" ? 0 : 2;
  } catch (error) {
    console.error(
      JSON.stringify({
        status: "error",
        reason: error instanceof Error ? error.message : String(error),
      }),
    );
    process.exitCode = 1;
  }
}
