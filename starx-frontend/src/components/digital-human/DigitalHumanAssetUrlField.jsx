export default function DigitalHumanAssetUrlField({
  id,
  label,
  value,
  placeholder,
  accept,
  uploading = false,
  disabled = false,
  onChange,
  onUpload,
}) {
  const handleFileChange = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) await onUpload(file);
  };

  return (
    <div className="dh-asset-field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <div className="dh-asset-input-row">
        <input
          id={id}
          type="url"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
        />
        <label className={`btn dh-asset-upload ${uploading ? "is-uploading" : ""} ${disabled ? "is-disabled" : ""}`}>
          <input
            type="file"
            accept={accept}
            disabled={disabled}
            onChange={handleFileChange}
          />
          {uploading ? "上传中…" : "本地上传"}
        </label>
      </div>
    </div>
  );
}
