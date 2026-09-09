import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  highlightedPainRegionsFromQuestionOptions,
  questionOptionsFromPainRegions,
  supportsPainLocationSync,
} from '../packages/shared/src/services/painLocationSync.js'

const patientView = readFileSync(
  new URL('../apps/patient/src/views/PatientView.vue', import.meta.url),
  'utf8',
)
const painLocationInput = readFileSync(
  new URL('../packages/shared/src/components/PainLocationInput.vue', import.meta.url),
  'utf8',
)
const bodyPainMap = readFileSync(
  new URL('../packages/shared/src/components/BodyPainMap.vue', import.meta.url),
  'utf8',
)

test('maps precise headache diagram selections to questionnaire options', () => {
  assert.deepEqual(
    questionOptionsFromPainRegions('headache', ['front_forehead_right']),
    ['單側', '前額'],
  )
  assert.deepEqual(
    questionOptionsFromPainRegions('headache', [
      'front_forehead_right',
      'front_forehead_left',
    ]),
    ['兩側都痛', '前額'],
  )
  assert.deepEqual(
    questionOptionsFromPainRegions('headache', ['back_occipital_left']),
    ['單側', '後腦勺及頸部'],
  )
})

test('highlights coarse headache options without inventing a precise side', () => {
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('headache', ['單側']),
    [],
  )
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('headache', ['前額']),
    ['front_forehead_right', 'front_forehead_left'],
  )
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('headache', [
      '兩側都痛',
      '後腦勺及頸部',
    ]),
    [
      'back_occipital_right',
      'back_occipital_center',
      'back_occipital_left',
      'back_neck_right',
      'back_neck_center',
      'back_neck_left',
    ],
  )
})

test('maps chest and abdomen regions in both directions', () => {
  assert.deepEqual(
    questionOptionsFromPainRegions('chest', ['front_chest_left']),
    ['左邊'],
  )
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('chest', ['兩側都有']),
    [
      'front_chest_right',
      'front_chest_left',
      'back_upper_right',
      'back_upper_left',
    ],
  )
  assert.deepEqual(
    questionOptionsFromPainRegions('abdomen', [
      'front_upper_abdomen_right',
      'back_flank_left',
    ]),
    ['右上腹', '左側腰痛'],
  )
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('abdomen', ['肚臍以下腹痛']),
    [
      'front_lower_abdomen_right',
      'front_lower_abdomen_center',
      'front_lower_abdomen_left',
    ],
  )
})

test('limits cross-control synchronization to explicitly mapped presets', () => {
  assert.equal(supportsPainLocationSync('headache'), true)
  assert.equal(supportsPainLocationSync('body_ache'), false)
  assert.deepEqual(
    questionOptionsFromPainRegions('body_ache', ['front_arm_right']),
    [],
  )
  assert.deepEqual(
    highlightedPainRegionsFromQuestionOptions('body_ache', ['右上肢']),
    [],
  )
})

test('patient view wires diagram and questionnaire updates through one state', () => {
  assert.match(patientView, /@update:model-value="updatePainLocations"/)
  assert.match(
    patientView,
    /@update:selected-options="updateQuestionOptions"/,
  )
  assert.match(patientView, /:selected-options="selectedQuestionOptions"/)
  assert.match(
    patientView,
    /:highlighted-region-ids="highlightedPainLocationIds"/,
  )
  assert.match(patientView, /@submit="submitQuestionnaireAnswer"/)
})

test('location question renders one option group and one submit action', () => {
  assert.match(patientView, /class="pain-location-question-card"/)
  assert.match(patientView, /:show-region-options="false"/)
  assert.match(patientView, /<PainLocationInput[\s\S]*?embedded/)
  assert.doesNotMatch(
    patientView,
    /<PainLocationInput[\s\S]*?@submit="submitMessage"/,
  )
  assert.match(
    bodyPainMap,
    /v-if="!readonly && showRegionOptions"[\s\S]*?class="region-options"/,
  )
  assert.match(painLocationInput, /v-if="!embedded"[\s\S]*?class="confirm-pain-button"/)
  assert.match(patientView, /<QuestionnaireControl[\s\S]*?embedded[\s\S]*?@submit="submitQuestionnaireAnswer"/)
})
