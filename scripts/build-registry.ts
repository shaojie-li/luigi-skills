import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { z } from "zod";
import { parse } from "yaml";

const name = z.string().regex(/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/);
const version = z.string().regex(/^\d+\.\d+\.\d+$/);
const requirement = z.strictObject({
  key: z.string().regex(/^(skill|ui|preset)\/[a-z][a-z0-9-]*$/),
  version,
});
const entrySchema = z.strictObject({
  type: z.enum(["skill", "ui", "preset", "template"]),
  name,
  description: z.string().min(1).max(1024),
  version,
  directory: z.string().regex(/^[a-z][a-z0-9-/]*$/),
  requires: z.array(requirement).default([]),
  dependencies: z.record(z.string(), z.string()).default({}),
});
const root = resolve(import.meta.dirname, "..");
const hash = (content: string) =>
  createHash("sha256").update(content).digest("hex");
const input = z
  .strictObject({ entries: z.array(entrySchema).min(1) })
  .parse(JSON.parse(await readFile(join(root, "catalog.json"), "utf8")));
const output = join(root, "registry");
const check = process.argv.includes("--check");
interface Published {
  type: string;
  name: string;
  description: string;
  version: string;
  url: string;
  sha256: string;
  requires: z.infer<typeof requirement>[];
}
const publishedSchema = entrySchema
  .omit({ directory: true, dependencies: true })
  .extend({ url: z.string(), sha256: z.string().regex(/^[a-f0-9]{64}$/) });
let entries: Published[] = [];
try {
  entries = z
    .strictObject({
      schemaVersion: z.literal(2),
      entries: z.array(publishedSchema),
    })
    .parse(
      JSON.parse(await readFile(join(output, "index.json"), "utf8")),
    ).entries;
} catch (error) {
  if (!(error instanceof Error && "code" in error && error.code === "ENOENT"))
    throw error;
}
async function writeOrCheck(path: string, content: string) {
  if (check) {
    if ((await readFile(path, "utf8")) !== content)
      throw new Error(`分发文件过期：${path}，运行 pnpm build 并审查差异`);
  } else await writeFile(path, content);
}
if (!check) await mkdir(join(output, "items"), { recursive: true });
const seen = new Set<string>();
for (const entry of input.entries) {
  const identity = `${entry.type}/${entry.name}@${entry.version}`;
  if (seen.has(identity)) throw new Error(`重复资产：${identity}`);
  seen.add(identity);
  const files: { path: string; content: string; sha256: string }[] = [];
  async function walk(directory: string, prefix = ""): Promise<void> {
    for (const child of (
      await readdir(directory, { withFileTypes: true })
    ).sort((a, b) => a.name.localeCompare(b.name, "en"))) {
      const path = `${prefix}${child.name}`;
      if (child.isSymbolicLink()) throw new Error(`拒绝分发符号链接：${path}`);
      if (child.isDirectory())
        await walk(join(directory, child.name), `${path}/`);
      else if (child.isFile()) {
        const content = new TextDecoder("utf-8", { fatal: true }).decode(
          await readFile(join(directory, child.name)),
        );
        if (content.length > 256000) throw new Error(`文件过大：${path}`);
        files.push({ path, content, sha256: hash(content) });
      } else throw new Error(`不支持的文件：${path}`);
    }
  }
  await walk(join(root, entry.directory));
  if (!files.length || files.length > 100)
    throw new Error(`文件数量非法：${identity}`);
  if (entry.type === "skill") {
    const frontmatter = files
      .find((file) => file.path === "SKILL.md")
      ?.content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1];
    if (!frontmatter) throw new Error(`Skill 缺少元数据：${identity}`);
    const metadata = z
      .object({ name, description: z.string() })
      .parse(parse(frontmatter));
    if (
      metadata.name !== entry.name ||
      metadata.description !== entry.description
    )
      throw new Error(`Skill 元数据不一致：${identity}`);
  }
  const item = { name: entry.name, description: entry.description, files };
  const payload =
    JSON.stringify(
      {
        schemaVersion: 1,
        version: entry.version,
        skills: entry.type === "skill" ? [item] : [],
        assets:
          entry.type === "skill"
            ? []
            : [
                {
                  ...item,
                  type: entry.type,
                  requires: [],
                  dependencies: entry.dependencies,
                },
              ],
      },
      null,
      2,
    ) + "\n";
  if (Buffer.byteLength(payload) > 2 * 1024 * 1024)
    throw new Error(`快照超过 2 MB：${identity}`);
  const sha256 = hash(payload);
  const published = publishedSchema.parse({
    type: entry.type,
    name: entry.name,
    description: entry.description,
    version: entry.version,
    url: `items/${sha256}.json`,
    sha256,
    requires: entry.requires,
  });
  const previous = entries.find(
    (e) => `${e.type}/${e.name}@${e.version}` === identity,
  );
  if (previous && JSON.stringify(previous) !== JSON.stringify(published))
    throw new Error(`版本已存在且内容不同：${identity}，请提升资产版本`);
  if (!previous) entries.push(published);
  await writeOrCheck(join(output, published.url), payload);
}
await writeOrCheck(
  join(output, "index.json"),
  JSON.stringify({ schemaVersion: 2, entries }, null, 2) + "\n",
);
console.log(
  `${check ? "验证" : "生成"} ${input.entries.length} 个资产；保留 ${entries.length} 个历史版本`,
);
