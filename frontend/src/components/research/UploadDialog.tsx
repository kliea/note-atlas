import { useEffect, useRef, useState, type DragEvent } from "react";

type UploadDialogProps = {
  onClose: () => void;
  onFiles: (files: File[]) => void;
};

export function UploadDialog({ onClose, onFiles }: UploadDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setOver(false);
    onFiles(Array.from(event.dataTransfer.files));
  }

  return (
    <div className="research-modal-backdrop" onClick={onClose}>
      <div
        className="research-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="research-upload-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="research-upload-title">Upload papers</h3>
        <div
          className={`research-dropzone ${over ? "over" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.stopPropagation();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          Drop PDFs here, or click to choose
          <small>Parsed on this machine. The PDF never leaves it.</small>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(event) => onFiles(Array.from(event.target.files ?? []))}
        />
        <div className="research-row research-row-end">
          <button type="button" className="nav-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
