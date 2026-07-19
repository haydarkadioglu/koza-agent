import { afterEach, describe, expect, test } from "bun:test"
import { mkdtemp, readdir, rm, utimes, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { cleanupStoreFiles, deleteStoreFileIfEmpty } from "./store-cleanup"

const roots: string[] = []

async function tempRoot() {
  const root = await mkdtemp(join(tmpdir(), "koza-store-cleanup-"))
  roots.push(root)
  return root
}

async function writeStore(root: string, name: string, value: string, modified: Date) {
  await writeFile(join(root, name), value)
  await utimes(join(root, name), modified, modified)
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})

describe("store cleanup", () => {
  test("removes empty scoped stores and leaves global stores alone", async () => {
    const root = await tempRoot()
    const now = new Date("2026-07-01T00:00:00.000Z")
    await writeStore(root, "koza.draft.empty.dat", "{}", now)
    await writeStore(root, "koza.workspace.empty.dat", "{\n}", now)
    await writeStore(root, "koza.global.dat", "{}", now)
    await writeStore(root, "koza.workspace.empty.dat.json", "{}", now)

    const result = await cleanupStoreFiles(root, now.getTime())

    expect(result.deleted.sort()).toEqual(["koza.draft.empty.dat", "koza.workspace.empty.dat"])
    expect((await readdir(root)).sort()).toEqual(["koza.global.dat", "koza.workspace.empty.dat.json"])
  })

  test("removes stale drafts by age without removing non-empty workspace stores", async () => {
    const root = await tempRoot()
    const now = new Date("2026-07-01T00:00:00.000Z")
    await writeStore(root, "koza.draft.old.dat", '{"draft:prompt":"hello"}', new Date("2026-05-01T00:00:00.000Z"))
    await writeStore(root, "koza.draft.recent.dat", '{"draft:prompt":"hello"}', now)
    await writeStore(
      root,
      "koza.workspace.old.dat",
      '{"workspace:layout":"wide"}',
      new Date("2025-01-01T00:00:00.000Z"),
    )
    await writeStore(root, "koza.workspace.recent.dat", '{"workspace:layout":"wide"}', now)

    const result = await cleanupStoreFiles(root, now.getTime())

    expect(result.deleted).toEqual(["koza.draft.old.dat"])
    expect((await readdir(root)).sort()).toEqual([
      "koza.draft.recent.dat",
      "koza.workspace.old.dat",
      "koza.workspace.recent.dat",
    ])
  })

  test("caps scoped stores by recency", async () => {
    const root = await tempRoot()
    const now = new Date("2026-07-01T00:00:00.000Z")
    await Promise.all(
      Array.from({ length: 102 }, (_, index) =>
        writeStore(
          root,
          `koza.draft.${index}.dat`,
          '{"draft:prompt":"hello"}',
          new Date(now.getTime() - index * 1000),
        ),
      ),
    )

    const result = await cleanupStoreFiles(root, now.getTime())

    const remaining = await readdir(root)

    expect(result.deleted.sort()).toEqual(["koza.draft.100.dat", "koza.draft.101.dat"])
    expect(remaining).toHaveLength(100)
  })

  test("removes a scoped store immediately when it becomes empty", async () => {
    const root = await tempRoot()
    await writeStore(root, "koza.draft.empty.dat", "{}", new Date("2026-07-01T00:00:00.000Z"))
    await writeStore(root, "koza.global.dat", "{}", new Date("2026-07-01T00:00:00.000Z"))

    expect(await deleteStoreFileIfEmpty(root, "koza.draft.empty.dat")).toBe(true)
    expect(await deleteStoreFileIfEmpty(root, "koza.global.dat")).toBe(false)
    expect(await readdir(root)).toEqual(["koza.global.dat"])
  })
})
