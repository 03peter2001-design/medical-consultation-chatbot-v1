import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatPainRegions,
  getPainRegions,
} from '../src/data/bodyPainRegions.js'

test('resolves structured body-map selections in patient order', () => {
  const regions = getPainRegions([
    'front_chest_left',
    'back_flank_right',
    'unknown',
  ])

  assert.deepEqual(
    regions.map(({ id, label, view }) => ({ id, label, view })),
    [
      { id: 'front_chest_left', label: '左胸', view: 'front' },
      { id: 'back_flank_right', label: '右後腰', view: 'back' },
    ],
  )
  assert.equal(
    formatPainRegions(['front_chest_left', 'back_flank_right']),
    '左胸、右後腰',
  )
})
