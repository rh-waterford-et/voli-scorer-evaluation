import { strict as assert } from 'node:assert'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(new URL('../dashboard/frontend/package.json', import.meta.url))
const ts = require('typescript')
const source = await readFile(new URL('../dashboard/frontend/src/hintPosition.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { hintPosition } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

const box = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height })

test('places a warning below its button when there is room', () => {
  assert.deepEqual(hintPosition(box(200, 100, 40, 20), box(0, 0, 200, 100), 800, 600), { left: 120, top: 125 })
})

test('flips expanded warnings above the button and clamps them to the viewport', () => {
  assert.deepEqual(hintPosition(box(760, 500, 30, 20), box(0, 0, 220, 200), 800, 600), { left: 572, top: 295 })
  assert.deepEqual(hintPosition(box(0, 5, 20, 20), box(0, 0, 300, 380), 320, 400), { left: 8, top: 8 })
})
