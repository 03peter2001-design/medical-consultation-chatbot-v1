export const BODY_PAIN_REGIONS = [
  { id: 'front_head', label: '頭部前側', view: 'front', d: 'M110 12a27 27 0 1 1 0 54a27 27 0 1 1 0-54' },
  { id: 'front_neck', label: '頸部前側', view: 'front', d: 'M96 67h28l4 21H92z' },
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
  { id: 'back_head', label: '後腦', view: 'back', d: 'M110 12a27 27 0 1 1 0 54a27 27 0 1 1 0-54' },
  { id: 'back_neck', label: '後頸', view: 'back', d: 'M96 67h28l4 21H92z' },
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

export const BODY_PAIN_REGION_MAP = Object.fromEntries(
  BODY_PAIN_REGIONS.map((region) => [region.id, region]),
)

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
