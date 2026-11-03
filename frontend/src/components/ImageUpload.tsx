import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import type { ImageUploadResult } from '../lib/api';
import { formatNumber, uploadImage } from '../lib/api';

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

interface ImageUploadProps {
  disabled?: boolean;
  descriptionEmpty: boolean;
  onFillDescription: (text: string) => void;
}

/**
 * Label-photo upload. The file is sent to the backend, which strips
 * EXIF before any use and returns metadata + OCR text. The preview
 * shown here is a local object URL of the selected file — it is NOT
 * the stripped file, because the upload response contains no image
 * bytes; the UI says exactly that. OCR text (or typed text) goes
 * into the description for the user to confirm before analysing.
 */
export default function ImageUpload({
  disabled,
  descriptionEmpty,
  onFillDescription,
}: ImageUploadProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImageUploadResult | null>(null);
  const [ocrFilled, setOcrFilled] = useState(false);
  const previousUrlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (previousUrlRef.current) URL.revokeObjectURL(previousUrlRef.current);
    };
  }, []);

  function clearPreview() {
    if (previousUrlRef.current) {
      URL.revokeObjectURL(previousUrlRef.current);
      previousUrlRef.current = null;
    }
    setPreviewUrl(null);
  }

  async function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError(null);
    setResult(null);
    setOcrFilled(false);
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setError('Only JPEG, PNG, or WebP images are accepted.');
      clearPreview();
      setFileName(null);
      return;
    }
    if (file.size > MAX_BYTES) {
      setError('Image is larger than 5 MB. Choose a smaller image.');
      clearPreview();
      setFileName(null);
      return;
    }
    clearPreview();
    const url = URL.createObjectURL(file);
    previousUrlRef.current = url;
    setPreviewUrl(url);
    setFileName(file.name);
    setLoading(true);
    try {
      const uploaded = await uploadImage(file);
      setResult(uploaded);
      if (uploaded.ocr_available && uploaded.ocr_text?.trim() && descriptionEmpty) {
        onFillDescription(uploaded.ocr_text.trim());
        setOcrFilled(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Image upload failed.');
    } finally {
      setLoading(false);
    }
  }

  const ocrText = result?.ocr_text?.trim() ?? '';

  return (
    <section aria-label="Label photo upload" className="mt-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">
        Label photo
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Upload a photo of the label (JPEG, PNG, or WebP, up to 5 MB). The
        server strips location and camera data (EXIF) before any use.
      </p>
      <label
        htmlFor="label-photo"
        className="mt-2 flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-base font-semibold text-[var(--text-primary)]"
      >
        {loading ? 'Uploading…' : 'Choose label photo'}
        <input
          id="label-photo"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(event) => void handleChange(event)}
          disabled={disabled || loading}
          className="sr-only"
        />
      </label>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {error}
        </p>
      ) : null}
      {previewUrl ? (
        <figure className="mt-3">
          <img
            src={previewUrl}
            alt={fileName ? `Preview of ${fileName}` : 'Preview of uploaded label photo'}
            className="max-h-64 w-auto rounded-lg border border-[var(--border)]"
          />
          <figcaption className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
            This preview is the file on your device. The server strips EXIF
            before any use; the preview itself is not the stripped file.
          </figcaption>
        </figure>
      ) : null}
      {result ? (
        <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3">
          <p className="font-mono text-xs text-[var(--text-secondary)]">
            {result.stripped ? 'EXIF stripped' : 'EXIF stripping not confirmed'} ·{' '}
            {formatNumber(result.width)}×{formatNumber(result.height)} ·{' '}
            {result.format} · SHA-256 {result.sha256.slice(0, 16)}…
          </p>
          {result.note ? (
            <p className="mt-1 text-sm text-[var(--text-secondary)]">{result.note}</p>
          ) : null}
          {!result.ocr_available ? (
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              OCR unavailable on this server — type the label text.
            </p>
          ) : ocrText ? (
            <>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-primary)]">
                <span className="font-semibold">Label text found:</span> {ocrText}
              </p>
              {ocrFilled ? (
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Description filled with the label text — edit it before
                  checking.
                </p>
              ) : (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onFillDescription(ocrText);
                    setOcrFilled(true);
                  }}
                  className="mt-2 min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] disabled:opacity-50"
                >
                  Fill description with label text
                </button>
              )}
            </>
          ) : (
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              No readable text was found in this image. Type the label text
              yourself.
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}
