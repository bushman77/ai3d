/** Validate generated rig GLBs with the same Three.js GLTFLoader used by Space Nova. */

import assert from "node:assert/strict"
import {readFile, writeFile} from "node:fs/promises"
import path from "node:path"
import {fileURLToPath, pathToFileURL} from "node:url"

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(scriptDirectory, "../../..")
const outputDirectory = path.resolve(process.argv[2] || path.join(scriptDirectory, "output"))
const loaderModule = path.join(
  repositoryRoot,
  "apps/darkorbit_web/assets/node_modules/three/examples/jsm/loaders/GLTFLoader.js"
)
const {GLTFLoader} = await import(pathToFileURL(loaderModule).href)

const templateNames = ["SpaceNovaMaleRig", "SpaceNovaFemaleRig"]

function parseGlb(bytes) {
  const arrayBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(arrayBuffer, "", resolve, reject)
  })
}

function hierarchySignature(bones) {
  const boneNames = new Set(bones.map(bone => bone.name))
  return bones
    .map(bone => [
      bone.name,
      bone.parent && boneNames.has(bone.parent.name) ? bone.parent.name : null
    ])
    .sort(([left], [right]) => left.localeCompare(right))
}

function validateWeights(skinnedMesh) {
  const skinIndices = skinnedMesh.geometry.getAttribute("skinIndex")
  const skinWeights = skinnedMesh.geometry.getAttribute("skinWeight")
  assert.ok(skinIndices, "skinned mesh must contain skinIndex data")
  assert.ok(skinWeights, "skinned mesh must contain skinWeight data")
  assert.equal(skinIndices.count, skinnedMesh.geometry.getAttribute("position").count)
  assert.equal(skinWeights.count, skinIndices.count)

  const weightVector = [0, 0, 0, 0]
  for (let index = 0; index < skinWeights.count; index += 1) {
    weightVector[0] = skinWeights.getX(index)
    weightVector[1] = skinWeights.getY(index)
    weightVector[2] = skinWeights.getZ(index)
    weightVector[3] = skinWeights.getW(index)
    const sum = weightVector.reduce((total, weight) => total + weight, 0)
    assert.ok(Number.isFinite(sum), `vertex ${index} has non-finite weights`)
    assert.ok(Math.abs(sum - 1) <= 1e-5, `vertex ${index} weights sum to ${sum}`)
  }

  return skinWeights.count
}

const report = {
  loader: "three/addons/loaders/GLTFLoader.js",
  templates: {}
}
const signatures = new Map()

for (const templateName of templateNames) {
  const glbPath = path.join(outputDirectory, `${templateName}.glb`)
  const gltf = await parseGlb(await readFile(glbPath))
  const skinnedMeshes = []
  gltf.scene.traverse(object => {
    if (object.isSkinnedMesh) skinnedMeshes.push(object)
  })

  assert.equal(skinnedMeshes.length, 1, `${templateName} must load one SkinnedMesh`)
  assert.equal(gltf.animations.length, 1, `${templateName} must load one pose-test animation`)
  const skinnedMesh = skinnedMeshes[0]
  const bones = skinnedMesh.skeleton.bones
  assert.equal(bones.length, 51, `${templateName} must load all 51 bones`)
  assert.ok(bones.some(bone => bone.name === "root"), `${templateName} is missing root`)
  assert.ok(bones.some(bone => bone.name === "head"), `${templateName} is missing head`)

  const signature = hierarchySignature(bones)
  signatures.set(templateName, signature)
  const vertexCount = validateWeights(skinnedMesh)
  const animation = gltf.animations[0]
  assert.ok(animation.duration > 0, `${templateName} animation duration must be positive`)
  assert.ok(animation.tracks.length > 0, `${templateName} animation must contain tracks`)

  report.templates[templateName] = {
    animationDurationSeconds: animation.duration,
    animationTracks: animation.tracks.length,
    bones: bones.length,
    skinnedMeshes: skinnedMeshes.length,
    vertices: vertexCount
  }
  console.log(`SPACE_NOVA_THREE_VALIDATED ${templateName}`)
}

assert.deepEqual(
  signatures.get("SpaceNovaMaleRig"),
  signatures.get("SpaceNovaFemaleRig"),
  "Three.js loaded different bone names or hierarchy for the two templates"
)
report.identicalBoneNamesAndHierarchy = true
report.success = true

const reportPath = path.join(outputDirectory, "three_validation_report.json")
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8")
console.log(`SPACE_NOVA_THREE_VALIDATION_REPORT ${reportPath}`)
