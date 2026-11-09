import { strict as assert } from 'node:assert'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(new URL('../dashboard/frontend/package.json', import.meta.url))
const ts = require('typescript')
const source = await readFile(new URL('../dashboard/frontend/src/comparePrompts.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { transcriptionModeState } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('streaming and batch modes are distinguished for dashboard and imported runs', () => {
  const batch = { params: { endpoint: '/v1/audio/transcriptions', transcription_stream: false } }
  const stream = { results: { endpoint: 'http://example/v1/audio/transcriptions', transcription_stream: true } }
  const unknown = { results: { endpoint: 'http://example/v1/audio/transcriptions' } }
  assert.deepEqual(transcriptionModeState([batch, stream]), { mismatch: true, unknown: false })
  assert.deepEqual(transcriptionModeState([stream, unknown]), { mismatch: false, unknown: true })
  assert.deepEqual(transcriptionModeState([batch, batch]), { mismatch: false, unknown: false })
})
