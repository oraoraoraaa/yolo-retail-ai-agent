export { ApiError, apiFetch, absoluteApiUrl, clearAuthSession, getApiBaseUrl, getAuthToken } from './client'
export { fetchAuthMe, fetchAuthStatus, login } from './auth'
export { analyzeShelfCameraCapture, analyzeShelfImage } from './audit'
export { sendChatMessage } from './chat'
export { getDatabaseRecord, queryDatabaseRecords, clearDatabaseRecords, downloadSystemBackup, restoreSystemBackup } from './database'
export {
  clearTickets,
  getTicket,
  getWebhookSettings,
  listTickets,
  redispatchTicket,
  runClosedLoop,
  saveWebhookSettings,
  testWebhook,
  updateTicketStatus,
  verifyTicket,
} from './tickets'
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
