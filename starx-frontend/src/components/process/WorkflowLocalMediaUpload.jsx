export default function WorkflowLocalMediaUpload({ type, uploading, disabled, onSelect }) {
  const isImage = type === "image";
  const label = isImage ? "图片" : "视频";

  return (
    <label
      className={`workflow-publish-local-upload ${uploading ? "uploading" : ""}`}
      aria-disabled={disabled}
      aria-busy={uploading}
    >
      <input
        className="workflow-publish-local-upload-input"
        type="file"
        accept={isImage ? ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" : "video/mp4"}
        multiple={isImage}
        disabled={disabled}
        onChange={async (event) => {
          const input = event.currentTarget;
          const files = Array.from(input.files || []);
          if (files.length) await onSelect?.(files);
          input.value = "";
        }}
      />
      <span className="workflow-publish-local-upload-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
        </svg>
      </span>
      <span className="workflow-publish-local-upload-copy">
        <strong>{uploading ? `正在上传${label}到 OSS…` : `从本地选择${label}`}</strong>
        <small>
          {uploading
            ? "请保持当前窗口开启，上传完成后将自动选中"
            : isImage
              ? "支持 JPG、PNG、WebP，可多选；单张不超过 10MB"
              : "仅支持 MP4，单个文件不超过 80MB"}
        </small>
      </span>
      <span className="workflow-publish-local-upload-action" aria-hidden="true">
        {uploading ? "上传中" : `选择${label}`}
      </span>
    </label>
  );
}
