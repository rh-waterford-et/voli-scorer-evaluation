import { strict as assert } from 'node:assert'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(new URL('../dashboard/frontend/package.json', import.meta.url))
const ts = require('typescript')
const source = await readFile(new URL('../dashboard/frontend/src/warningChecks.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { startWarningChecks } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const defer = () => {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 10))
const response = (cluster_access, id) => ({ cluster_access, id })

test('local warnings appear while the cluster is slow or unavailable', async () => {
  const local = defer(), live = defer(), results = [], statuses = []
  const cancel = startWarningChecks({
    local: () => local.promise, live: () => live.promise, delay: 0,
    onResult: (result) => results.push(result.id), onLocalError: () => assert.fail('local failed'),
    onLocalDone: () => {}, onLiveStatus: (status) => statuses.push(status),
  })
  local.resolve(response('not_checked', 'local'))
  await tick()
  assert.deepEqual(results, ['local'])
  live.resolve(response('unavailable', 'fallback'))
  await tick()
  assert.deepEqual(results, ['local'])
  assert.deepEqual(statuses, ['checking', 'unavailable'])
  cancel()
})

test('late local response cannot overwrite a successful live check', async () => {
  const local = defer(), live = defer(), results = []
  const cancel = startWarningChecks({
    local: () => local.promise, live: () => live.promise, delay: 0,
    onResult: (result) => results.push(result.id), onLocalError: () => assert.fail('local failed'),
    onLocalDone: () => {}, onLiveStatus: () => {},
  })
  await tick()
  live.resolve(response('ok', 'live'))
  await tick()
  local.resolve(response('not_checked', 'local'))
  await tick()
  assert.deepEqual(results, ['live'])
  cancel()
})

test('cancelled requests cannot update a changed endpoint or profile list', async () => {
  const local = defer(), live = defer(), results = []
  const cancel = startWarningChecks({
    local: () => local.promise, live: () => live.promise, delay: 0,
    onResult: (result) => results.push(result.id), onLocalError: () => assert.fail('cancelled error'),
    onLocalDone: () => {}, onLiveStatus: () => {},
  })
  await tick()
  cancel()
  local.resolve(response('not_checked', 'old local'))
  live.resolve(response('ok', 'old live'))
  await tick()
  assert.deepEqual(results, [])
})

test('fresh browser with no cluster settings still loads local warnings', async () => {
  const results = [], statuses = []
  const cancel = startWarningChecks({
    local: async () => response('not_checked', 'local'),
    onResult: (result) => results.push(result.id), onLocalError: () => assert.fail('local failed'),
    onLocalDone: () => {}, onLiveStatus: (status) => statuses.push(status),
  })
  await tick()
  assert.deepEqual(results, ['local'])
  assert.deepEqual(statuses, [])
  cancel()
})
