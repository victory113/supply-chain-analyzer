import { useCallback, useRef, useState } from 'react';
import type { DragEvent } from 'react';

const MAX_BYTES = 10 * 1024 * 1024; // must match the backend's max_upload_bytes

interface UploadDropzoneProps {
  onFile: (file: File) => void;
  disabled?: boolean;
}

/**
 * Drag-and-drop CSV picker.
 *
 * Extension and size are checked client-side purely for fast feedback — the
 * backend validates both again, since a client check is not a security control.
 */
export function UploadDropzone({ onFile, disabled = false }: UploadDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.csv')) {
        setError('That file is not a .csv — export your data as CSV and try again.');
        return;
      }
      if (file.size > MAX_BYTES) {
        setError(
          `That file is ${(file.size / 1_048_576).toFixed(1)} MB; the limit is 10 MB.`,
        );
        return;
      }
      setError(null);
      onFile(file);
    },
    [onFile],
  );

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    accept(event.dataTransfer.files[0]);
  };

  const openPicker = () => {
    if (!disabled) inputRef.current?.click();
  };

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div
        className={`dropzone${dragging ? ' dragging' : ''}${disabled ? ' disabled' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={openPicker}
        onKeyDown={(event) => {
          // Keyboard parity with the click target — a div isn't focusable or
          // activatable for free.
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openPicker();
          }
        }}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label="Upload a CSV file"
      >
        <div className="dropzone-icon" aria-hidden="true">
          📄
        </div>
        <div className="dropzone-title">
          {disabled ? 'Uploading…' : 'Drop a CSV here, or click to browse'}
        </div>
        <div className="dropzone-hint">
          Shipment exports up to 10 MB · columns are matched automatically
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        disabled={disabled}
        onChange={(event) => {
          accept(event.target.files?.[0]);
          // Reset so re-picking the same file still fires a change event.
          event.target.value = '';
        }}
      />

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
