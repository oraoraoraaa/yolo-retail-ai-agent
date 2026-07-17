export { ApiError, apiFetch, getApiBaseUrl } from './client'
export { analyzeShelfCameraCapture, analyzeShelfImage } from './audit'
export { sendChatMessage } from './chat'
export { queryDatabaseRecords } from './database'
export {
  createPlanogram,
  deletePlanogram,
  getActivePlanogramId,
  listPlanograms,
  matchPlanogramDetections,
  setActivePlanogram,
  updatePlanogram,
} from './planogram'
export {
  captureCameraDetection,
  detectUploadedImage,
  getStreamStatus,
  getStreamVideoUrl,
  listStreamCameras,
  listStreamModels,
  startStream,
  stopStream,
} from './stream'
export type { SendChatPayload, SendChatResponse } from './chat'
export type {
  DetectionBox,
  DetectionResultItem,
  LocalDetectionResult,
  StreamCamera,
  StreamCamerasResponse,
  StreamModel,
  StreamModelsResponse,
  StreamStatusResponse,
} from './stream'
