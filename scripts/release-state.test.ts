import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { inspectRelease } from "../skills/release-with-codex/scripts/release-state.js";

function fixture(
  run: (
    cwd: string,
    remote: string,
    git: (...args: string[]) => string,
  ) => void,
) {
  const base = mkdtempSync(join(tmpdir(), "release-state-test-"));
  const cwd = join(base, "repo");
  const remote = join(base, "remote.git");
  const exec = (at: string, ...args: string[]) =>
    execFileSync("git", args, {
      cwd: at,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  try {
    exec(base, "init", "--bare", "--initial-branch=main", remote);
    exec(base, "clone", remote, cwd);
    const git = (...args: string[]) => exec(cwd, ...args);
    git("config", "user.name", "Release Test");
    git("config", "user.email", "release@example.invalid");
    git("config", "commit.gpgsign", "false");
    git("config", "core.hooksPath", join(base, "no-hooks"));
    writeFileSync(join(cwd, "file.txt"), "base\n");
    git("add", "file.txt");
    git("commit", "-m", "chore: 初始化");
    git("push", "-u", "origin", "main");
    run(cwd, remote, git);
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
}

test("干净且无未推送内容停止；只有 ahead 提交时继续", () =>
  fixture((cwd, _remote, git) => {
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("commit", "--allow-empty", "-m", "docs: 补充说明");
    const result = inspectRelease(cwd);
    assert.equal(result.status, "ready");
    if (result.status === "ready") {
      assert.equal(result.ahead, 1);
      assert.equal(result.pendingCommits.length, 1);
    }
  }));

test("非 main、detached HEAD、缺失上游与错误目标停止", () =>
  fixture((cwd, _remote, git) => {
    git("switch", "-c", "feature");
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("switch", "--detach");
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("switch", "main");
    git("branch", "--unset-upstream");
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("config", "branch.main.remote", "origin");
    git("config", "branch.main.merge", "refs/heads/other");
    assert.equal(inspectRelease(cwd).status, "stopped");
  }));

test("保留部分暂存内容，fingerprint 检测正文变化和未跟踪文件", () =>
  fixture((cwd, _remote, git) => {
    writeFileSync(join(cwd, "file.txt"), "staged\n");
    git("add", "file.txt");
    writeFileSync(join(cwd, "file.txt"), "unstaged\n");
    writeFileSync(join(cwd, "new file.txt"), "new\n");
    const index = git("diff", "--cached");
    const result = inspectRelease(cwd);
    assert.equal(result.status, "ready");
    if (result.status !== "ready") return;
    assert.deepEqual(result.changedPaths, ["file.txt", "new file.txt"]);
    assert.deepEqual(result.stagedPaths, ["file.txt"]);
    assert.deepEqual(result.unstagedPaths, ["file.txt"]);
    assert.equal(inspectRelease(cwd, result.fingerprint).status, "ready");
    writeFileSync(join(cwd, "new file.txt"), "changed\n");
    assert.equal(inspectRelease(cwd, result.fingerprint).status, "stopped");
    assert.equal(git("diff", "--cached"), index);
    assert.equal(readFileSync(join(cwd, "file.txt"), "utf8"), "unstaged\n");
  }));

test("远端领先或分叉时停止，fetch 失败显性报错", () =>
  fixture((cwd, remote, git) => {
    const old = git("rev-parse", "HEAD").trim();
    git("commit", "--allow-empty", "-m", "feat: 远端变更");
    git("push");
    git("reset", "--hard", old);
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("commit", "--allow-empty", "-m", "fix: 本地变更");
    assert.equal(inspectRelease(cwd).status, "stopped");
    git("remote", "set-url", "origin", `${remote}-missing`);
    assert.throws(() => inspectRelease(cwd));
  }));

test("未完成操作和过大的未跟踪文件阻止继续", () =>
  fixture((cwd, _remote, git) => {
    const mergeHead = join(cwd, ".git", "MERGE_HEAD");
    writeFileSync(mergeHead, git("rev-parse", "HEAD"));
    assert.equal(inspectRelease(cwd).status, "stopped");
    rmSync(mergeHead);
    writeFileSync(join(cwd, "large.bin"), Buffer.alloc(2 * 1024 * 1024 + 1));
    assert.equal(inspectRelease(cwd).status, "stopped");
  }));

test("同步远端发布标签，基线变化使旧审查失效", () =>
  fixture((cwd, remote, git) => {
    writeFileSync(join(cwd, "file.txt"), "docs\n");
    const before = inspectRelease(cwd);
    assert.equal(before.status, "ready");
    execFileSync("git", [
      "--git-dir",
      remote,
      "tag",
      "v1.0.0",
      "refs/heads/main",
    ]);
    if (before.status !== "ready") return;
    assert.equal(inspectRelease(cwd, before.fingerprint).status, "stopped");
    assert.equal(git("tag", "--list").trim(), "v1.0.0");
    assert.equal(inspectRelease(cwd).status, "ready");
  }));
