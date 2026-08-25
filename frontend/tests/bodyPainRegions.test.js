import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatPainRegions,
  getPainMapPreset,
  getPainRegions,
  togglePainRegionSelection,
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

test('limits each complaint to clinically relevant body-map regions', () => {
  const headache = getPainMapPreset('headache')
  const chest = getPainMapPreset('chest')
  const abdomen = getPainMapPreset('abdomen')

  assert.deepEqual(headache.allowedRegionIds, [
    'front_vertex',
    'front_forehead_right',
    'front_forehead_left',
    'front_temple_right',
    'front_temple_left',
    'front_orbit_right',
    'front_orbit_left',
    'front_neck_right',
    'front_neck_left',
    'back_vertex',
    'back_occipital_right',
    'back_occipital_center',
    'back_occipital_left',
    'back_neck_right',
    'back_neck_center',
    'back_neck_left',
  ])
  assert.equal(
    headache.allowedRegionIds.some((id) => id.includes('leg')),
    false,
  )

  assert.equal(
    chest.allowedRegionIds.every(
      (id) => id.includes('chest') || id.includes('upper'),
    ),
    true,
  )
  assert.equal(
    chest.allowedRegionIds.some((id) => id.includes('abdomen')),
    false,
  )

  assert.equal(
    abdomen.allowedRegionIds.every(
      (id) =>
        id.includes('abdomen') ||
        id.includes('flank') ||
        id === 'back_spine_lower',
    ),
    true,
  )
  assert.equal(
    abdomen.allowedRegionIds.some((id) => id.includes('head')),
    false,
  )
})

test('keeps legacy coarse head selections readable', () => {
  assert.equal(
    formatPainRegions(['front_head', 'back_neck']),
    '頭部前側、後頸',
  )
})

test('falls back to the complete body map for unknown routes', () => {
  const all = getPainMapPreset('unknown')
  assert.equal(all.key, 'all')
  assert.equal(all.allowedRegionIds.length > 20, true)
})

test('keeps diagram and checkbox selections on the same region state', () => {
  const allowedRegionIds = getPainMapPreset('chest').allowedRegionIds

  const selectedFromDiagram = togglePainRegionSelection(
    [],
    'front_chest_center',
    allowedRegionIds,
  )
  assert.deepEqual(selectedFromDiagram, ['front_chest_center'])

  const selectedFromOption = togglePainRegionSelection(
    selectedFromDiagram,
    'front_chest_left',
    allowedRegionIds,
  )
  assert.deepEqual(selectedFromOption, [
    'front_chest_center',
    'front_chest_left',
  ])

  assert.deepEqual(
    togglePainRegionSelection(
      selectedFromOption,
      'front_chest_center',
      allowedRegionIds,
    ),
    ['front_chest_left'],
  )
  assert.strictEqual(
    togglePainRegionSelection(
      selectedFromOption,
      'front_leg_left',
      allowedRegionIds,
    ),
    selectedFromOption,
  )
})
