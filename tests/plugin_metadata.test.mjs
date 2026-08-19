/** Distribution metadata contracts for the DSH plugin. */

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(HERE, '..', 'dsh-plugin')
const readJson = (name) => JSON.parse(readFileSync(resolve(pluginRoot, name), 'utf8'))

test('DSH manifest and npm package expose the same plugin version', () => {
  const manifest = readJson('dsh.plugin.json')
  const pkg = readJson('package.json')

  assert.equal(manifest.id, pkg.name)
  assert.equal(manifest.version, pkg.version)
})

test('plugin distribution includes both host and browser entry points', () => {
  const manifest = readJson('dsh.plugin.json')
  const pkg = readJson('package.json')

  assert.equal(manifest.main.replace(/^\.\//, ''), pkg.main.replace(/^\.\//, ''))
  assert.equal(manifest.client.main.replace(/^\.\//, ''), pkg.exports['./client'].replace(/^\.\//, ''))
  assert.ok(pkg.files.includes('src'))
  assert.ok(pkg.files.includes('lib/client.js'))
  assert.ok(pkg.files.includes('scripts/workbench.py'))
  assert.ok(pkg.files.includes('assets/workbench.html'))
})
