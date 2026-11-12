import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const readOptional = (url) => existsSync(url) ? readFileSync(url, "utf8") : "";
const pageSource = readOptional(new URL("./ProcessManagement.jsx", import.meta.url));
const drawerSource = readOptional(new URL("../components/process/WorkflowDetailDrawer.jsx", import.meta.url));
const matrixSource = readOptional(new URL("../components/process/WorkflowMatrix.jsx", import.meta.url));
const publishModalSource = readOptional(new URL("../components/process/WorkflowPublishModal.jsx", import.meta.url));
const localUploadSource = readOptional(new URL("../components/process/WorkflowLocalMediaUpload.jsx", import.meta.url));
const contentCreationSource = readOptional(new URL("./ContentCreation.jsx", import.meta.url));
const styles = readOptional(new URL("../styles/pages.css", import.meta.url));

test("workflow page composes Kim matrix, detail drawer, and controlled publish modal", () => {
  assert.match(pageSource, /import WorkflowMatrix/);
  assert.match(pageSource, /import WorkflowDetailDrawer/);
  assert.match(pageSource, /import WorkflowPublishModal/);
  assert.match(pageSource, /<WorkflowMatrix/);
  assert.match(pageSource, /<WorkflowDetailDrawer/);
  assert.match(pageSource, /<WorkflowPublishModal/);
});

test("workflow drawer is the only publish entry and uses a double pending-review gate", () => {
  assert.match(pageSource, /app\.loadTaskCreation/);
  assert.match(pageSource, /if \(!creation\) return/);
  assert.match(pageSource, /app\.publishCreation/);
  assert.match(pageSource, /app\.refreshPublishStatus/);
  assert.ok((pageSource.match(/canPublishWorkflowTask\(/g) || []).length >= 2);
  assert.match(drawerSource, /canPublish/);
  assert.match(drawerSource, /canPublish \? \(/);
  assert.match(drawerSource, /onPublish\?\.\(task\)/);
  assert.doesNotMatch(contentCreationSource, /app\.publishCreation/);
  assert.doesNotMatch(contentCreationSource, /app\.refreshPublishStatus/);
  assert.doesNotMatch(contentCreationSource, /showPublishConfirm && pendingPublishDraft/);
  assert.doesNotMatch(contentCreationSource, /onClick=\{openPublishConfirm\}/);
  assert.match(contentCreationSource, /publishMediaCandidates:\s*buildPublishMediaCandidates\(\)/);
});

test("closing or switching task invalidates a pending publish open", () => {
  assert.match(pageSource, /const selectedTaskIdRef = useRef\(""\)/);
  assert.match(pageSource, /const invalidatePendingPublishOpen = \(\) =>/);
  assert.match(pageSource, /publishOpenRunRef\.current \+= 1/);
  assert.match(pageSource, /selectedTaskIdRef\.current !== task\.id/);
  assert.match(pageSource, /onSelectTask=\{selectTask\}/);
  assert.match(pageSource, /onClose=\{closeTaskDetails\}/);
});

test("workflow closes publish gates synchronously while a task stage is moving", () => {
  assert.match(pageSource, /movingTaskIdsRef/);
  assert.match(pageSource, /isTaskTransitioning/);
  assert.ok((pageSource.match(/isTaskTransitioning\(/g) || []).length >= 3);
  assert.match(pageSource, /transitioning=\{isTaskTransitioning\(selectedTask\?\.id\)\}/);
  assert.match(drawerSource, /transitioning/);
  assert.match(drawerSource, /disabled=\{transitioning\}/);
});

test("workflow publish submission has an in-flight gate independent of modal renders", () => {
  assert.match(pageSource, /publishInFlightRef/);
  assert.match(pageSource, /publishInFlightRef\.current/);
  assert.match(pageSource, /if \(publishInFlightRef\.current\) return/);
  assert.match(pageSource, /publishInFlightRef\.current = true/);
  assert.match(pageSource, /publishInFlightRef\.current = false/);
});

test("workflow retries only a trusted failed or cancelled publish state", () => {
  assert.match(pageSource, /const retry = \["failed", "cancelled"\]\.includes\(publishState\?\.status\)/);
  assert.match(pageSource, /buildWorkflowPublishPayload\(\{ \.\.\.publishDraft, retry \}\)/);
});

test("workflow publish polling is scoped to the open creation and always cleaned up", () => {
  assert.match(pageSource, /isWorkflowPublishActive\(publishState\?\.status\)/);
  assert.match(pageSource, /window\.setInterval/);
  assert.match(pageSource, /5000/);
  assert.match(pageSource, /window\.clearInterval/);
  assert.match(pageSource, /publishDraft\.creationId/);
});

test("workflow publish modal supports image multi-select and delegated local media upload", () => {
  assert.match(publishModalSource, /draft, publishState, deviceConfigured, platformSupported, busy, uploading = false, suspended = false, error/);
  assert.match(publishModalSource, /draft\.mediaCandidates/);
  assert.match(publishModalSource, /draft\.targetPlatform/);
  assert.match(publishModalSource, /PUBLISH_PLATFORMS\.map/);
  assert.match(publishModalSource, /updateDraft\(\{ targetPlatform: event\.target\.value \}\)/);
  assert.match(publishModalSource, /当前平台暂不支持自动发布/);
  assert.match(publishModalSource, /onConfigureDevice/);
  assert.match(publishModalSource, /onRefresh/);
  assert.match(publishModalSource, /onConfirm/);
  assert.match(publishModalSource, /<WorkflowLocalMediaUpload/);
  assert.match(publishModalSource, /onUploadImages/);
  assert.match(publishModalSource, /onUploadVideo/);
  assert.match(localUploadSource, /type="file"/);
  assert.match(localUploadSource, /multiple=\{isImage\}/);
  assert.match(localUploadSource, /image\/jpeg,image\/png,image\/webp/);
  assert.match(publishModalSource, /type=\{draft\.type === "image" \? "checkbox" : "radio"\}/);
  assert.doesNotMatch(`${publishModalSource}\n${localUploadSource}`, /\bapp\.|starxApi|URL\.createObjectURL|blob:/);
  assert.match(pageSource, /app\.uploadPublishImages/);
  assert.match(pageSource, /app\.uploadPublishVideo/);
});

test("workflow reloads persisted publish state after a submission error so failure can be retried", () => {
  assert.match(pageSource, /catch \(error\)[\s\S]*app\.loadTaskCreation\?\.\(latestTask\)\.catch/);
});

test("workflow local media upload uses a responsive branded card", () => {
  assert.match(localUploadSource, /workflow-publish-local-upload-icon/);
  assert.match(localUploadSource, /从本地选择/);
  assert.match(localUploadSource, /支持 JPG、PNG、WebP，可多选；单张不超过 10MB/);
  assert.match(localUploadSource, /仅支持 MP4，单个文件不超过 80MB/);
  assert.match(localUploadSource, /workflow-publish-local-upload-action/);
  assert.match(styles, /\.workflow-publish-local-upload\s*\{[^}]*border[^}]*background/s);
  assert.match(styles, /\.workflow-publish-local-upload-input\s*\{[^}]*position:\s*absolute[^}]*opacity:\s*0/s);
});

test("workflow publish media opens MediaLightbox for image and video preview", () => {
  assert.match(publishModalSource, /import MediaLightbox, \{ useMediaLightbox \} from "\.\.\/MediaLightbox"/);
  assert.match(publishModalSource, /const mediaLightbox = useMediaLightbox\(\)/);
  assert.match(publishModalSource, /createImageSlide|createVideoSlide/);
  assert.match(publishModalSource, /mediaLightbox\.openMedia\(/);
  assert.match(publishModalSource, /workflow-publish-media-preview-btn/);
  assert.match(publishModalSource, /<MediaLightbox/);
  assert.match(publishModalSource, /event\.key === "Escape"[\s\S]*mediaLightbox\.open[\s\S]*mediaLightbox\.closeMedia\(\)/);
  assert.doesNotMatch(publishModalSource, /const \[previewVideo, setPreviewVideo\]/);
  assert.doesNotMatch(publishModalSource, /workflow-publish-video-preview-overlay/);
});

test("workflow publish modal keeps the backend visibility mapping exact", () => {
  assert.match(publishModalSource, /<option value="0">默认公开<\/option>/);
  assert.match(publishModalSource, /<option value="1">好友可见<\/option>/);
  assert.match(publishModalSource, /<option value="2">仅自己可见<\/option>/);
});

test("workflow publish modal treats current device errors as a recoverable configuration state", () => {
  assert.match(
    publishModalSource,
    /isPublishDeviceConfigurationError\(error, publishState\?\.errorMessage\)/,
  );
  assert.match(publishModalSource, /publishNeedsConfiguration/);
  assert.match(publishModalSource, /检查设备配置/);
  assert.doesNotMatch(publishModalSource, /&& !publishNeedsConfiguration/);
});

test("workflow publish modal cannot close while a publish POST is busy", () => {
  assert.match(publishModalSource, /const busyRef = useRef\(busy\)/);
  assert.match(publishModalSource, /busyRef\.current = busy/);
  assert.match(
    publishModalSource,
    /const requestClose = \(\) => \{\s*if \(busyRef\.current\) return;\s*if \(suspended\) return;\s*onCloseRef\.current\?\.\(\);\s*\}/,
  );
  assert.match(
    publishModalSource,
    /event\.key === "Escape"[\s\S]{0,180}requestClose\(\)/,
  );
  assert.doesNotMatch(
    publishModalSource,
    /event\.target === event\.currentTarget\) requestClose\(\)/,
  );
  assert.match(publishModalSource, /aria-busy=\{busy\}/);
  assert.ok((publishModalSource.match(/disabled=\{busy\}/g) || []).length >= 2);
});

test("workflow publish modal suspends the underlying drawer modal", () => {
  assert.match(pageSource, /suspended=\{Boolean\(publishDraft\)\}/);
  assert.match(drawerSource, /suspended/);
  assert.match(drawerSource, /if \(!task \|\| suspended\) return undefined/);
  assert.match(drawerSource, /aria-modal=\{suspended \? undefined : "true"\}/);
  assert.match(drawerSource, /aria-hidden=\{suspended \|\| undefined\}/);
});

test("account configuration suspends the publish modal without discarding its draft", () => {
  assert.match(pageSource, /suspended=\{Boolean\(app\.showAddAccountModal\)\}/);
  assert.doesNotMatch(pageSource, /showAddAccountModal[\s\S]{0,120}setPublishDraft\(null\)/);
  assert.match(publishModalSource, /suspended = false/);
  assert.match(publishModalSource, /if \(!draft \|\| suspended\) return undefined/);
  assert.match(publishModalSource, /\[draft\?\.creationId, suspended, mediaLightbox\.open, mediaLightbox\.closeMedia\]/);
  assert.match(publishModalSource, /aria-modal=\{suspended \? undefined : "true"\}/);
  assert.match(publishModalSource, /aria-hidden=\{suspended \|\| undefined\}/);
  assert.match(publishModalSource, /inert=\{suspended \? "" : undefined\}/);
  assert.match(publishModalSource, /const suspendedRef = useRef\(suspended\)/);
  assert.match(publishModalSource, /suspendedRef\.current = suspended/);
  assert.match(publishModalSource, /!suspendedRef\.current[\s\S]*previouslyFocused\.focus\(\)/);
  assert.match(styles, /\.workflow-publish-overlay\[aria-hidden="true"\][\s\S]{0,120}pointer-events:\s*none/);
});

test("workflow publish modal blocks an empty description with a clear message", () => {
  assert.match(publishModalSource, /const descriptionReady = Boolean\(String\(draft\.description \|\| ""\)\.trim\(\)\)/);
  assert.match(publishModalSource, /&& descriptionReady/);
  assert.match(publishModalSource, /请填写发布文案后再发布/);
  assert.match(publishModalSource, /aria-invalid=\{!descriptionReady\}/);
});

test("workflow publish modal exposes an optional title using the existing field design", () => {
  assert.match(publishModalSource, /作品标题 <em>选填<\/em>/);
  assert.match(publishModalSource, /value=\{draft\.title \|\| ""\}/);
  assert.match(publishModalSource, /maxLength=\{255\}/);
  assert.match(publishModalSource, /updateDraft\(\{ title: event\.target\.value \}\)/);
  assert.match(styles, /\.workflow-publish-field-hint/);
});

test("workflow display components stay app-independent and retain develop controls", () => {
  assert.match(matrixSource, /tasks, stages, selectedTaskId, onSelectTask, currentPage, totalPages, onPageChange/);
  assert.match(matrixSource, /onPageChange\?\.\(safeCurrentPage - 1\)/);
  assert.match(matrixSource, /onPageChange\?\.\(safeCurrentPage \+ 1\)/);
  assert.match(drawerSource, /onAdvance, onRetreat, onMove, onDelete, onDuplicate, onOpen, onPublish/);
  assert.match(drawerSource, /onRetreat\?\.\(task\)/);
  assert.match(pageSource, /searchKeyword/);
  assert.match(pageSource, /assigneeFilter/);
  assert.match(pageSource, /app\.moveTask/);
  assert.match(pageSource, /app\.deleteTask/);
  assert.match(pageSource, /app\.startBlankCreation/);
  assert.match(pageSource, /app\.openTaskCreation/);
  assert.doesNotMatch(`${matrixSource}\n${drawerSource}`, /\bapp\.|starxApi/);
  assert.doesNotMatch(pageSource, /Math\.random/);
});

test("workflow drawer exposes one-click duplication with an in-flight guard", () => {
  assert.match(pageSource, /const \[duplicatingTaskId, setDuplicatingTaskId\] = useState\(""\)/);
  assert.match(pageSource, /await app\.duplicateTask\(task\.id\)/);
  assert.match(pageSource, /duplicating=\{duplicatingTaskId === selectedTask\?\.id\}/);
  assert.match(pageSource, /onDuplicate=\{duplicateTask\}/);
  assert.match(drawerSource, /onClick=\{\(\) => onDuplicate\?\.\(task\)\}/);
  assert.match(drawerSource, /快速复制流程/);
});

test("workflow matrix keeps Kim fixed-task row structure across all seven develop stages", () => {
  assert.match(matrixSource, /className="workflow-matrix-header"/);
  assert.match(matrixSource, /className="workflow-task-header" role="columnheader">任务信息/);
  assert.match(matrixSource, /className={`workflow-matrix-row/);
  assert.match(matrixSource, /className="workflow-task-fixed"/);
  assert.match(matrixSource, /className="workflow-task-info"/);
  assert.match(matrixSource, /className={`workflow-stage-cell/);
  assert.match(matrixSource, /safeStages\.map\(\(stage/);
  assert.match(pageSource, /const ROWS_PER_PAGE = \d+/);
  assert.match(pageSource, /filteredTasks\.slice\(startIndex, startIndex \+ ROWS_PER_PAGE\)/);
  assert.match(pageSource, /tasks=\{pagedTasks\}/);
  assert.match(pageSource, /stages=\{WORKFLOW_STAGES\}/);
  assert.doesNotMatch(pageSource, /colPages|setColPage/);
  assert.doesNotMatch(matrixSource, /workflow-matrix-column|workflow-task-card/);
});

test("workflow stage cells only select the task and never mutate its stage directly", () => {
  assert.match(matrixSource, /onClick=\{\(event\) => \{\s*event\.stopPropagation\(\);\s*onSelectTask\?\.\(task\);\s*\}\}/);
  assert.doesNotMatch(matrixSource, /onSelectTask\?\.\(task,\s*stage/);
  assert.doesNotMatch(matrixSource, /onMove|moveTask|app\./);
});

test("workflow matrix preserves Kim sticky header and fixed task-column visual language", () => {
  assert.match(styles, /\.workflow-matrix-header,\s*\.workflow-matrix-row[\s\S]{0,180}grid-template-columns:\s*360px repeat\(7,\s*minmax\(120px,\s*1fr\)\)/);
  assert.match(styles, /\.workflow-matrix-header[\s\S]{0,160}position:\s*sticky[\s\S]{0,100}top:\s*0/);
  assert.match(styles, /\.workflow-task-header[\s\S]{0,180}position:\s*sticky[\s\S]{0,100}left:\s*0/);
  assert.match(styles, /\.workflow-task-fixed[\s\S]{0,180}position:\s*sticky[\s\S]{0,100}left:\s*0/);
  assert.match(styles, /\.workflow-matrix-row:nth-child\(even\)/);
  assert.match(styles, /\.workflow-stage-cell\.overdue/);
  assert.match(styles, /\.workflow-pagination/);
});

test("workflow drawer uses real handoff fields and behaves as a keyboard modal", () => {
  assert.match(drawerSource, /task\.handoffNote/);
  assert.match(drawerSource, /task\.updated/);
  assert.doesNotMatch(drawerSource, /task\.note \|\| task\.description/);
  assert.match(drawerSource, /role="dialog"/);
  assert.match(drawerSource, /aria-modal=\{suspended \? undefined : "true"\}/);
  assert.match(drawerSource, /dialogRef/);
  assert.match(drawerSource, /event\.key === "Escape"/);
  assert.match(drawerSource, /event\.key !== "Tab"/);
  assert.match(drawerSource, /previouslyFocused/);
  assert.match(drawerSource, /createPortal/);
  assert.match(drawerSource, /workflow-detail-layer/);
  assert.match(drawerSource, /document\.body/);
});

test("workflow detail layer blocks background clicks when open", () => {
  const detailStyles = readOptional(new URL("../styles/workflow-detail.css", import.meta.url));
  assert.match(detailStyles, /\.workflow-detail-layer\s*\{[\s\S]*pointer-events:\s*auto/);
  assert.match(detailStyles, /\.workflow-detail-layer\[data-suspended="true"\]\s*\{[\s\S]*pointer-events:\s*none/);
  assert.doesNotMatch(detailStyles, /\.workflow-drawer-backdrop\s*\{[\s\S]*pointer-events:\s*none/);
});

test("workflow styles are namespaced, responsive, and motion-safe", () => {
  assert.match(styles, /\.workflow-page\s*\{/);
  assert.match(styles, /\.workflow-matrix\s*\{/);
  assert.match(styles, /\.workflow-drawer\s*\{/);
  assert.match(styles, /\.workflow-publish-modal\s*\{/);
  assert.match(styles, /@media\s*\(max-width:\s*700px\)[\s\S]*\.workflow-page/);
  assert.match(styles, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.workflow-drawer/);
});
