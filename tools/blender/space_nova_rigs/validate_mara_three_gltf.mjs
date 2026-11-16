/** Verify rigged Mara through the repository's Three.js GLTFLoader. */

import assert from "node:assert/strict"
import {readFile, writeFile} from "node:fs/promises"
import path from "node:path"
import {fileURLToPath, pathToFileURL} from "node:url"

globalThis.self = globalThis
globalThis.createImageBitmap = async () => ({width: 1, height: 1, close() {}})

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(scriptDirectory, "../../..")
const outputDirectory = path.resolve(process.argv[2] || path.join(scriptDirectory, "output"))
const threeModule = path.join(repositoryRoot, "apps/darkorbit_web/assets/node_modules/three/build/three.module.js")
const loaderModule = path.join(
  repositoryRoot,
  "apps/darkorbit_web/assets/node_modules/three/examples/jsm/loaders/GLTFLoader.js"
)
const {AnimationMixer, Vector3} = await import(pathToFileURL(threeModule).href)
const {GLTFLoader} = await import(pathToFileURL(loaderModule).href)

function parseGlb(bytes) {
  const arrayBuffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
  return new Promise((resolve, reject) => {
    new GLTFLoader().parse(arrayBuffer, "", resolve, reject)
  })
}

function glbJson(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  assert.equal(view.getUint32(0, true), 0x46546c67, "file is not binary glTF")
  assert.equal(view.getUint32(4, true), 2, "GLB is not glTF 2.0")
  const jsonLength = view.getUint32(12, true)
  const jsonType = view.getUint32(16, true)
  assert.equal(jsonType, 0x4e4f534a, "first GLB chunk is not JSON")
  const jsonBytes = bytes.subarray(20, 20 + jsonLength)
  return JSON.parse(new TextDecoder().decode(jsonBytes).trimEnd())
}

function hierarchySignature(bones) {
  const names = new Set(bones.map(bone => bone.name))
  return bones
    .map(bone => [bone.name, bone.parent && names.has(bone.parent.name) ? bone.parent.name : null])
    .sort(([left], [right]) => left.localeCompare(right))
}

function validateWeights(skinnedMesh) {
  const positions = skinnedMesh.geometry.getAttribute("position")
  const indices = skinnedMesh.geometry.getAttribute("skinIndex")
  const weights = skinnedMesh.geometry.getAttribute("skinWeight")
  assert.ok(indices, "Mara is missing skinIndex")
  assert.ok(weights, "Mara is missing skinWeight")
  assert.equal(indices.count, positions.count)
  assert.equal(weights.count, positions.count)
  let minimumSum = Infinity
  let maximumSum = -Infinity
  for (let index = 0; index < weights.count; index += 1) {
    const sum = weights.getX(index) + weights.getY(index) + weights.getZ(index) + weights.getW(index)
    assert.ok(Number.isFinite(sum), `vertex ${index} has non-finite weights`)
    assert.ok(Math.abs(sum - 1) <= 1e-5, `vertex ${index} weights sum to ${sum}`)
    minimumSum = Math.min(minimumSum, sum)
    maximumSum = Math.max(maximumSum, sum)
  }
  return {minimumSum, maximumSum, vertices: weights.count}
}

function finiteVector(vector) {
  return [vector.x, vector.y, vector.z].every(Number.isFinite)
}

function validateRuntimePoses(gltf, skinnedMesh) {
  const mixer = new AnimationMixer(gltf.scene)
  const clip = gltf.animations[0]
  const action = mixer.clipAction(clip)
  action.play()
  const frames = [1, 10, 20, 30, 40, 50]
  const bounds = {}
  for (const frame of frames) {
    mixer.setTime((frame - 1) / 24)
    gltf.scene.updateMatrixWorld(true)
    skinnedMesh.skeleton.update()
    assert.ok(
      skinnedMesh.skeleton.boneMatrices.every(Number.isFinite),
      `frame ${frame} produced non-finite bone matrices`
    )
    skinnedMesh.computeBoundingBox()
    assert.ok(finiteVector(skinnedMesh.boundingBox.min), `frame ${frame} bounding minimum is invalid`)
    assert.ok(finiteVector(skinnedMesh.boundingBox.max), `frame ${frame} bounding maximum is invalid`)
    const size = skinnedMesh.boundingBox.getSize(new Vector3())
    assert.ok(Math.max(size.x, size.y, size.z) < 4, `frame ${frame} has implausible runtime bounds`)
    bounds[frame] = {
      min: skinnedMesh.boundingBox.min.toArray(),
      max: skinnedMesh.boundingBox.max.toArray()
    }
  }
  mixer.stopAllAction()
  return bounds
}

const maraPath = path.join(outputDirectory, "mara_venn_rigged.glb")
const templatePath = path.join(outputDirectory, "SpaceNovaFemaleRig.glb")
const maraBytes = await readFile(maraPath)
const templateBytes = await readFile(templatePath)
const maraDocument = glbJson(maraBytes)
const mara = await parseGlb(maraBytes)
const template = await parseGlb(templateBytes)

const maraMeshes = []
const templateMeshes = []
mara.scene.traverse(object => {
  if (object.isSkinnedMesh) maraMeshes.push(object)
})
template.scene.traverse(object => {
  if (object.isSkinnedMesh) templateMeshes.push(object)
})

assert.equal(maraMeshes.length, 1, "Mara GLB must load exactly one SkinnedMesh")
assert.equal(templateMeshes.length, 1, "female template must load exactly one SkinnedMesh")
assert.equal(mara.animations.length, 1, "Mara GLB must load one deformation-test animation")
const maraMesh = maraMeshes[0]
const templateMesh = templateMeshes[0]
assert.equal(maraMesh.skeleton.bones.length, 51, "Mara GLB must contain 51 bones")
assert.deepEqual(
  hierarchySignature(maraMesh.skeleton.bones),
  hierarchySignature(templateMesh.skeleton.bones),
  "Mara GLB does not preserve the female template hierarchy"
)

assert.equal(maraMesh.geometry.getAttribute("position").count, 20_968)
assert.ok(maraMesh.geometry.getAttribute("normal"), "Mara GLB is missing normals")
assert.ok(maraMesh.geometry.getAttribute("uv"), "Mara GLB is missing UVs")
assert.ok(maraMesh.material.map, "Mara GLB material is missing its base-color texture")
assert.ok(maraMesh.material.roughnessMap, "Mara GLB material is missing its roughness texture")
assert.ok(maraMesh.material.metalnessMap, "Mara GLB material is missing its metallic texture")
assert.equal(maraDocument.images?.length, 2, "Mara GLB must embed the two source images")
assert.equal(maraDocument.textures?.length, 2, "Mara GLB must preserve two texture bindings")
assert.ok(maraDocument.images.every(image => image.mimeType === "image/png" && image.bufferView !== undefined))

const weightReport = validateWeights(maraMesh)
const animation = mara.animations[0]
assert.ok(animation.duration >= 49 / 24, "deformation-test animation is too short")
assert.ok(animation.tracks.length > 0, "deformation-test animation has no tracks")
const runtimeBounds = validateRuntimePoses(mara, maraMesh)

const report = {
  loader: "three/examples/jsm/loaders/GLTFLoader.js",
  threeVersion: "0.187.0",
  fileBytes: maraBytes.byteLength,
  skinnedMeshes: maraMeshes.length,
  vertices: weightReport.vertices,
  bones: maraMesh.skeleton.bones.length,
  hierarchyMatchesFemaleTemplate: true,
  normalizedWeights: true,
  minimumWeightSum: weightReport.minimumSum,
  maximumWeightSum: weightReport.maximumSum,
  uv: true,
  embeddedImages: maraDocument.images.length,
  materials: 1,
  animationDurationSeconds: animation.duration,
  animationTracks: animation.tracks.length,
  runtimePoseBounds: runtimeBounds,
  success: true
}
const reportPath = path.join(outputDirectory, "mara_three_validation_report.json")
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8")
console.log("SPACE_NOVA_MARA_THREE_VALIDATED")
console.log(`SPACE_NOVA_MARA_THREE_VALIDATION_REPORT ${reportPath}`)
