import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

await test("构建保留历史版本、拒绝覆盖和不完整元数据；检查模式不写入", async (t) => {
  const root = resolve(import.meta.dirname, "..");
  const temp = await mkdtemp(join(tmpdir(), "luigi-publish-"));
  t.after(() => rm(temp, { recursive: true, force: true }));
  await mkdir(join(temp, "scripts"));
  await mkdir(join(temp, "skill"));
  await copyFile(
    join(root, "scripts/build-registry.ts"),
    join(temp, "scripts/build-registry.ts"),
  );
  await writeFile(join(temp, "package.json"), '{"type":"module"}');
  await symlink(join(root, "node_modules"), join(temp, "node_modules"), "dir");
  const skill = join(temp, "skill/SKILL.md");
  const initial = "---\nname: forms\ndescription: 测试\n---\n第一版\n";
  await writeFile(skill, initial);
  const catalog = {
    entries: [
      {
        type: "skill",
        name: "forms",
        description: "测试",
        version: "1.0.0",
        directory: "skill",
        requires: [],
      },
    ],
  };
  const save = () =>
    writeFile(join(temp, "catalog.json"), JSON.stringify(catalog));
  await save();
  const build = (...args: string[]) =>
    execFileSync(
      process.execPath,
      [
        "--import",
        import.meta.resolve("tsx"),
        join(temp, "scripts/build-registry.ts"),
        ...args,
      ],
      { cwd: temp, encoding: "utf8", stdio: "pipe" },
    );
  build();
  build("--check");
  const index = join(temp, "registry/index.json");
  const before = await readFile(index, "utf8");
  await writeFile(skill, initial + "第二版\n");
  assert.throws(() => build(), /版本已存在且内容不同/);
  assert.equal(await readFile(index, "utf8"), before);
  catalog.entries[0]!.version = "2.0.0";
  await save();
  assert.throws(() => build("--check"));
  assert.equal(await readFile(index, "utf8"), before);
  build();
  build("--check");
  const published = JSON.parse(await readFile(index, "utf8")) as {
    entries: { version: string; url: string }[];
  };
  assert.deepEqual(
    published.entries.map((e) => e.version),
    ["1.0.0", "2.0.0"],
  );
  assert.match(
    await readFile(join(temp, "registry", published.entries[0]!.url), "utf8"),
    /第一版/,
  );
  await writeFile(skill, "没有 frontmatter");
  assert.throws(() => build(), /缺少元数据/);
});
