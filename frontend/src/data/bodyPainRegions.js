export const BODY_PAIN_REGIONS = [
  { id: 'front_vertex', label: '頭頂', view: 'front', d: 'M91 27Q95 11 110 10q15 1 19 17-9-4-19-4t-19 4Z' },
  { id: 'front_forehead_right', label: '右前額', view: 'front', d: 'M84 29q9-6 26-6v16H89q-2-6-5-10Z' },
  { id: 'front_forehead_left', label: '左前額', view: 'front', d: 'M110 23q17 0 26 6-3 4-5 10h-21Z' },
  { id: 'front_temple_right', label: '右太陽穴', view: 'front', d: 'M84 30q-5 9 0 19l9-2 2-10-6 2q-2-6-5-9Z' },
  { id: 'front_temple_left', label: '左太陽穴', view: 'front', d: 'M136 30q5 9 0 19l-9-2-2-10 6 2q2-6 5-9Z' },
  { id: 'front_orbit_right', label: '右眼眶周圍', view: 'front', d: 'M92 39q8-7 16 0-6 10-16 7Z' },
  { id: 'front_orbit_left', label: '左眼眶周圍', view: 'front', d: 'M112 39q8-7 16 0-6 10-16 7Z' },
  { id: 'front_neck_right', label: '右前頸', view: 'front', d: 'M96 67h14v21H92z' },
  { id: 'front_neck_left', label: '左前頸', view: 'front', d: 'M110 67h14l4 21h-18z' },
  { id: 'front_chest_right', label: '右胸', view: 'front', d: 'M72 89h27v57H65l4-43z' },
  { id: 'front_chest_center', label: '胸骨中央', view: 'front', d: 'M99 89h22v57H99z' },
  { id: 'front_chest_left', label: '左胸', view: 'front', d: 'M121 89h27l3 14 4 43h-34z' },
  { id: 'front_upper_abdomen_right', label: '右上腹', view: 'front', d: 'M67 147h32v46H70z' },
  { id: 'front_upper_abdomen_center', label: '上腹中央', view: 'front', d: 'M99 147h22v46H99z' },
  { id: 'front_upper_abdomen_left', label: '左上腹', view: 'front', d: 'M121 147h32l-3 46h-29z' },
  { id: 'front_lower_abdomen_right', label: '右下腹', view: 'front', d: 'M70 194h29v47H76z' },
  { id: 'front_lower_abdomen_center', label: '下腹中央', view: 'front', d: 'M99 194h22v47H99z' },
  { id: 'front_lower_abdomen_left', label: '左下腹', view: 'front', d: 'M121 194h29l-6 47h-23z' },
  { id: 'front_arm_right', label: '右上肢', view: 'front', d: 'M64 91l-14 5-15 65-14 77 22 4 20-77 7-58z' },
  { id: 'front_arm_left', label: '左上肢', view: 'front', d: 'M156 91l14 5 15 65 14 77-22 4-20-77-7-58z' },
  { id: 'front_leg_right', label: '右下肢', view: 'front', d: 'M76 242h33l-4 84-9 110H69l8-111z' },
  { id: 'front_leg_left', label: '左下肢', view: 'front', d: 'M111 242h33l7 83 8 111h-27l-9-110z' },
  { id: 'back_vertex', label: '頭頂後側', view: 'back', d: 'M91 27Q95 11 110 10q15 1 19 17-9-4-19-4t-19 4Z' },
  { id: 'back_occipital_right', label: '右後腦', view: 'back', d: 'M84 28q7-5 19-5v39Q91 59 84 49q-5-11 0-21Z' },
  { id: 'back_occipital_center', label: '後腦中央', view: 'back', d: 'M103 23q7-2 14 0v39q-7 5-14 0Z' },
  { id: 'back_occipital_left', label: '左後腦', view: 'back', d: 'M117 23q12 0 19 5 5 10 0 21-7 10-19 13Z' },
  { id: 'back_neck_right', label: '右後頸', view: 'back', d: 'M96 67h9v21H92z' },
  { id: 'back_neck_center', label: '後頸中央', view: 'back', d: 'M105 67h10v21h-10z' },
  { id: 'back_neck_left', label: '左後頸', view: 'back', d: 'M115 67h9l4 21h-13z' },
  { id: 'back_upper_right', label: '右上背', view: 'back', d: 'M72 89h32v67H65l4-53z' },
  { id: 'back_spine_upper', label: '上背脊椎', view: 'back', d: 'M104 89h12v67h-12z' },
  { id: 'back_upper_left', label: '左上背', view: 'back', d: 'M116 89h32l3 14 4 53h-39z' },
  { id: 'back_flank_right', label: '右後腰', view: 'back', d: 'M67 157h37v75H74z' },
  { id: 'back_spine_lower', label: '下背脊椎', view: 'back', d: 'M104 157h12v75h-12z' },
  { id: 'back_flank_left', label: '左後腰', view: 'back', d: 'M116 157h37l-7 75h-30z' },
  { id: 'back_hip_right', label: '右臀部', view: 'back', d: 'M74 233h36v43H76z' },
  { id: 'back_hip_left', label: '左臀部', view: 'back', d: 'M110 233h36l-2 43h-34z' },
  { id: 'back_arm_right', label: '右上肢後側', view: 'back', d: 'M64 91l-14 5-15 65-14 77 22 4 20-77 7-58z' },
  { id: 'back_arm_left', label: '左上肢後側', view: 'back', d: 'M156 91l14 5 15 65 14 77-22 4-20-77-7-58z' },
  { id: 'back_leg_right', label: '右下肢後側', view: 'back', d: 'M76 277h34l-5 49-9 110H69l8-111z' },
  { id: 'back_leg_left', label: '左下肢後側', view: 'back', d: 'M110 277h34l7 48 8 111h-27l-9-110z' },
]

const BODY_PAIN_REGION_MAP = Object.fromEntries(
  [
    ...BODY_PAIN_REGIONS,
    { id: 'front_head', label: '頭部前側', view: 'front' },
    { id: 'front_neck', label: '頸部前側', view: 'front' },
    { id: 'back_head', label: '後腦', view: 'back' },
    { id: 'back_neck', label: '後頸', view: 'back' },
  ].map((region) => [region.id, region]),
)

const ALL_REGION_IDS = BODY_PAIN_REGIONS.map((region) => region.id)

const BODY_PAIN_PRESETS = {
  headache: {
    key: 'headache',
    title: '請點選頭痛的位置',
    instruction: '可複選並切換正面與背面，請點選最接近的頭部或頸部位置。',
    viewBox: '70 0 80 100',
    allowedRegionIds: [
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
    ],
  },
  chest: {
    key: 'chest',
    title: '請點選胸痛的位置',
    instruction: '可切換正面與背面，選擇胸前或上背疼痛的位置。',
    viewBox: '30 55 160 205',
    allowedRegionIds: [
      'front_chest_right',
      'front_chest_center',
      'front_chest_left',
      'back_upper_right',
      'back_spine_upper',
      'back_upper_left',
    ],
  },
  abdomen: {
    key: 'abdomen',
    title: '請點選腹痛的位置',
    instruction: '可切換正面與背面，選擇腹部或腰背疼痛的位置。',
    viewBox: '48 125 124 175',
    allowedRegionIds: [
      'front_upper_abdomen_right',
      'front_upper_abdomen_center',
      'front_upper_abdomen_left',
      'front_lower_abdomen_right',
      'front_lower_abdomen_center',
      'front_lower_abdomen_left',
      'back_flank_right',
      'back_spine_lower',
      'back_flank_left',
    ],
  },
  all: {
    key: 'all',
    title: '請直接點選疼痛部位',
    instruction: '可複選正面與背面；左右以病人本人為準。',
    viewBox: '0 0 220 450',
    allowedRegionIds: ALL_REGION_IDS,
  },
}

export function getPainMapPreset(route = '') {
  return BODY_PAIN_PRESETS[route] || BODY_PAIN_PRESETS.all
}

export function getPainRegions(ids = []) {
  return ids
    .map((id) => BODY_PAIN_REGION_MAP[id])
    .filter(Boolean)
}

export function formatPainRegions(ids = []) {
  return getPainRegions(ids)
    .map((region) => region.label)
    .join('、')
}
