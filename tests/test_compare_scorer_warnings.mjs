import { strict as assert } from 'node:assert'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(new URL('../dashboard/frontend/package.json', import.meta.url))
const ts = require('typescript')
const source = await readFile(new URL('../dashboard/frontend/src/comparisonPolicy.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { comparisonState } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('mixed-profile warnings remain visible without blocking comparison', () => {
  const checks = { mixed: { severity: 'warning', reasons: ['media cache — no input media'] } }
  const result = comparisonState([], ['mixed', 'mixed', 'baseline'], checks)
  assert.equal(result.comparable, true)
  assert.equal(result.warnings.size, 1)
  assert.deepEqual(result.warnings.get('mixed').reasons, checks.mixed.reasons)
})

test('workload mismatches still block highlighting even when scorers have warnings', () => {
  const checks = { mixed: { severity: 'warning', reasons: ['check signal'] } }
  const result = comparisonState(['different inputs'], ['mixed'], checks)
  assert.equal(result.comparable, false)
  assert.equal(result.warnings.size, 1)
})
